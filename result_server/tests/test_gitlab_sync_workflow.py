"""Exercise independent mirror push steps without contacting either mirror."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest


WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/sync-to-gitlab.yml'


def job(name):
    text = WORKFLOW.read_text().split('  ' + name + ':\n', 1)[1]
    return text.split('\n  sync-', 1)[0]


def push_script(name):
    lines = job(name).splitlines()
    start = next(i for i, line in enumerate(lines) if line == '        run: |'
                 and any('Push protected branches' in x for x in lines[max(0, i - 8):i]))
    return textwrap.dedent('\n'.join(lines[start + 1:]))


@pytest.fixture
def mirrors(tmp_path):
    tools = tmp_path / 'tools'
    tools.mkdir()
    fake_git = tools / 'git'
    fake_git.write_text('#!' + sys.executable + '\n' + textwrap.dedent('''
        import json, os, pathlib, sys, time
        args = sys.argv[1:]
        target = os.environ['TEST_MIRROR']
        if args[:2] == ['remote', 'add']:
            assert args[2] == ('gitlab' if target == 'swc' else 'gitlab-com')
            assert args[3].startswith('https://oauth2:')
            raise SystemExit(0)
        assert args[0] == 'push'
        with open(os.environ['TEST_CALLS'], 'a') as out:
            out.write(json.dumps(args) + '\\n')
        if target == 'swc' and os.environ.get('TEST_BLOCK'):
            pathlib.Path(os.environ['TEST_STARTED']).touch()
            while not pathlib.Path(os.environ['TEST_RELEASE']).exists():
                time.sleep(0.01)
        failure = os.environ.get('TEST_FAIL', '')
        raise SystemExit(1 if failure == 'all' or (failure == 'tags' and '--tags' in args) else 0)
    '''))
    fake_git.chmod(0o700)
    return tmp_path, dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                         GITLAB_TOKEN='test-placeholder', GITLAB_REPO_HOST_PATH='example.invalid/repo.git',
                         GITLAB_COM_TOKEN='test-placeholder',
                         GITLAB_COM_REPO_HOST_PATH='gitlab.com/example/repo.git')


def command(mirrors, target, **overrides):
    root, env = mirrors
    return ['bash', '-c', push_script('sync-swc' if target == 'swc' else 'sync-gitlab-com')], dict(
        env, TEST_MIRROR=target, TEST_CALLS=str(root / (target + '.jsonl')), **overrides)


def run(mirrors, target, **overrides):
    args, env = command(mirrors, target, **overrides)
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)


def calls(mirrors, target):
    path = mirrors[0] / (target + '.jsonl')
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def test_jobs_are_independent_and_fetch_the_same_refs():
    for name in ('sync-swc', 'sync-gitlab-com'):
        text = job(name)
        assert 'needs:' not in text
        assert 'continue-on-error:' not in text
        assert 'fetch-depth: 0' in text
        assert 'git fetch origin +refs/heads/develop:refs/remotes/origin/develop +refs/heads/main:refs/remotes/origin/main' in text
    assert 'steps.refs.outcome' not in job('sync-gitlab-com')
    assert 'prepare-gitlab-repo' not in job('sync-gitlab-com')


@pytest.mark.parametrize('target', ['swc', 'com'])
def test_push_targets_ci_skip_tags_and_force_policy(mirrors, target):
    assert run(mirrors, target).returncode == 0
    remote = 'gitlab' if target == 'swc' else 'gitlab-com'
    branch = ['push', '-o', 'ci.skip', remote,
              'refs/remotes/origin/develop:refs/heads/develop',
              'refs/remotes/origin/main:refs/heads/main']
    tags = ['push', '-o', 'ci.skip', remote, '--tags']
    if target == 'swc':
        branch += ['--force']
        tags += ['--force']
    assert calls(mirrors, target) == [branch, tags]


@pytest.mark.parametrize('target', ['swc', 'com'])
@pytest.mark.parametrize('failure', ['all', 'tags'])
def test_push_failure_remains_a_failure(mirrors, target, failure):
    assert run(mirrors, target, TEST_FAIL=failure).returncode != 0
    assert len(calls(mirrors, target)) == (1 if failure == 'all' else 2)


@pytest.mark.parametrize('variable', ['GITLAB_TOKEN', 'GITLAB_REPO_HOST_PATH'])
def test_primary_configuration_is_required(mirrors, variable):
    assert run(mirrors, 'swc', **{variable: ''}).returncode != 0
    assert calls(mirrors, 'swc') == []


def test_optional_mirror_without_token_is_skipped(mirrors):
    assert run(mirrors, 'com', GITLAB_COM_TOKEN='').returncode == 0
    assert calls(mirrors, 'com') == []


def test_gitlab_com_can_finish_while_primary_is_blocked(mirrors):
    root, _ = mirrors
    started, release = root / 'started', root / 'release'
    args, env = command(mirrors, 'swc', TEST_BLOCK='1', TEST_STARTED=str(started),
                        TEST_RELEASE=str(release), TEST_FAIL='all')
    process = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists()
        assert run(mirrors, 'com').returncode == 0
        assert len(calls(mirrors, 'com')) == 2
        assert process.poll() is None
        release.touch()
        assert process.wait(timeout=5) != 0
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
