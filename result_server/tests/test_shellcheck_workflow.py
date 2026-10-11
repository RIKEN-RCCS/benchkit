"""Execute the workflow's shell steps with local checkers and Git fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def workflow_script(name):
    lines = (REPO_ROOT / ".github/workflows/shellcheck.yml").read_text().splitlines()
    start = lines.index("      - name: " + name)
    run = next(i for i in range(start, len(lines)) if lines[i] == "        run: |")
    end = run + 1
    while end < len(lines) and (not lines[end] or lines[end].startswith("          ")):
        end += 1
    return textwrap.dedent("\n".join(lines[run + 1:end]))


@pytest.fixture
def checks(tmp_path):
    for directory in ("scripts", "programs", "benchpark-bridge/scripts", "tools"):
        (tmp_path / directory).mkdir(parents=True)
    tools = tmp_path / "tools"
    checker = tools / "shellcheck"
    checker.write_text("#!" + sys.executable + "\n" + textwrap.dedent('''
        import fcntl, json, os, sys, time
        args = sys.argv[1:]
        assert len(args) == 5 and args[0] == '-S' and args[2:4] == ['-f', 'gcc']
        def update(delta):
            with open(os.environ['CHECK_STATE'], 'r+') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                data = json.load(stream)
                data['active'] += delta
                data['maximum'] = max(data['maximum'], data['active'])
                if delta > 0:
                    data['calls'].append(args)
                stream.seek(0); json.dump(data, stream); stream.truncate()
        update(1)
        time.sleep(0.05)
        update(-1)
        raise SystemExit(int(os.environ.get('FAIL_CODE', '0')) if args[4] == os.environ.get('FAIL_FILE') else 0)
    '''))
    checker.chmod(0o700)
    git = tools / "git"
    git.write_text("#!" + sys.executable + "\n" + textwrap.dedent('''
        import os, sys
        if sys.argv[1] == 'fetch':
            raise SystemExit(0)
        assert sys.argv[1] == 'diff' and '-z' in sys.argv
        if os.environ.get('FAIL_DIFF'):
            raise SystemExit(1)
        sys.stdout.buffer.write(open(os.environ['CHANGED_FILES'], 'rb').read())
    '''))
    git.chmod(0o700)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"active": 0, "maximum": 0, "calls": []}))
    changed = tmp_path / "changed"
    changed.write_bytes(b"")
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
               CHECK_STATE=str(state), CHANGED_FILES=str(changed), GITHUB_BASE_REF="develop")
    return tmp_path, state, changed, env


def execute(checks, warning=False):
    root, _, _, env = checks
    name = ("Run warning-level shellcheck on changed app scripts" if warning
            else "Run bash syntax checks and shellcheck at error level")
    return subprocess.run(["bash", "-c", workflow_script(name)], cwd=root,
                          env=env, capture_output=True, text=True, timeout=15)


@pytest.mark.parametrize("warning", [False, True])
def test_each_file_is_checked_once_with_at_most_two_processes(checks, warning):
    root, state, changed, _ = checks
    names = ["programs/plain.sh", "programs/space name.sh", "programs/line\nbreak.sh"]
    if not warning:
        names += ["scripts/helper.sh", "benchpark-bridge/scripts/bridge.sh"]
    for name in names:
        (root / name).write_text("#!/bin/bash\ntrue\n")
    (root / "scripts/ignored.txt").write_text("not a shell script")
    changed.write_bytes(b"\0".join(name.encode() for name in names) + b"\0")
    result = execute(checks, warning)
    assert result.returncode == 0, result.stderr
    data = json.loads(state.read_text())
    assert sorted(call[-1] for call in data["calls"]) == sorted(names)
    assert all(call[1] == ("warning" if warning else "error") for call in data["calls"])
    assert 1 <= data["maximum"] <= 2
    assert data["active"] == 0


@pytest.mark.parametrize("warning", [False, True])
@pytest.mark.parametrize("status", [1, 2, 127, 255])
def test_any_checker_failure_fails_the_step(checks, warning, status):
    root, _, changed, env = checks
    name = "programs/failure.sh"
    (root / name).write_text("true\n")
    changed.write_bytes(name.encode() + b"\0")
    env.update(FAIL_FILE=name, FAIL_CODE=str(status))
    result = execute(checks, warning)
    assert result.returncode != 0
    assert "shellcheck error-level: 0" not in result.stdout
    assert "changed app shellcheck warning-level: 0" not in result.stdout


def test_syntax_failure_stops_before_shellcheck(checks):
    root, state, _, _ = checks
    (root / "scripts/invalid.sh").write_text("if then\n")
    assert execute(checks).returncode != 0
    assert json.loads(state.read_text())["calls"] == []


@pytest.mark.parametrize("warning", [False, True])
def test_empty_selection_does_not_run_checker(checks, warning):
    assert execute(checks, warning).returncode == 0
    assert json.loads(checks[1].read_text())["calls"] == []


@pytest.mark.parametrize("warning", [False, True])
def test_selection_failure_is_not_reported_as_empty_success(checks, warning):
    root, state, _, env = checks
    if warning:
        env['FAIL_DIFF'] = '1'
    else:
        (root / "benchpark-bridge/scripts").rmdir()
    assert execute(checks, warning).returncode != 0
    assert json.loads(state.read_text())["calls"] == []
