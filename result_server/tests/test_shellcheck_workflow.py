"""Execute the workflow's shell steps with local checkers and Git fixtures."""

import json
import os
from pathlib import Path
import subprocess
import shutil
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
    (tmp_path / "scripts/tests").mkdir()
    shutil.copy(REPO_ROOT / "scripts/tests/shellcheck_app_matrix.py", tmp_path / "scripts/tests/")
    tools = tmp_path / "tools"
    checker = tools / "shellcheck"
    checker.write_text("#!" + sys.executable + "\n" + textwrap.dedent('''
        import fcntl, json, os, sys, time
        args = sys.argv[1:]
        assert args[0] == '-x'
        args = args[1:]
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
        time.sleep(float(os.environ["CHECK_DELAY"]))
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
               CHECK_STATE=str(state), CHECK_DELAY="0", CHANGED_FILES=str(changed), GITHUB_BASE_REF="develop",
               SHARD_INDEX="0", SHARD_COUNT="6", GITHUB_OUTPUT=str(tmp_path / "outputs"))
    return tmp_path, state, changed, env


def execute(checks, warning=False):
    root, _, _, env = checks
    name = ("Run warning-level shellcheck on changed app scripts" if warning
            else "Run bash syntax checks and shellcheck at error level")
    if warning:
        selection = subprocess.run(["bash", "-c", workflow_script("Select changed app scripts")],
                                   cwd=root, env=env, capture_output=True, text=True, timeout=15)
        if selection.returncode:
            return selection
        output = Path(env["GITHUB_OUTPUT"]).read_text().splitlines()
        matrix = json.loads(next(line.removeprefix("matrix=") for line in output if line.startswith("matrix=")))
        results = []
        for app in matrix["include"]:
            result = subprocess.run(["bash", "-c", workflow_script(name)], cwd=root,
                                    env=dict(env, APP_FILES_JSON=json.dumps(app["files"])),
                                    capture_output=True, text=True, timeout=15)
            results.append(result)
            if result.returncode:
                return result
        return subprocess.CompletedProcess([], 0, "".join(r.stdout for r in results),
                                           "".join(r.stderr for r in results))
    results = []
    for shard in ([0] if warning else range(6)):
        result = subprocess.run(["bash", "-c", workflow_script(name)], cwd=root,
                                env=dict(env, SHARD_INDEX=str(shard)),
                                capture_output=True, text=True, timeout=15)
        results.append(result)
        if result.returncode:
            return result
    return subprocess.CompletedProcess([], 0, "".join(r.stdout for r in results),
                                       "".join(r.stderr for r in results))


@pytest.mark.parametrize("warning", [False, True])
def test_each_file_is_checked_once_with_at_most_two_processes(checks, warning):
    root, state, changed, env = checks
    env["CHECK_DELAY"] = "0.05"
    names = ["programs/first/plain.sh", "programs/first/space name.sh", "programs/second/line\nbreak.sh"]
    if not warning:
        names += [f"scripts/helper-{index}.sh" for index in range(8)]
        names += ["benchpark-bridge/scripts/bridge.sh"]
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("#!/bin/bash\ntrue\n")
    (root / "scripts/ignored.txt").write_text("not a shell script")
    changed.write_bytes(b"\0".join(name.encode() for name in names) + b"\0")
    result = execute(checks, warning)
    assert result.returncode == 0, result.stderr
    data = json.loads(state.read_text())
    assert sorted(call[-1] for call in data["calls"]) == sorted(names)
    assert all(call[1] == ("warning" if warning else "error") for call in data["calls"])
    assert data["maximum"] == 2
    assert data["active"] == 0


@pytest.mark.parametrize("warning", [False, True])
@pytest.mark.parametrize("status", [1, 2, 127, 255])
def test_any_checker_failure_fails_the_step(checks, warning, status):
    root, _, changed, env = checks
    name = "programs/first/failure.sh"
    (root / name).parent.mkdir(parents=True, exist_ok=True)
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


@pytest.mark.parametrize("count", [1, 2, 5, 6, 7, 123, 136])
def test_shards_cover_every_file_without_overlap(checks, count):
    root, state, _, env = checks
    names = [f"scripts/input-{i:03d}.sh" for i in range(count)]
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("true\n")
    seen = []
    for shard in range(6):
        state.write_text(json.dumps({"active": 0, "maximum": 0, "calls": []}))
        result = subprocess.run(
            ["bash", "-c", workflow_script("Run bash syntax checks and shellcheck at error level")],
            cwd=root, env=dict(env, SHARD_INDEX=str(shard)), capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr
        actual = sorted(call[-1] for call in json.loads(state.read_text())["calls"])
        assert actual == names[shard::6]
        seen += actual
    assert sorted(seen) == names


@pytest.mark.parametrize("error", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("warning", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch", "push"])
def test_required_check_accepts_only_complete_success(error, warning, event):
    result = subprocess.run(
        ["bash", "-c", workflow_script("Check ShellCheck job results")],
        env=dict(os.environ, ERROR_RESULT=error, WARNING_RESULT=warning, EVENT_NAME=event,
                 SELECTION_RESULT="success" if event == "pull_request" else "skipped", HAS_CHANGES="true"),
        capture_output=True)
    expected = error == "success" and warning == ("success" if event == "pull_request" else "skipped")
    assert (result.returncode == 0) == expected


@pytest.mark.parametrize("index,count", [("-1", "6"), ("6", "6"), ("0", "0"), ("bad", "6")])
def test_invalid_shard_configuration_fails(checks, index, count):
    root, state, _, env = checks
    result = subprocess.run(
        ["bash", "-c", workflow_script("Run bash syntax checks and shellcheck at error level")],
        cwd=root, env=dict(env, SHARD_INDEX=index, SHARD_COUNT=count), capture_output=True)
    assert result.returncode != 0
    assert json.loads(state.read_text())["calls"] == []


def test_workflow_runs_independent_shards_and_preserves_required_check():
    workflow = (REPO_ROOT / ".github/workflows/shellcheck.yml").read_text()
    error = workflow.split("  shellcheck-error:\n", 1)[1].split("  shellcheck-warning-apps:\n", 1)[0]
    selection = workflow.split("  shellcheck-warning-apps:\n", 1)[1].split("  shellcheck-warning:\n", 1)[0]
    warning = workflow.split("  shellcheck-warning:\n", 1)[1].split("  shellcheck:\n", 1)[0]
    gate = workflow.split("  shellcheck:\n", 1)[1]
    assert "shard: [0, 1, 2, 3, 4, 5]" in error
    assert 'SHARD_COUNT: "6"' in error
    assert "SHARD_INDEX: ${{ matrix.shard }}" in error
    assert "fail-fast: false" in error
    assert "needs:" not in error and "needs:" not in selection
    assert "if: github.event_name == 'pull_request'" in selection
    assert "fromJSON(needs.shellcheck-warning-apps.outputs.matrix)" in warning
    assert "fetch-depth: 0" in error and "fetch-depth: 0" in warning
    assert "name: shellcheck -S error" in gate
    assert "needs: [shellcheck-error, shellcheck-warning-apps, shellcheck-warning]" in gate
    assert "if: always()" in gate


@pytest.mark.parametrize("selection", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("has_changes", ["true", "false", ""])
@pytest.mark.parametrize("warning", ["success", "failure", "cancelled", "skipped"])
def test_pr_gate_checks_app_selection_and_empty_matrix(selection, has_changes, warning):
    result = subprocess.run(
        ["bash", "-c", workflow_script("Check ShellCheck job results")],
        env=dict(os.environ, ERROR_RESULT="success", SELECTION_RESULT=selection,
                 HAS_CHANGES=has_changes, WARNING_RESULT=warning, EVENT_NAME="pull_request"),
        capture_output=True)
    expected = selection == "success" and (
        (has_changes == "true" and warning == "success") or
        (has_changes == "false" and warning == "skipped"))
    assert (result.returncode == 0) == expected


def test_changed_apps_get_separate_matrices_without_missing_files(checks):
    root, _, changed, env = checks
    paths = ["programs/app space/run.sh", "programs/app space/build.sh",
             "programs/app\nline/subdir/profile.sh"]
    changed.write_bytes(b"\0".join(p.encode() for p in paths) + b"\0")
    result = subprocess.run(["bash", "-c", workflow_script("Select changed app scripts")],
                            cwd=root, env=env, capture_output=True)
    assert result.returncode == 0
    matrix = json.loads(Path(env["GITHUB_OUTPUT"]).read_text().splitlines()[0][len("matrix="):])
    assert len(matrix["include"]) == 2
    assert sorted(f for app in matrix["include"] for f in app["files"]) == sorted(paths)
    assert all(all(Path(f).parts[1] == app["app"] for f in app["files"]) for app in matrix["include"])


@pytest.mark.parametrize("shard", range(6))
def test_failure_in_each_error_shard_is_reported(checks, shard):
    root, _, _, env = checks
    names = [f"scripts/input-{index}.sh" for index in range(6)]
    for name in names:
        (root / name).write_text("true\n")
    result = subprocess.run(
        ["bash", "-c", workflow_script("Run bash syntax checks and shellcheck at error level")],
        cwd=root, env=dict(env, SHARD_INDEX=str(shard), FAIL_FILE=names[shard], FAIL_CODE="1"),
        capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "shellcheck error-level: 0" not in result.stdout


def test_error_and_warning_install_pinned_checker_with_download_cache():
    workflow = (REPO_ROOT / ".github/workflows/shellcheck.yml").read_text()
    for job, following in [("shellcheck-error", "shellcheck-warning-apps"),
                           ("shellcheck-warning", "shellcheck")]:
        section = workflow.split(f"  {job}:\n", 1)[1].split(f"  {following}:\n", 1)[0]
        assert "cache: pip" in section
        assert "cache-dependency-path: requirements-shellcheck.txt" in section
        assert "python -m pip install --quiet -r requirements-shellcheck.txt" in section
        assert "shellcheck --version" in section
    triggers = workflow.split("jobs:", 1)[0]
    assert triggers.count('      - "requirements-shellcheck.txt"') == 2
    requirements = (REPO_ROOT / "requirements-shellcheck.txt").read_text().splitlines()
    packages = [line for line in requirements if line and not line.startswith("#")]
    assert len(packages) == 1 and packages[0].startswith("shellcheck-py==")
