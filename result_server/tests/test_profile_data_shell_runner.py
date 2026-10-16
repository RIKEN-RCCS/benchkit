import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_DIR = Path(__file__).resolve().parents[2]
RUNNER = REPO_DIR / "scripts/tests/run_profile_data_shell_tests.sh"


def _runner_lines(*args):
    output = subprocess.check_output(
        ["bash", str(RUNNER), *args],
        cwd=REPO_DIR,
        text=True,
    )
    return [line for line in output.splitlines() if line]


def test_profile_data_shell_runner_covers_shell_tests_once():
    groups = _runner_lines("list")
    assert "common" not in groups
    assert {"common-observation-profiler", "common-observation-other", "common-execution-run", "common-execution-other"} <= set(groups)

    grouped_tests = []
    for group in groups:
        grouped_tests.extend(_runner_lines("list-tests", group))

    all_tests = _runner_lines("list-tests")
    assert grouped_tests == all_tests
    assert len(grouped_tests) == len(set(grouped_tests))

    discovered_tests = sorted(
        str(path.relative_to(REPO_DIR))
        for path in (REPO_DIR / "scripts/tests").glob("test_*.sh")
    )
    assert sorted(grouped_tests) == discovered_tests

    for test_path in grouped_tests:
        assert (REPO_DIR / test_path).is_file()


def test_common_alias_covers_both_parts_without_overlap():
    observation = _runner_lines("list-tests", "common-observation")
    execution = _runner_lines("list-tests", "common-execution")
    assert observation and execution
    assert not set(observation) & set(execution)
    assert _runner_lines("list-tests", "common") == observation + execution


@pytest.mark.parametrize("group", ["common-observation-profiler", "common-observation-other", "common-observation", "common", "common-execution", "common-execution-run", "common-execution-other", "all"])
def test_runner_dispatches_each_selected_test_once(tmp_path, group):
    tools = tmp_path / "bin"
    tools.mkdir()
    record = tmp_path / "executed"
    fake_bash = tools / "bash"
    fake_bash.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"$TEST_EXECUTION_RECORD\"\n"
    )
    fake_bash.chmod(0o700)
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
               TEST_EXECUTION_RECORD=str(record))
    subprocess.run([shutil.which("bash"), str(RUNNER), group], cwd=REPO_DIR,
                   env=env, check=True, capture_output=True, text=True)
    dispatched = [str(Path(line).relative_to(REPO_DIR))
                  for line in record.read_text().splitlines()]
    assert dispatched == _runner_lines("list-tests", group)
    assert len(dispatched) == len(set(dispatched))


def test_execution_alias_covers_both_parts_without_overlap():
    execution = _runner_lines("list-tests", "common-execution")
    run = _runner_lines("list-tests", "common-execution-run")
    other = _runner_lines("list-tests", "common-execution-other")
    assert run and other
    assert not set(run) & set(other)
    assert run + other == execution


@pytest.mark.parametrize("group", ["common-observation-profiler", "common-observation-other", "common-observation", "common-execution-run", "common-execution-other", "common-execution", "common", "all"])
@pytest.mark.parametrize("failure_position", ["first", "last"])
def test_runner_stops_and_returns_failure(tmp_path, group, failure_position):
    tools = tmp_path / "bin"
    tools.mkdir()
    record = tmp_path / "executed"
    fake_bash = tools / "bash"
    fake_bash.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$1\" >> \"$TEST_EXECUTION_RECORD\"\n[ \"$1\" != \"$TEST_FAILURE_PATH\" ] || exit 7\n"
    )
    fake_bash.chmod(0o700)
    selected = _runner_lines("list-tests", group)
    failure_index = 0 if failure_position == "first" else len(selected) - 1
    result = subprocess.run([shutil.which("bash"), str(RUNNER), group], cwd=REPO_DIR,
                            env=dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                                     TEST_EXECUTION_RECORD=str(record),
                                     TEST_FAILURE_PATH=str(REPO_DIR / selected[failure_index])),
                            capture_output=True, text=True)
    assert result.returncode == 7
    assert record.read_text().splitlines() == [
        str(REPO_DIR / path) for path in selected[:failure_index + 1]
    ]


def test_observation_alias_covers_both_parts_without_overlap():
    observation = _runner_lines("list-tests", "common-observation")
    profiler = _runner_lines("list-tests", "common-observation-profiler")
    other = _runner_lines("list-tests", "common-observation-other")
    assert profiler and other
    assert not set(profiler) & set(other)
    assert profiler + other == observation


@pytest.mark.parametrize("group", ["common-observation", "common", "all"])
def test_parallel_cases_cover_all_parts_without_duplicates(group):
    cases = _runner_lines("list-cases", group)
    assert len(cases) == len(set(cases))
    files = _runner_lines("list-tests", group)
    assert set(case.split("::")[0] for case in cases) == set(files)
    for file in files:
        selected = [case for case in cases if case.split("::")[0] == file]
        if "::" in selected[0]:
            parts = subprocess.check_output(["bash", str(REPO_DIR / file), "--list-parts"], text=True).splitlines()
            assert selected == [file + "::" + part for part in parts]
        else:
            assert selected == [file]


@pytest.mark.parametrize("group", ["common-observation", "common", "all"])
@pytest.mark.parametrize("position", ["first", "last"])
def test_parallel_dispatch_and_failure_propagation(tmp_path, group, position):
    import json
    import sys
    tools = tmp_path / "bin"
    tools.mkdir()
    records = tmp_path / "records"
    records.mkdir()
    checker = tools / "bash"
    checker.write_text("#!" + sys.executable + "\n" +
        "import json, os, sys\n" +
        "from pathlib import Path\n" +
        "Path(os.environ['CASE_RECORDS'],str(os.getpid())).write_text(json.dumps(sys.argv[1:]))\n" +
        "case=sys.argv[1]+('::'+sys.argv[2] if len(sys.argv)>2 else '')\n" +
        "raise SystemExit(7 if case==os.environ['FAIL_CASE'] else 0)\n")
    checker.chmod(0o700)
    cases = _runner_lines("list-cases", group)
    selected = cases[0 if position == "first" else -1]
    def absolute(case):
        file, sep, part = case.partition("::")
        return str(REPO_DIR / file) + (sep + part if sep else "")
    result = subprocess.run([shutil.which("bash"), str(RUNNER), group, "--jobs", "2"],
        cwd=REPO_DIR, env=dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'],
            CASE_RECORDS=str(records), FAIL_CASE=absolute(selected)), capture_output=True)
    assert result.returncode == 7
    seen = []
    for path in records.iterdir():
        args = json.loads(path.read_text())
        seen.append(str(Path(args[0]).relative_to(REPO_DIR)) + ("::"+args[1] if len(args)>1 else ""))
    assert sorted(seen) == sorted(cases)


@pytest.mark.parametrize("script", ["test_bk_profiler.sh", "test_bk_input_info.sh", "test_build_cache.sh", "test_bk_run.sh"])
def test_unknown_part_is_rejected_before_tests(script):
    result = subprocess.run(["bash", str(REPO_DIR / "scripts/tests" / script), "unknown"], capture_output=True)
    assert result.returncode == 2
