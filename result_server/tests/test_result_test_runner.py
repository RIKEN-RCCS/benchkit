"""Exercise complete, disjoint file selection and real pytest exit statuses."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest

SCRIPT = Path(__file__).with_name("run_result_server_tests.py")
spec = importlib.util.spec_from_file_location("result_test_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize("count", [2, 4])
def test_file_shards_cover_nested_new_tests_once_with_stable_order(tmp_path, count):
    names = ["test_big.py", "test_small.py", "nested/test_new.py", "nested/new_test.py"]
    for index, name in enumerate(names):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("#" * (40 - index * 9))
    (tmp_path / "helper.py").write_text("not a test")
    groups = runner.split_test_files(tmp_path, count)
    assert all(groups)
    assert sum(map(len, groups)) == len(set(sum((list(g) for g in groups), [])))
    assert set(sum((list(g) for g in groups), [])) == {tmp_path / name for name in names}
    assert groups == runner.split_test_files(tmp_path, count)
    assert all(group == sorted(group) for group in groups)


@pytest.mark.parametrize("shard", [None, 0, 1])
@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 5])
def test_runner_returns_pytest_status_and_preserves_arguments(tmp_path, monkeypatch, shard, status):
    script = tmp_path / "result_server/tests/run_result_server_tests.py"
    script.parent.mkdir(parents=True)
    for name in ("test_a.py", "test_b.py"):
        script.with_name(name).write_text("def test_example(): pass\n")
    monkeypatch.setattr(runner, "__file__", str(script))
    calls = []
    monkeypatch.setattr(runner.pytest, "main", lambda args: calls.append(args) or status)
    args = ["runner", "-q", "-n", "2", "--dist", "loadfile"]
    if shard is not None:
        args += ["--shard", str(shard)]
    assert runner.main(args) == status
    expected = [script.parent] if shard is None else runner.split_test_files(script.parent)[shard]
    assert calls == [[*(str(p) for p in expected), "-q", "-n", "2", "--dist", "loadfile"]]


@pytest.mark.parametrize("value", ["-1", "2", "bad"])
def test_invalid_shard_fails_before_pytest(monkeypatch, value):
    monkeypatch.setattr(runner.pytest, "main", lambda args: pytest.fail("must not run pytest"))
    with pytest.raises(SystemExit) as error:
        runner.main(["runner", "--shard", value])
    assert error.value.code != 0


def test_empty_shard_fails_before_pytest(tmp_path, monkeypatch):
    script = tmp_path / "result_server/tests/run_result_server_tests.py"
    script.parent.mkdir(parents=True)
    monkeypatch.setattr(runner, "__file__", str(script))
    monkeypatch.setattr(runner.pytest, "main", lambda args: pytest.fail("must not run pytest"))
    assert runner.main(["runner", "--shard", "0"]) != 0


def test_real_shards_collect_all_cases_and_propagate_failure(tmp_path):
    tests = tmp_path / "result_server/tests"
    tests.mkdir(parents=True)
    script = tests / SCRIPT.name
    shutil.copyfile(SCRIPT, script)
    (tests / "test_pass.py").write_text("def test_pass(): assert True\n")
    (tests / "test_fail.py").write_text("def test_fail(): assert False\n")
    (tests / "conftest.py").write_text(textwrap.dedent("""\
        import json
        from pathlib import Path

        calls = []

        def pytest_runtest_logreport(report):
            if report.when == "call":
                calls.append([report.nodeid, report.outcome])

        def pytest_sessionfinish(session, exitstatus):
            Path("observed.json").write_text(json.dumps({
                "collected": [item.nodeid for item in session.items], "calls": calls,
            }))
    """))
    seen = []
    outcomes = []
    statuses = []
    for index in range(2):
        report = tmp_path / "observed.json"
        report.unlink(missing_ok=True)
        result = subprocess.run([sys.executable, str(script), "--shard", str(index), "-q"],
                                cwd=tmp_path, capture_output=True, text=True)
        observation = json.loads(report.read_text())
        assert observation["collected"] == [node for node, _ in observation["calls"]]
        seen.extend(observation["collected"])
        outcomes.extend(observation["calls"])
        statuses.append(result.returncode)
    assert sorted(seen) == ["result_server/tests/test_fail.py::test_fail", "result_server/tests/test_pass.py::test_pass"]
    assert sorted(outcomes) == [
        ["result_server/tests/test_fail.py::test_fail", "failed"],
        ["result_server/tests/test_pass.py::test_pass", "passed"],
    ]
    assert sorted(statuses) == [0, 1]


def _shell_gate():
    workflow = (SCRIPT.parents[2] / ".github/workflows/result-server-tests.yml").read_text()
    return textwrap.dedent(workflow.split("      - name: Check shell test groups\n", 1)[1].split("        run: |\n", 1)[1])


@pytest.mark.parametrize("scope", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("full", ["true", "false"])
@pytest.mark.parametrize("shell", ["success", "failure", "cancelled", "skipped"])
def test_shell_aggregate_rejects_incomplete_groups(scope, full, shell):
    import os
    result = subprocess.run(["bash", "-c", _shell_gate()],
                            env=dict(os.environ, SCOPE_STATUS=scope, FULL_TESTS=full, SHELL_STATUS=shell,
                                     PYTEST_STATUS="success", DB_STATUS="success"),
                            capture_output=True)
    expected = scope == "success" and shell == "success"
    assert (result.returncode == 0) == expected


@pytest.mark.parametrize("shard", range(4))
@pytest.mark.parametrize("status", range(6))
def test_four_shards_preserve_pytest_status(tmp_path, monkeypatch, shard, status):
    script = tmp_path / "result_server/tests/run_result_server_tests.py"
    script.parent.mkdir(parents=True)
    for index in range(4):
        script.with_name(f"test_{index}.py").write_text("def test_example(): pass\n")
    monkeypatch.setattr(runner, "__file__", str(script))
    calls = []
    monkeypatch.setattr(runner.pytest, "main", lambda args: calls.append(args) or status)
    assert runner.main(["runner", "--shard-count", "4", "--shard", str(shard), "-q"]) == status
    assert calls == [[*(str(p) for p in runner.split_test_files(script.parent, 4)[shard]), "-q"]]


@pytest.mark.parametrize("job", ["PYTEST_STATUS", "DB_STATUS"])
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped"])
@pytest.mark.parametrize("full", ["true", "false"])
def test_aggregate_rejects_incomplete_python_jobs(job, status, full):
    import os
    env = dict(os.environ, SCOPE_STATUS="success", FULL_TESTS=full,
               SHELL_STATUS="success", PYTEST_STATUS="success", DB_STATUS="success")
    env[job] = status
    assert subprocess.run(["bash", "-c", _shell_gate()], env=env, capture_output=True).returncode != 0


def test_scope_validation_rejects_missing_or_unknown_decisions():
    import os
    workflow = (SCRIPT.parents[2] / ".github/workflows/result-server-tests.yml").read_text()
    command = workflow.split("      - name: Validate test scope\n", 1)[1].split("        run: |\n", 1)[1].split("\n\n", 1)[0]
    command = textwrap.dedent(command)
    for decision in ["true", "false", "", "unknown"]:
        status = subprocess.run(["bash", "-c", command], env=dict(os.environ, FULL_TESTS=decision)).returncode
        assert (status == 0) == (decision in {"true", "false"})


def test_workflow_runs_preparation_without_waiting_for_scope_job():
    workflow = (SCRIPT.parents[2] / ".github/workflows/result-server-tests.yml").read_text()
    jobs = ["pytest", "encrypted-budget-db", "profile-data-shell-group", "profile-data-shell"]
    for index, job in enumerate(jobs[:-1]):
        section = workflow.split(f"  {job}:\n", 1)[1].split(f"  {jobs[index+1]}:\n", 1)[0]
        assert "needs:" not in section
        assert "fetch-depth: 0" in section
        assert "id: scope" in section
        assert "run: python3 scripts/tests/ci_test_scope.py" in section
        assert "- name: Validate test scope" in section
        # Only selection and validation may run without the explicit full flag.
        steps = section.split("      - name: ")[1:]
        for step in steps[3:]:
            assert "if: steps.scope.outputs.full == 'true'" in step
    assert "--shard-count 4" in workflow
    assert "--jobs 2" in workflow
    assert "needs: [test-scope, pytest, encrypted-budget-db, profile-data-shell-group]" in workflow
