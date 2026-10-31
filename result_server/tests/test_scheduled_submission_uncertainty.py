"""Scheduled submit contracts: temporary SQLite, fake transport, no external jobs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import sqlite3
import threading
import urllib.error

import pytest
from test_execution_profiles import _profile
from utils.execution_profiles import ExecutionProfileStore, normalize_trigger_definition
from utils.gitlab_pipeline import GitLabPipelineSubmitResult, build_pipeline_plan, submit_pipeline_plan
import trigger_runner as runner

NOW = datetime(2026, 10, 31, 1, 0, 15, tzinfo=UTC)


@pytest.fixture(params=['benchkit', 'benchpark'])
def scheduled(tmp_path, monkeypatch, request):
    backend = request.param
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TARGETS',
                       'kit=gitlab.example.org/group/kit,park=gitlab.example.org/group/park')
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TARGET_BACKENDS', '{"park":"benchpark"}')
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TRIGGER_TOKEN_KIT', 'fake-kit-token')
    monkeypatch.setenv('RESULT_SERVER_GITLAB_TRIGGER_TOKEN_PARK', 'fake-park-token')
    metadata = {} if backend == 'benchkit' else {'pipeline': {
        'backend': 'benchpark', 'site': 'example-site',
        'experiment_config': 'config/experiments/demo.yaml', 'gitlab_target': 'park'}}
    store = ExecutionProfileStore(str(tmp_path / 'portal.sqlite'))
    store.upsert_profile(_profile(id='demo', allocation_project_id='', scheduler_extra_args='',
                                  metadata_json=metadata), actor='admin@test.com')
    trigger, errors = normalize_trigger_definition({'id': 'daily', 'trigger_type': 'scheduled',
        'profile_id': 'demo', 'enabled': True, 'gitlab_target': 'kit' if backend == 'benchkit' else 'park',
        'target_ref': 'develop', 'cron_expr': '0 10 * * *', 'timezone': 'Asia/Tokyo'})
    assert not errors
    store.upsert_trigger_definition(trigger, actor='admin@test.com')
    return store, dict(db_path=store.db_path, dry_run=False, submit=True,
                      result_server_url='https://results.example.org/dev2', now=NOW, use_lock=False)


def run_pair(scheduled, submit):
    store, kwargs = scheduled
    first = runner.run_triggers(**kwargs, submit_pipeline=submit)[0]
    second = runner.run_triggers(**dict(kwargs, now=NOW + timedelta(seconds=20)), submit_pipeline=submit)[0]
    return store, first, second


@pytest.mark.parametrize('code,payload', [(0, {}), (503, {}), (408, {}), (201, {}),
    (201, {'id': True}), (201, {'id': 'invalid'}), (201, {'id': 0}), (302, {})])
def test_uncertain_outcomes_are_not_resent(scheduled, code, payload):
    calls = []
    def submit(plan, *, token):
        calls.append(plan)
        return GitLabPipelineSubmitResult(code, payload, [] if code == 201 else ['fake transport error'])
    store, first, second = run_pair(scheduled, submit)
    assert first.status == 'submission_unknown'
    assert second.status == 'submission_held' and not second.should_fire
    assert len(calls) == 1
    attempts = store.list_trigger_runs('daily', statuses=['submission_unknown'])
    assert len(attempts) == 1
    assert attempts[0]['payload_json']['submit']['acceptance'] == 'unknown'
    assert second.payload['submission_hold']['confirmation_required'] is True


def test_receipt_followed_by_response_loss_holds_slot(scheduled):
    accepted = []
    def submit(plan, *, token):
        accepted.append(42)  # Simulated server-side pipeline creation before response loss.
        raise TimeoutError('must-not-be-recorded-secret')
    store, first, second = run_pair(scheduled, submit)
    assert first.status == 'submission_unknown' and second.status == 'submission_held'
    assert accepted == [42]
    assert 'must-not-be-recorded-secret' not in json.dumps(store.list_trigger_runs('daily'))


@pytest.mark.parametrize('code', [400, 401, 403, 404, 405, 422, 429])
def test_clear_rejection_retains_existing_next_tick_behavior(scheduled, code):
    calls = []
    def submit(plan, *, token):
        calls.append(plan)
        return (GitLabPipelineSubmitResult(code, {}, ['rejected']) if len(calls) == 1
                else GitLabPipelineSubmitResult(201, {'id': 42}, []))
    store, first, second = run_pair(scheduled, submit)
    assert first.status == 'submit_failed' and second.status == 'submitted'
    assert first.payload['submit']['acceptance'] == 'rejected'
    assert len(calls) == 2
    assert sum(r['status'] == 'submitted' for r in store.list_trigger_runs('daily')) == 1


def test_success_is_recorded_once_and_deduplicated(scheduled):
    calls = []
    def submit(plan, *, token):
        calls.append(plan)
        return GitLabPipelineSubmitResult(201, {'id': 42}, [])
    store, first, second = run_pair(scheduled, submit)
    assert first.status == 'submitted' and second.status == 'already_submitted'
    assert first.payload['submit']['acceptance'] == 'accepted'
    assert len(calls) == 1
    assert len(store.list_trigger_runs('daily', statuses=['submitted'])) == 1


def test_process_interruption_leaves_durable_claim(scheduled):
    store, kwargs = scheduled
    def interrupted(plan, *, token):
        raise SystemExit('simulated process interruption')
    with pytest.raises(SystemExit):
        runner.run_triggers(**kwargs, submit_pipeline=interrupted)
    assert len(store.list_trigger_runs('daily', statuses=['submitting'])) == 1
    second = runner.run_triggers(**kwargs, submit_pipeline=lambda *a, **k: pytest.fail('resubmitted'))[0]
    assert second.status == 'submission_held'


def test_failure_saving_response_cannot_release_claim(scheduled, monkeypatch):
    store, kwargs = scheduled
    original = ExecutionProfileStore.finish_scheduled_submission
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('simulated disk failure')
    monkeypatch.setattr(ExecutionProfileStore, 'finish_scheduled_submission', fail)
    with pytest.raises(sqlite3.OperationalError):
        runner.run_triggers(**kwargs, submit_pipeline=lambda *a, **k: GitLabPipelineSubmitResult(201, {'id': 42}, []))
    monkeypatch.setattr(ExecutionProfileStore, 'finish_scheduled_submission', original)
    assert runner.run_triggers(**kwargs, submit_pipeline=lambda *a, **k: pytest.fail('resubmitted'))[0].status == 'submission_held'
    assert store.list_trigger_runs('daily', statuses=['submitting'])


def test_atomic_claim_survives_concurrent_evaluations_without_runner_lock(scheduled, monkeypatch):
    store, kwargs = scheduled
    barrier = threading.Barrier(2)
    original = runner.evaluate_trigger
    def evaluate(*a, **k):
        result = original(*a, **k)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(runner, 'evaluate_trigger', evaluate)
    calls = []
    def submit(*a, **k):
        calls.append(42)
        return GitLabPipelineSubmitResult(201, {'id': 42}, [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: runner.run_triggers(**kwargs, submit_pipeline=submit)[0], range(2)))
    assert calls == [42]
    assert sorted(r.status for r in results) == ['submission_held', 'submitted']
    assert len(store.list_trigger_runs('daily', statuses=['submitted'])) == 1


def test_dry_run_does_not_claim_or_send_even_with_submit_flag(scheduled):
    store, kwargs = scheduled
    result = runner.run_triggers(**dict(kwargs, dry_run=True),
        submit_pipeline=lambda *a, **k: pytest.fail('dry-run sent'))[0]
    assert result.status == 'would_submit'
    assert not store.list_trigger_runs('daily', statuses=['submitting', 'submitted', 'submission_unknown'])


def test_future_schedule_slot_is_distinct_from_held_slot(scheduled):
    store, kwargs = scheduled
    first = runner.run_triggers(**kwargs, submit_pipeline=lambda *a, **k: GitLabPipelineSubmitResult(0, {}, ['timeout']))[0]
    next_day = runner.run_triggers(**dict(kwargs, now=NOW + timedelta(days=1)),
        submit_pipeline=lambda *a, **k: GitLabPipelineSubmitResult(201, {'id': 43}, []))[0]
    assert first.status == 'submission_unknown' and next_day.status == 'submitted'
    assert first.reason != next_day.reason


def test_local_validation_is_a_known_non_attempt():
    calls = []
    plan = build_pipeline_plan(gitlab_repo='gitlab.example.org/group/kit', target_ref='develop')
    result = submit_pipeline_plan(plan, token='', urlopen=lambda *a, **k: calls.append(1))
    assert not result.request_attempted and not calls
    assert runner.scheduled_submission_status(result) == 'submit_failed'


@pytest.mark.parametrize('status_code,held', [(0, True), (503, True), (408, True),
                                              (201, True), (400, False), (429, False)])
def test_legacy_submit_failed_is_reclassified_conservatively(scheduled, status_code, held):
    store, kwargs = scheduled
    reason = runner.evaluate_trigger(store, store.list_trigger_definitions()[0], now=NOW,
                                     result_server_url=kwargs['result_server_url']).reason
    store.create_trigger_run(trigger_id='daily', trigger_type='scheduled', status='submit_failed',
        dry_run=False, reason=reason,
        payload={'submit': {'status_code': status_code, 'response': {}}}, errors=['old failure'])
    calls=[]
    def submit(*args, **kw):
        calls.append(1)
        return GitLabPipelineSubmitResult(201, {'id':42}, [])
    result=runner.run_triggers(**kwargs, submit_pipeline=submit)[0]
    assert result.status == ('submission_held' if held else 'submitted')
    assert len(calls) == (0 if held else 1)


def test_legacy_untimed_unknown_failure_and_dry_run_diagnostic(scheduled):
    store,kwargs=scheduled
    run_id=store.create_trigger_run(trigger_id='daily',trigger_type='scheduled',status='submit_failed',
        dry_run=False,reason='cron:0 10 * * *',payload={'submit':{'status_code':0,'response':{}}})
    with store.connect() as c:
        c.execute('UPDATE trigger_runs SET created_at=? WHERE id=?',(NOW.isoformat(),run_id))
    assert runner.run_triggers(**kwargs,submit_pipeline=lambda *a,**k:pytest.fail('legacy resend'))[0].status=='submission_held'


def test_dry_run_history_never_consumes_scheduled_slot(scheduled):
    store,kwargs=scheduled
    reason=runner.evaluate_trigger(store,store.list_trigger_definitions()[0],now=NOW,
                                  result_server_url=kwargs['result_server_url']).reason
    for status in ['submitting','submission_unknown','submitted','submit_failed']:
        store.create_trigger_run(trigger_id='daily',trigger_type='scheduled',status=status,
            dry_run=True,reason=reason,payload={'submit':{'status_code':0,'response':{}}})
    assert runner.run_triggers(**kwargs,submit_pipeline=lambda *a,**k:GitLabPipelineSubmitResult(201,{'id':42},[]))[0].status=='submitted'


def test_history_does_not_claim_pipeline_or_result_for_unknown_attempt(tmp_path):
    from utils.execution_history import summarize_execution_history, execution_result_links
    run={'id':1,'trigger_id':'daily','trigger_type':'scheduled','status':'submission_unknown',
         'dry_run':False,'reason':'cron:0 10 * * *','payload_json':{
             'gitlab_project':'gitlab.example.org/group/kit','submit':{'status_code':0,'response':{}}},
         'errors':[],'created_at':'2026-10-31T01:00:00Z'}
    summary=summarize_execution_history(run)
    assert summary['decision_label']=='Acceptance unknown; confirmation required'
    assert summary['pipeline_url']==''
    assert execution_result_links(str(tmp_path), [run])=={}


@pytest.mark.parametrize('transport', ['timeout', 'urlerror', 'empty_success', 'invalid_json', 'http503'])
def test_real_submit_adapter_with_fake_transport(scheduled, transport):
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def getcode(self):return 201
        def read(self):return b'' if transport=='empty_success' else b'not-json'
    def urlopen(request, timeout):
        calls.append(request.full_url)
        if transport=='timeout':raise TimeoutError()
        if transport=='urlerror':raise urllib.error.URLError('fake response loss')
        if transport=='http503':raise urllib.error.HTTPError(request.full_url,503,'unavailable',{},None)
        return Response()
    def submit(plan,*,token):return submit_pipeline_plan(plan,token=token,urlopen=urlopen)
    store,first,second=run_pair(scheduled,submit)
    assert len(calls)==1 and first.status=='submission_unknown' and second.status=='submission_held'


def test_cannot_claim_means_no_network_attempt(scheduled, monkeypatch):
    _,kwargs=scheduled
    def fail(*args,**kwargs):raise sqlite3.OperationalError('temporary DB unavailable')
    monkeypatch.setattr(ExecutionProfileStore,'claim_scheduled_submission',fail)
    with pytest.raises(sqlite3.OperationalError):
        runner.run_triggers(**kwargs,submit_pipeline=lambda *a,**k:pytest.fail('sent without claim'))


def test_legacy_unparseable_failure_is_held(scheduled):
    store,kwargs=scheduled
    reason=runner.evaluate_trigger(store,store.list_trigger_definitions()[0],now=NOW,
                                  result_server_url=kwargs['result_server_url']).reason
    store.create_trigger_run(trigger_id='daily',trigger_type='scheduled',status='submit_failed',
                             dry_run=False,reason=reason,payload={})
    assert runner.run_triggers(**kwargs,submit_pipeline=lambda *a,**k:pytest.fail('ambiguous resend'))[0].status=='submission_held'


def test_hold_history_is_throttled_without_releasing_the_attempt(scheduled):
    store, kwargs = scheduled
    runner.run_triggers(**kwargs, submit_pipeline=lambda *a, **k: GitLabPipelineSubmitResult(0, {}, ['timeout']))
    for seconds in (20, 40, 60):
        result = runner.run_triggers(**dict(kwargs, now=NOW + timedelta(seconds=seconds)),
            submit_pipeline=lambda *a, **k: pytest.fail('held slot resent'))[0]
        assert result.status == 'submission_held'
    assert len(store.list_trigger_runs('daily', statuses=['submission_held'])) == 1
    assert len(store.list_trigger_runs('daily', statuses=['submission_unknown'])) == 1


def test_independent_triggers_are_not_deduplicated_against_each_other(scheduled):
    store, kwargs = scheduled
    definition = dict(store.list_trigger_definitions()[0], id='independent-daily')
    store.upsert_trigger_definition(definition, actor='admin@test.com')
    calls = []
    def submit(*args, **kw):
        calls.append(1)
        return GitLabPipelineSubmitResult(201, {'id': len(calls)}, [])
    results = runner.run_triggers(**kwargs, submit_pipeline=submit)
    assert len(calls) == 2
    assert all(result.status == 'submitted' for result in results)
