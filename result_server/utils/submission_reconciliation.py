"""Read-only reconciliation and explicit accepted-only confirmation.

The injected reader must implement the read-only GitLab pipelines API contract:
https://docs.gitlab.com/api/pipelines/
No credential discovery, runner hook or retry operation lives here.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class PipelinePage:
    pipelines: list[dict]
    # None means the server positively reported the end, not a failed fetch.
    next_page: int | None


@dataclass(frozen=True)
class Reconciliation:
    decision: str
    pipeline_id: int | None = None


def snapshot(store, run_id):
    """Read an existing database without migrating or creating one."""
    conn = sqlite3.connect(Path(store.db_path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM trigger_runs WHERE id=?', (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def inspect_submission(row, target, reader, *, max_pages=10):
    """Reader methods: pipelines(target, ref, page), variables(target, pipeline_id).

    Pages must contain project_id/ref/source/id; variables is the complete API
    list of key/value entries. The reader must raise on HTTP/auth/parse failures
    or uncertain pagination. No missing candidate is proof of non-acceptance.
    """
    try:
        if (not row or row['trigger_type'] != 'scheduled' or row['dry_run']
                or row['status'] != 'submission_unknown'):
            return Reconciliation('ineligible')
        payload = json.loads(row['payload_json'])
        request = payload['payload']
        expected = request['variables']
        repo = target.repo.removesuffix('.git')
        host, project = repo.split('/', 1)
        if (not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', host)
                or any(p in ('', '.', '..') for p in project.split('/'))
                or not re.fullmatch(r'[A-Za-z0-9_./-]+', project)):
            return Reconciliation('insufficient_evidence')
        api = f'https://{host}/api/v4/projects/{quote(project, safe="")}/trigger/pipeline'
        if (payload['gitlab_target'] != target.id
                or payload['gitlab_project'].removesuffix('.git') != repo
                or payload['api_url'] != api
                or not isinstance(request['ref'], str) or not request['ref']
                or not isinstance(expected, dict) or not expected
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in expected.items())
                or expected.get('BK_TRIGGER_ID') != row['trigger_id']
                or expected.get('BK_TRIGGER_TYPE') != 'scheduled'
                or expected.get('BK_TRIGGER_REASON') != row['reason']
                or not re.search(r'@\d{4}-\d{2}-\d{2}T', row['reason'])):
            return Reconciliation('insufficient_evidence')
        backend = expected.get('BK_PIPELINE_BACKEND', 'benchkit')
        if backend not in ('benchkit', 'benchpark'):
            return Reconciliation('insufficient_evidence')
        matches = set()
        seen = set()
        page = 1
        for _ in range(max_pages):
            batch = reader.pipelines(target, request['ref'], page)
            if not isinstance(batch, PipelinePage) or not isinstance(batch.pipelines, list):
                return Reconciliation('lookup_failed')
            for pipeline in batch.pipelines:
                pipeline_id = pipeline['id']
                if type(pipeline_id) is not int or pipeline_id <= 0:
                    return Reconciliation('lookup_failed')
                # Repeated entries can mean a changing page boundary: do not
                # claim complete coverage of a moving result set.
                if pipeline_id in seen:
                    return Reconciliation('incomplete_lookup')
                seen.add(pipeline_id)
                if (pipeline['ref'] != request['ref'] or pipeline['source'] != 'trigger'):
                    continue
                # Resolve project identity independently of numeric pipeline IDs.
                if reader.project_path(target, pipeline['project_id']) != project:
                    continue
                entries = reader.variables(target, pipeline_id)
                actual = {}
                if not isinstance(entries, list):
                    return Reconciliation('lookup_failed')
                for item in entries:
                    key, value = item['key'], item['value']
                    if (not isinstance(key, str) or not isinstance(value, str) or key in actual
                            or item.get('variable_type', 'env_var') != 'env_var'):
                        return Reconciliation('insufficient_evidence')
                    actual[key] = value
                if any(key not in actual for key in expected):
                    return Reconciliation('insufficient_evidence')
                if (actual.get('BK_PIPELINE_BACKEND', 'benchkit') == backend
                        and all(actual.get(k) == v for k, v in expected.items())):
                    matches.add(pipeline_id)
            if batch.next_page is None:
                break
            if type(batch.next_page) is not int or batch.next_page != page + 1:
                return Reconciliation('incomplete_lookup')
            page = batch.next_page
        else:
            return Reconciliation('incomplete_lookup')
        if not matches:
            return Reconciliation('no_candidates')
        if len(matches) != 1:
            return Reconciliation('multiple_candidates')
        return Reconciliation('accepted', matches.pop())
    except Exception:
        # Reader exception bodies may contain authentication data or variables.
        return Reconciliation('lookup_failed')


def confirm_submission(store, original, target, reader):
    """Explicit operation; re-read evidence and CAS the entire saved snapshot.

    Only acceptance can be recorded. Original failure details remain in the
    payload audit and errors_json. Never called automatically by the runner.
    """
    result = inspect_submission(original, target, reader)
    if result.decision != 'accepted':
        return result
    payload = json.loads(original['payload_json'])
    payload['reconciliation'] = {
        'previous_submit': payload.get('submit'),
        'method': 'complete_pipeline_variables_match',
        'pipeline_id': result.pipeline_id,
    }
    payload['submit'] = {'status_code': 200, 'response': {'id': result.pipeline_id},
                         'request_attempted': True, 'acceptance': 'accepted'}
    columns = ('id', 'trigger_id', 'trigger_type', 'status', 'dry_run', 'reason',
               'payload_json', 'errors_json', 'actor', 'created_at', 'updated_at')
    where = ' AND '.join(f'{key} IS ?' for key in columns)
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        updated = conn.execute(
            'UPDATE trigger_runs SET status=?, payload_json=?, updated_at=? WHERE ' + where,
            ('submitted', json.dumps(payload, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(), *(original[key] for key in columns)),
        )
        if updated.rowcount != 1:
            return Reconciliation('history_changed')
    return result


class GitLabReadOnlyReader:
    """Explicit read token; GET only, pinned target, no redirects or token lookup."""
    def __init__(self, target, *, read_token, timeout=15, opener=None):
        import urllib.request
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        if not read_token or '\n' in read_token or '\r' in read_token:
            raise ValueError('A read token is required')
        self._target = target
        self._token = read_token
        self._timeout = timeout
        self._open = opener or urllib.request.build_opener(NoRedirect()).open

    def _get(self, target, suffix):
        import urllib.request
        if target != self._target:
            raise ValueError('Target changed')
        repo = target.repo.removesuffix('.git')
        host, project = repo.split('/', 1)
        if (not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', host)
                or not re.fullmatch(r'[A-Za-z0-9_./-]+', project)
                or any(part in ('', '.', '..') for part in project.split('/'))):
            raise ValueError('Invalid target')
        url = f'https://{host}/api/v4/projects/{quote(project, safe="")}{suffix}'
        req = urllib.request.Request(url, headers={'PRIVATE-TOKEN': self._token}, method='GET')
        with self._open(req, timeout=self._timeout) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError('Unexpected response')
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Response too large')
            return json.loads(raw), response.headers

    def project_path(self, target, project_id):
        data, _ = self._get(target, '')
        if type(project_id) is not int or data['id'] != project_id:
            raise ValueError('Project identity mismatch')
        return data['path_with_namespace']

    def pipelines(self, target, ref, page):
        from urllib.parse import urlencode
        query = urlencode({'ref': ref, 'source': 'trigger', 'page': page,
                           'per_page': 100, 'order_by': 'id', 'sort': 'asc'})
        data, headers = self._get(target, '/pipelines?' + query)
        # A missing header must not masquerade as the end of the result set.
        if headers.get('X-Page') != str(page) or headers.get('X-Next-Page') is None:
            raise ValueError('Missing pagination evidence')
        following = headers['X-Next-Page']
        return PipelinePage(data, int(following) if following else None)

    def variables(self, target, pipeline_id):
        if type(pipeline_id) is not int or pipeline_id <= 0:
            raise ValueError('Invalid pipeline identity')
        data, headers = self._get(target, f'/pipelines/{pipeline_id}/variables')
        if headers.get('X-Next-Page', ''):
            raise ValueError('Incomplete variables')
        return data
