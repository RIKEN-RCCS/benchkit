"""Offline first-match rule checks; no GitLab, runner, or scheduler calls."""
import re
from pathlib import Path

import pytest


CONFIG = Path(__file__).resolve().parents[2] / '.gitlab-ci.yml'
JOBS = ('generate_matrix', 'trigger_child_pipeline')
TRIGGER = '$CI_PIPELINE_SOURCE == "trigger"'
GUARDS = (
    '$estimate_result_uuid != ""',
    '$park_only == "true"',
    '$park_send == "true"',
    r'$CI_COMMIT_MESSAGE =~ /\[park-only\]/',
    r'$CI_COMMIT_MESSAGE =~ /\[park-send\]/',
)


def rules(job):
    # Parse only the existing scalar if/changes/when subset; reject unknown shapes.
    text = CONFIG.read_text().split(job + ':\n', 1)[1]
    block = re.split(r'^\S', text, maxsplit=1, flags=re.M)[0]
    section = block.split('  rules:\n', 1)[1]
    parsed = []
    for item in re.split(r'(?=^    - )', section, flags=re.M):
        if not item.strip():
            continue
        condition = re.search(r"^    - if: '(.+)'$", item, re.M)
        when = re.search(r'^\s+when: (always|never)\b', item, re.M)
        unconditional = re.fullmatch(r'    - when: (always|never)\s*', item)
        if unconditional:
            parsed.append({'when': unconditional[1]})
            continue
        assert when, item
        if condition:
            parsed.append({'if': condition[1], 'when': when[1]})
        else:
            assert item.startswith('    - changes:\n'), item
            compare = re.search(r'^        compare_to: "(.+)"$', item, re.M)
            paths = re.findall(r'^          - "(.+)"$', item, re.M)
            assert compare and paths, item
            parsed.append({'compare_to': compare[1], 'paths': paths, 'when': when[1]})
    return parsed


def condition_matches(condition, values):
    match = re.fullmatch(r'\$([A-Z_a-z0-9]+) (==|!=|=~) (".*"|/.*/)', condition)
    assert match, condition
    key, operator, literal = match.groups()
    value = values.get(key, '')
    if operator == '=~':
        return re.search(literal[1:-1], value) is not None
    expected = literal[1:-1]
    return (value == expected) if operator == '==' else (value != expected)


def path_matches(path, pattern):
    pattern = re.escape(pattern).replace(r'\*\*/', '(?:.*/)?')
    pattern = pattern.replace(r'\*\*', '.*').replace(r'\*', '[^/]*')
    return re.fullmatch(pattern, path) is not None


def select(job_rules, values, changed):
    for rule in job_rules:
        if 'if' in rule and not condition_matches(rule['if'], values):
            continue
        if 'paths' in rule:
            assert rule['compare_to'] == 'refs/heads/$CI_DEFAULT_BRANCH'
            if not any(path_matches(path, pattern) for path in changed for pattern in rule['paths']):
                continue
        return rule['when']
    return 'never'


@pytest.mark.parametrize('job', JOBS)
def test_parent_and_child_keep_mode_guards_before_explicit_trigger(job):
    selected = rules(job)
    assert tuple(rule.get('if') for rule in selected[:5]) == GUARDS
    assert all(rule['when'] == 'never' for rule in selected[:5])
    assert selected[5] == {'if': TRIGGER, 'when': 'always'}
    assert rules(JOBS[0]) == rules(JOBS[1])


@pytest.mark.parametrize('job', JOBS)
@pytest.mark.parametrize('default', ['main', 'develop'])
@pytest.mark.parametrize('ref', ['main', 'develop', 'feature/example'])
@pytest.mark.parametrize('changed', [[], ['result_server/routes/admin.py'], ['docs/ci.md'],
                                     ['scripts/result.sh']])
def test_explicit_trigger_runs_independent_of_default_branch_and_diff(job, default, ref, changed):
    values = {'CI_PIPELINE_SOURCE': 'trigger', 'CI_DEFAULT_BRANCH': default,
              'CI_COMMIT_REF_NAME': ref, 'BK_TRIGGER_TYPE': 'manual_button'}
    assert select(rules(job), values, changed) == 'always'


@pytest.mark.parametrize('job', JOBS)
@pytest.mark.parametrize('source', ['push', 'schedule', 'web', 'api', 'parent_pipeline'])
@pytest.mark.parametrize('changed', [[], ['result_server/routes/admin.py'], ['docs/ci.md'],
                                     ['programs/qws/run.sh'], ['scripts/result.sh'],
                                     ['result_server/app.py', 'programs/qws/run.sh']])
def test_non_trigger_sources_retain_existing_change_rules(job, source, changed):
    selected = rules(job)
    previous = [rule for rule in selected if rule.get('if') != TRIGGER]
    values = {'CI_PIPELINE_SOURCE': source}
    assert select(selected, values, changed) == select(previous, values, changed)
    if source == 'push':
        expected = 'never' if changed in (['result_server/routes/admin.py'], ['docs/ci.md']) else 'always'
        assert select(selected, values, changed) == expected


@pytest.mark.parametrize('job', JOBS)
@pytest.mark.parametrize('override', [
    {'estimate_result_uuid': 'example-uuid'}, {'park_only': 'true'}, {'park_send': 'true'},
    {'CI_COMMIT_MESSAGE': 'example [park-only]'}, {'CI_COMMIT_MESSAGE': 'example [park-send]'},
])
def test_trigger_does_not_override_estimation_or_park_mode_guards(job, override):
    values = dict(CI_PIPELINE_SOURCE='trigger', **override)
    assert select(rules(job), values, ['result_server/app.py']) == 'never'


@pytest.mark.parametrize('job', JOBS)
def test_reproduces_mirror_default_branch_difference_without_trigger_skip(job):
    selected = rules(job)
    previous = [rule for rule in selected if rule.get('if') != TRIGGER]
    swc = {'CI_PIPELINE_SOURCE': 'trigger', 'CI_DEFAULT_BRANCH': 'main',
           'CI_COMMIT_REF_NAME': 'develop'}
    changed = ['result_server/routes/admin.py', 'docs/guides/benchpark-ci-integration.md']
    assert select(previous, swc, changed) == 'never'
    assert select(selected, swc, changed) == 'always'
    gitlab_com = dict(swc, CI_DEFAULT_BRANCH='develop')
    assert select(previous, gitlab_com, []) == 'always'
    assert select(selected, gitlab_com, []) == 'always'


@pytest.mark.parametrize('path,expected_ref', [
    ('/console/admin/execution-profiles', 'main'),
    ('/dev/console/admin/execution-profiles', 'develop'),
    ('/dev2/console/admin/execution-profiles', 'develop'),
])
@pytest.mark.parametrize('repo', ['swc.example.org/group/kit', 'gitlab.example.org/group/kit'])
def test_portal_default_ref_passes_unchanged_to_each_trigger_target(tmp_path, path, expected_ref, repo):
    from test_execution_profiles import _admin_app, _cleanup
    from routes.admin import _default_trigger_ref
    from utils.gitlab_pipeline import build_pipeline_plan

    app, dirs = _admin_app(tmp_path / 'profiles.sqlite')
    try:
        with app.test_request_context(path):
            ref = _default_trigger_ref()
            plan = build_pipeline_plan(gitlab_repo=repo, target_ref=ref,
                                       code='qws', system='ExampleSystem')
        assert ref == expected_ref
        assert plan.errors == []
        assert plan.payload['ref'] == expected_ref
    finally:
        _cleanup(dirs)
