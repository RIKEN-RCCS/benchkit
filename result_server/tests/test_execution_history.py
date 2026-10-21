"""Persisted manual history renders without resubmission or cross-project links."""
import json
from pathlib import Path

import pytest

from test_execution_profiles import _admin_app, _cleanup, _login_admin
from utils.execution_profiles import ExecutionProfileStore
from utils.execution_history import list_execution_history, summarize_execution_history
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
