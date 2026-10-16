"""Exercise complete, disjoint file selection and real pytest exit statuses."""
import importlib.util
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


def test_file_shards_cover_nested_new_tests_once_with_stable_order(tmp_path):
    names = ["test_big.py", "test_small.py", "nested/test_new.py", "nested/new_test.py"]
    for index, name in enumerate(names):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("#" * (40 - index * 9))
    (tmp_path / "helper.py").write_text("not a test")
    groups = runner.split_test_files(tmp_path)
    assert all(groups)
    assert not set(groups[0]) & set(groups[1])
    assert set(groups[0] + groups[1]) == {tmp_path / name for name in names}
    assert groups == runner.split_test_files(tmp_path)
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
    seen = []
    statuses = []
    for index in range(2):
        collection = subprocess.run([sys.executable, str(script), "--shard", str(index),
                                     "--collect-only", "-q"], cwd=tmp_path, capture_output=True, text=True)
        assert collection.returncode == 0, collection.stdout + collection.stderr
        seen.extend(line for line in collection.stdout.splitlines() if "::test_" in line)
        result = subprocess.run([sys.executable, str(script), "--shard", str(index), "-q"],
                                cwd=tmp_path, capture_output=True, text=True)
        statuses.append(result.returncode)
    assert sorted(seen) == ["result_server/tests/test_fail.py::test_fail", "result_server/tests/test_pass.py::test_pass"]
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
                            env=dict(os.environ, SCOPE_STATUS=scope, FULL_TESTS=full, SHELL_STATUS=shell),
                            capture_output=True)
    expected = scope == "success" and ((full == "true" and shell == "success")
                                       or (full == "false" and shell == "skipped"))
    assert (result.returncode == 0) == expected
