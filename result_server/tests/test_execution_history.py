"""Persisted manual history renders without resubmission or cross-project links."""
import json
from pathlib import Path

import pytest

from test_execution_profiles import _admin_app, _cleanup, _login_admin
from utils.execution_profiles import ExecutionProfileStore
from utils.execution_history import (
    execution_result_links, list_execution_history, summarize_execution_history,
)
from utils.trigger_display import build_trigger_result_links


def request(store, *, project='gitlab.example.org/group/park', pipeline=42,
            status='submitted', dry_run=False, request_type='gitlab_pipeline'):
    return store.create_execution_request(
        request_type=request_type, status=status, dry_run=dry_run,
        profile_id='park-qws', target_ref='main', code='qws', system='ExampleSystem',
        actor='admin@test.com', errors=['Submission rejected'] if status != 'submitted' else [],
        payload={'gitlab_project': project, 'gitlab_target': 'park',
                 'payload': {'ref': 'main', 'variables': {'BK_PIPELINE_BACKEND': 'benchpark'}},
                 'submit': {'response': {'id': pipeline, 'web_url': 'javascript:alert(1)'}}},
    )


def result(path, *, project='gitlab.example.org/group/park', pipeline=42):
    path.write_text(json.dumps({
        'ci_project': project, 'pipeline_id': pipeline, 'execution_backend': 'benchpark',
        'execution_trigger': {'id': 'park-qws', 'type': 'manual_button'},
        'code': 'qws', 'system': 'ExampleSystem', 'FOM': 1, 'FOM_unit': 's',
    }))


def test_manual_requests_survive_reload_and_link_by_project_and_pipeline(tmp_path):
    db = tmp_path / 'portal.sqlite'
    store = ExecutionProfileStore(str(db))
    first = request(store)
    second = request(store, pipeline=43)
    failed = request(store, status='submit_failed')
    runner = store.create_trigger_run(trigger_id='nightly', trigger_type='scheduled',
        status='submitted', dry_run=False, payload={
            'gitlab_project': 'gitlab.example.org/group/kit',
            'submit': {'response': {'id': 42}}})
    assert first == runner  # independent SQLite sequences have overlapping IDs
    result(tmp_path / 'first.json')
    result(tmp_path / 'second.json', pipeline=43)
    result(tmp_path / 'other-project.json', project='other.example.org/group/park')
    result(tmp_path / 'unknown-pipeline.json', pipeline=999)
    runs = list_execution_history(ExecutionProfileStore(str(db)))
    assert {-first, -second, -failed, runner} == {run['id'] for run in runs}
    links = build_trigger_result_links(str(tmp_path), runs)
    assert [item['filename'] for item in links[-first]] == ['first.json']
    assert [item['filename'] for item in links[-second]] == ['second.json']
    assert -failed not in links and runner not in links
    summary = summarize_execution_history(next(run for run in runs if run['id'] == -first))
    assert summary['history_source'] == 'Manual' and summary['record_id'] == first
    assert summary['trigger_id'] == 'park-qws'
    assert summary['pipeline_url'] == 'https://gitlab.example.org/group/park/-/pipelines/42'


def test_previews_and_non_pipeline_requests_are_not_manual_execution_history(tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    request(store, dry_run=True)
    request(store, request_type='profile_preview')
    assert list_execution_history(store) == []


@pytest.mark.parametrize('project', ['javascript:alert(1)', 'user:secret@gitlab.example.org/g/p',
                                     'gitlab.example.org/../p', 'gitlab.example.org/g/p?token=secret'])
def test_history_never_renders_untrusted_pipeline_urls(tmp_path, project):
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    request(store, project=project)
    summary = summarize_execution_history(list_execution_history(store)[0])
    assert summary['pipeline_url'] == ''


def test_admin_history_get_reloads_manual_pipeline_and_result_without_submission(tmp_path, monkeypatch):
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    try:
        store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
        request_id = request(store)
        result(Path(dirs[0]) / 'manual-result.json')
        def deny(*args, **kwargs):
            raise AssertionError('History GET must not submit or contact GitLab')
        monkeypatch.setattr('routes.admin.submit_pipeline_plan', deny)
        monkeypatch.setattr('urllib.request.urlopen', deny)
        client = app.test_client()
        assert client.get('/admin/execution-profiles').status_code in (302, 403)
        _login_admin(client)
        for _ in range(2):
            response = client.get('/admin/execution-profiles')
            assert response.status_code == 200
            html = response.data.decode()
            assert f'Manual #{request_id}' in html
            assert 'https://gitlab.example.org/group/park/-/pipelines/42' in html
            assert '/results/detail/manual-result.json' in html
            assert 'javascript:alert' not in html
        assert len(store.list_execution_requests()) == 1
    finally:
        _cleanup(dirs)


def test_blocked_submission_remains_visible_without_pipeline_or_result_link(tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    request(store, status='submit_blocked')
    run = list_execution_history(store)[0]
    summary = summarize_execution_history(run)
    assert summary['status'] == 'submit_blocked'
    assert summary['error_summary'] == 'Submission rejected'
    assert summary['pipeline_url'] == ''


def test_history_sorts_sources_by_time_and_applies_one_combined_limit(tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    request_id = request(store)
    runner_id = store.create_trigger_run(trigger_id='nightly', trigger_type='scheduled',
                                        status='not_due', dry_run=True)
    with store.connect() as conn:
        conn.execute('UPDATE execution_requests SET created_at=? WHERE id=?',
                     ('2026-10-21T01:00:00Z', request_id))
        conn.execute('UPDATE trigger_runs SET created_at=? WHERE id=?',
                     ('2026-10-20T01:00:00Z', runner_id))
    assert [run['id'] for run in list_execution_history(store, limit=1)] == [-request_id]
    runner = list_execution_history(store)[1]
    assert runner['id'] == runner_id and runner['dry_run'] is True
    assert summarize_execution_history(runner)['history_source'] == 'Runner'


def test_history_filters_before_paging_and_orders_equal_timestamps(tmp_path):
    from test_execution_profiles import _profile, _scheduled_trigger

    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(_profile(id='park-qws'), actor='admin')
    store.upsert_trigger_definition(_scheduled_trigger(
        id='nightly', profile_id='park-qws'), actor='admin')
    request_id = request(store)
    runner_id = store.create_trigger_run(
        trigger_id='nightly', trigger_type='scheduled', status='submitted', dry_run=False)
    with store.connect() as conn:
        for table in ('execution_requests', 'trigger_runs'):
            conn.execute(f'UPDATE {table} SET created_at=?', ('2026-10-20T12:00:00Z',))
    for _ in range(85):
        store.create_trigger_run(trigger_id='routine', trigger_type='scheduled',
                                 status='not_due', dry_run=False)

    filters = dict(profile_id='park-qws', status='submitted',
                   since='2026-10-20', until='2026-10-20')
    rows = list_execution_history(store, **filters)
    assert {row['id'] for row in rows} == {-request_id, runner_id}
    assert rows[0]['id'] == runner_id  # source is the deterministic final tie-breaker
    pages = [list_execution_history(store, limit=1, offset=i, **filters)[0]['id']
             for i in range(2)]
    assert pages == [row['id'] for row in rows]
    assert list_execution_history(store, offset=2, **filters) == []
    assert [row['id'] for row in list_execution_history(store, trigger_id='nightly')] == [runner_id]
    assert list_execution_history(store, status="submitted' OR 1=1 --") == []
    assert list_execution_history(store, since='2026-10-21', until='2026-10-21',
                                  profile_id='park-qws') == []


def test_runner_profile_filter_uses_only_existing_definition(tmp_path):
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.create_trigger_run(trigger_id='deleted', trigger_type='scheduled',
                             status='submitted', dry_run=False)
    assert list_execution_history(store)[0]['profile_id'] == ''
    assert list_execution_history(store, profile_id='guessed') == []


@pytest.fixture
def history_client(tmp_path, monkeypatch):
    app, dirs = _admin_app(tmp_path / 'portal.sqlite')
    def deny(*args, **kwargs):
        raise AssertionError('History reads must not submit or contact GitLab')
    monkeypatch.setattr('routes.admin.submit_pipeline_plan', deny)
    monkeypatch.setattr('urllib.request.urlopen', deny)
    try:
        yield app, app.test_client(), ExecutionProfileStore(str(tmp_path / 'portal.sqlite')), Path(dirs[0])
    finally:
        _cleanup(dirs)


def test_history_search_paging_and_result_receipt_are_separate(history_client):
    from urllib.parse import urlparse, parse_qs
    from html.parser import HTMLParser

    app, client, store, received = history_client
    ids = [request(store, pipeline=100 + i) for i in range(41)]
    result(received / 'saved.json', pipeline=140)
    _login_admin(client)
    response = client.get('/admin/execution-profiles?history_profile_id=park-qws&history_status=submitted')
    html = response.data.decode()
    assert response.status_code == 200
    assert 'Submission / Decision' in html and 'CI: Not checked' in html
    assert '1 matching Result' in html and 'No matching Result' in html
    assert f'Manual #{ids[0]} /' not in html
    assert f'Manual #{ids[-1]} /' in html
    class Links(HTMLParser):
        hrefs = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'a' and attrs.get('aria-label') == 'Next page':
                self.hrefs.append(attrs['href'])
    parser = Links()
    parser.feed(html)
    next_url = parser.hrefs[0]
    assert parse_qs(urlparse(next_url).query) == {
        'history_profile_id': ['park-qws'], 'history_status': ['submitted'], 'history_page': ['2']}
    second = client.get(next_url).data.decode()
    assert f'Manual #{ids[0]} /' in second and f'Manual #{ids[-1]} /' not in second
    assert 'aria-label="Next page"' not in second
    assert len(store.list_execution_requests(limit=100)) == 41


def test_all_result_links_include_fifth_and_do_not_cross_projects(history_client):
    _app, client, store, received = history_client
    request_id = request(store)
    for i in range(6):
        result(received / f'matching-{i}.json')
    result(received / 'wrong-project.json', project='other.example.org/group/park')
    _login_admin(client)
    history = client.get('/admin/execution-profiles').data.decode()
    path = f'/admin/execution-profiles/history/manual/{request_id}/results'
    assert path in history and 'View all 6 Results' in history
    detail = client.get(path)
    assert detail.status_code == 200
    for i in range(6):
        assert f'/results/detail/matching-{i}.json' in detail.data.decode()
    assert 'wrong-project.json' not in detail.data.decode()
    assert 'Not checked' in detail.data.decode()


def test_project_collisions_outside_filter_still_exclude_legacy_result(history_client):
    _app, client, store, received = history_client
    request_id = request(store)
    request(store, project='other.example.org/group/park')
    (received / 'legacy.json').write_text(json.dumps({
        'pipeline_id': 42, 'execution_backend': 'benchpark', 'Exp': 'legacy',
    }))
    result(received / 'qualified.json')
    _login_admin(client)
    detail = client.get(f'/admin/execution-profiles/history/manual/{request_id}/results')
    assert detail.status_code == 200
    assert '/results/detail/qualified.json' in detail.data.decode()
    assert '/results/detail/legacy.json' not in detail.data.decode()


def test_history_does_not_assign_result_by_reusable_trigger_alone(history_client):
    _app, client, store, received = history_client
    runner_id = store.create_trigger_run(
        trigger_id='park-qws', trigger_type='manual_button', status='submitted', dry_run=False,
        payload={'gitlab_project': 'gitlab.example.org/group/park',
                 'submit': {'response': {'id': 42}}})
    (received / 'unidentified.json').write_text(json.dumps({
        'execution_trigger': {'id': 'park-qws', 'type': 'manual_button'},
    }))
    _login_admin(client)
    detail = client.get(f'/admin/execution-profiles/history/runner/{runner_id}/results')
    assert 'No matching Result' in detail.data.decode()
    assert 'unidentified.json' not in detail.data.decode()


def test_history_escape_filter_and_result_label(history_client):
    _app, client, store, received = history_client
    request_id = request(store)
    (received / 'saved.json').write_text(json.dumps({
        'ci_project': 'gitlab.example.org/group/park', 'pipeline_id': 42,
        'Exp': '<script>alert(1)</script>',
    }))
    _login_admin(client)
    html = client.get('/admin/execution-profiles', query_string={
        'history_profile_id': '"><script>alert(1)</script>'}).data.decode()
    assert '<script>alert(1)</script>' not in html
    detail = client.get(f'/admin/execution-profiles/history/manual/{request_id}/results').data.decode()
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in detail
    assert '<script>alert(1)</script>' not in detail


@pytest.mark.parametrize('status,dry_run', [('submit_failed', False), ('blocked', False),
                                          ('submitted', True)])
def test_non_submissions_cannot_acquire_results_from_same_trigger(history_client, status, dry_run):
    _app, client, store, received = history_client
    runner_id = store.create_trigger_run(
        trigger_id='park-qws', trigger_type='manual_button', status=status, dry_run=dry_run,
        payload={'gitlab_project': 'gitlab.example.org/group/park',
                 'submit': {'response': {'id': 42}}})
    result(received / 'other-attempt.json')
    rows = list_execution_history(store)
    assert execution_result_links(str(received), rows) == {}
    _login_admin(client)
    response = client.get(f'/admin/execution-profiles/history/runner/{runner_id}/results')
    html = response.data.decode()
    assert response.status_code == 200 and 'other-attempt.json' not in html
    assert ('Preview only' if dry_run else 'Not submitted') in html


def test_unavailable_result_directory_is_not_reported_as_zero_results(history_client, monkeypatch):
    _app, client, store, _received = history_client
    request(store)
    def unavailable(_path):
        raise PermissionError('not readable')
    monkeypatch.setattr('utils.trigger_display._os_listdir', unavailable)
    _login_admin(client)
    html = client.get('/admin/execution-profiles').data.decode()
    assert 'Result lookup unavailable' in html
    assert 'No matching Result' not in html


@pytest.mark.parametrize('query', [
    'history_page=0', 'history_page=-1', 'history_page=abc', 'history_page=1000000',
    'history_since=2026-02-30', 'history_since=20261020',
    'history_since=2026-10-22&history_until=2026-10-21', 'history_profile_id=' + 'x' * 129,
])
def test_history_rejects_invalid_search(history_client, query):
    _app, client, _store, _received = history_client
    _login_admin(client)
    assert client.get('/admin/execution-profiles?' + query).status_code == 400


def test_all_results_route_requires_admin_and_exact_record_source(history_client):
    from test_execution_profiles import _login_user

    _app, client, store, received = history_client
    request_id = request(store)
    preview = request(store, dry_run=True)
    result(received / 'saved.json')
    path = f'/admin/execution-profiles/history/manual/{request_id}/results'
    assert client.get(path).status_code in (302, 403)
    _login_user(client)
    assert client.get(path).status_code == 403
    _login_admin(client)
    assert client.get(path).status_code == 200
    for source, record_id in [('runner', request_id), ('manual', preview), ('bad', request_id),
                              ('manual', 0), ('manual', 2**63)]:
        assert client.get(f'/admin/execution-profiles/history/{source}/{record_id}/results').status_code == 404


def test_history_read_does_not_change_schema_or_stored_rows(history_client):
    _app, client, store, _received = history_client
    request(store)
    def snapshot():
        with store.connect() as conn:
            return tuple(conn.iterdump())
    before = snapshot()
    _login_admin(client)
    assert client.get('/admin/execution-profiles').status_code == 200
    assert client.get('/admin/execution-profiles/history/manual/1/results').status_code == 200
    assert snapshot() == before


def test_submission_response_ignores_history_search_parameters(history_client):
    from routes.admin import _execution_history_context

    app, _client, store, _received = history_client
    request(store)
    with app.test_request_context('/admin/execution-profiles/submit?history_page=invalid'
                                 '&history_since=not-a-date', method='POST'):
        context = _execution_history_context(app.config['EXECUTION_PROFILE_DB_PATH'])
    assert context['history_page'] == 1
    assert not any(context['history_filters'].values())
    assert len(context['trigger_runs']) == 1
