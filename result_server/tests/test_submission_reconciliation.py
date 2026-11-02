"""No live service: real runner payloads, fake reader and temporary SQLite."""
import json
from types import SimpleNamespace

import pytest
from test_scheduled_submission_uncertainty import scheduled
import trigger_runner as runner
from utils.gitlab_pipeline import GitLabPipelineSubmitResult
from utils.submission_reconciliation import (
    PipelinePage, snapshot, inspect_submission, confirm_submission,
)


class Reader:
    def __init__(self, row):
        payload = json.loads(row['payload_json'])
        self.project = payload['gitlab_project'].split('/', 1)[1]
        self.ref = payload['payload']['ref']
        self.values = dict(payload['payload']['variables'])
        self.ids = [42]
        self.next_page = None
        self.failure = False

    def project_path(self, target, project_id):
        assert project_id == 7
        return self.project

    def pipelines(self, target, ref, page):
        if self.failure:
            raise RuntimeError('secret-must-not-leak')
        return PipelinePage([dict(id=i, project_id=7, ref=self.ref, source='trigger')
                             for i in self.ids], self.next_page)

    def variables(self, target, pipeline_id):
        return [dict(key=k, value=v) for k, v in self.values.items()]


@pytest.fixture
def attempt(scheduled):
    store, kwargs = scheduled
    runner.run_triggers(**kwargs, submit_pipeline=lambda *a, **k:
                        GitLabPipelineSubmitResult(0, {}, ['timeout']))
    run = store.list_trigger_runs(statuses=['submission_unknown'])[0]
    row = snapshot(store, run['id'])
    payload = json.loads(row['payload_json'])
    target = SimpleNamespace(id=payload['gitlab_target'], repo=payload['gitlab_project'])
    return store, kwargs, row, target, Reader(row)


def test_inspection_and_explicit_confirmation(attempt):
    store, kwargs, row, target, reader = attempt
    assert inspect_submission(row, target, reader).decision == 'accepted'
    assert snapshot(store, row['id']) == row  # inspection cannot mutate
    assert confirm_submission(store, row, target, reader).pipeline_id == 42
    current = snapshot(store, row['id'])
    assert current['status'] == 'submitted'
    assert current['errors_json'] == row['errors_json']
    payload = json.loads(current['payload_json'])
    assert payload['submit']['response']['id'] == 42
    from utils.execution_history import list_execution_history, summarize_execution_history
    history = next(item for item in list_execution_history(store) if item['id'] == row['id'])
    summary = summarize_execution_history(history)
    assert summary['pipeline_url'] == f'https://{target.repo}/-/pipelines/42'
    assert payload['reconciliation']['previous_submit']['acceptance'] == 'unknown'
    assert confirm_submission(store, row, target, reader).decision == 'history_changed'
    # Confirming acceptance must not cause a second POST for the same slot.
    def forbidden(*a, **k):
        pytest.fail('resubmitted confirmed attempt')
    runner.run_triggers(**kwargs, submit_pipeline=forbidden)


@pytest.mark.parametrize('mode,decision', [
    ('none', 'no_candidates'), ('many', 'multiple_candidates'),
    ('failure', 'lookup_failed'), ('pagination', 'incomplete_lookup'),
    ('duplicate', 'incomplete_lookup'), ('project', 'no_candidates'),
    ('ref', 'no_candidates'), ('variable', 'no_candidates'),
    ('destination', 'no_candidates'), ('backend', 'no_candidates'), ('missing', 'insufficient_evidence'),
    ('duplicate_variable', 'insufficient_evidence'),
])
def test_nonunique_or_incomplete_evidence_keeps_hold(attempt, mode, decision):
    store, kwargs, row, target, reader = attempt
    if mode == 'none': reader.ids = []
    if mode == 'many': reader.ids = [42, 43]
    if mode == 'failure': reader.failure = True
    if mode == 'pagination': reader.next_page = 9
    if mode == 'duplicate': reader.ids = [42, 42]
    if mode == 'project': reader.project = 'other/project'
    if mode == 'ref': reader.ref = 'main'
    if mode == 'variable': reader.values['BK_TRIGGER_ID'] = 'another-trigger'
    if mode == 'destination':
        key = 'BK_PORTAL_RESULT_SERVER' if 'BK_PORTAL_RESULT_SERVER' in reader.values else 'RESULT_SERVER'
        assert key in reader.values
        reader.values[key] = 'https://other.example.org'
    if mode == 'backend': reader.values['BK_PIPELINE_BACKEND'] = 'another-backend'
    if mode == 'missing': reader.values.pop('BK_TRIGGER_REASON')
    if mode == 'duplicate_variable':
        original = reader.variables
        reader.variables = lambda *a: original(*a) + original(*a)[:1]
    result = confirm_submission(store, row, target, reader)
    assert result.decision == decision
    assert 'secret' not in repr(result)
    assert snapshot(store, row['id']) == row
    assert store.has_scheduled_submission_hold(trigger_id=row['trigger_id'], reason=row['reason'])


def test_concurrent_history_change(attempt):
    store, _, row, target, reader = attempt
    with store.connect() as conn:
        conn.execute('UPDATE trigger_runs SET actor=? WHERE id=?', ('changed', row['id']))
    assert confirm_submission(store, row, target, reader).decision == 'history_changed'
    assert snapshot(store, row['id'])['status'] == 'submission_unknown'


@pytest.mark.parametrize('field,value', [('status','submitting'), ('status','submitted'),
    ('trigger_type','manual'), ('dry_run',1), ('reason','cron:0 10 * * *')])
def test_ineligible_or_legacy_evidence(attempt, field, value):
    store, _, row, target, reader = attempt
    altered = dict(row, **{field:value})
    assert inspect_submission(altered, target, reader).decision in ('ineligible','insufficient_evidence')
    assert snapshot(store, row['id']) == row


def test_complete_pagination(attempt):
    _, _, row, target, reader = attempt
    original = reader.pipelines
    reader.pipelines = lambda target, ref, page: (PipelinePage([], 2) if page == 1
                                                  else original(target, ref, page))
    assert inspect_submission(row, target, reader).decision == 'accepted'
    assert inspect_submission(row, target, reader, max_pages=1).decision == 'incomplete_lookup'


def test_read_transport_is_get_only_and_requires_complete_pagination(attempt):
    from io import BytesIO
    from urllib.parse import urlsplit
    from utils.submission_reconciliation import GitLabReadOnlyReader
    _, _, row, target, fake = attempt
    requests = []
    class Response(BytesIO):
        status = 200
        def __init__(self, req, data, headers):
            super().__init__(json.dumps(data).encode())
            self.url = req.full_url
            self.headers = headers
        def geturl(self): return self.url
    def opener(req, timeout):
        requests.append(req)
        assert req.method == 'GET'
        assert req.get_header('Private-token') == 'fake-read-token'
        path = urlsplit(req.full_url).path
        if path.endswith('/variables'):
            return Response(req, fake.variables(target, 42), {})
        if path.endswith('/pipelines'):
            return Response(req, fake.pipelines(target, fake.ref, 1).pipelines,
                            {'X-Page':'1', 'X-Next-Page':''})
        return Response(req, {'id':7, 'path_with_namespace':fake.project}, {})
    reader = GitLabReadOnlyReader(target, read_token='fake-read-token', opener=opener)
    assert inspect_submission(row, target, reader).decision == 'accepted'
    assert len(requests) == 3
    assert all('fake-read-token' not in request.full_url for request in requests)
    reader._open = lambda req, timeout: Response(req, [], {})
    assert inspect_submission(row, target, reader).decision == 'lookup_failed'


@pytest.mark.parametrize('mode', ['redirect', 'http', 'json', 'exception'])
def test_transport_failures_are_held_and_sanitized(attempt, mode):
    from io import BytesIO
    from utils.submission_reconciliation import GitLabReadOnlyReader
    store, _, row, target, _ = attempt
    class Response(BytesIO):
        status = 403 if mode == 'http' else 200
        headers = {'X-Page':'1', 'X-Next-Page':''}
        def geturl(self): return 'https://untrusted.example.org/'
    def opener(req, timeout):
        if mode == 'exception': raise TimeoutError('private-secret')
        response = Response(b'private-secret')
        if mode != 'redirect': response.geturl = lambda: req.full_url
        return response
    reader = GitLabReadOnlyReader(target, read_token='private-secret', opener=opener)
    result = confirm_submission(store, row, target, reader)
    assert result.decision == 'lookup_failed'
    assert 'private-secret' not in repr(result)
    assert snapshot(store, row['id']) == row
