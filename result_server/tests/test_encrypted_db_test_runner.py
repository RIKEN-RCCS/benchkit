"""Check SQLCipher selection coverage, fail-closed validation, and exit codes."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("run_encrypted_db_tests.py")
spec = importlib.util.spec_from_file_location("encrypted_db_test_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_groups_keep_the_existing_sqlcipher_selection_once():
    # Preserve the pre-split workflow selection, including the runtime report test.
    expected = {
        "test_budget_registry.py", "test_budget_routes.py", "test_budget_groups.py",
        "test_budget_group_routes.py", "test_db_migrations.py", "test_runner_observations.py",
        "test_runner_observation_ingest_storage.py", "test_runner_observation_handoff.py",
        "test_budget_profile_preview.py", "test_budget_pipeline.py",
        "test_budget_profile_binding.py", "test_sqlcipher_runtime_report.py",
    }
    first, second = runner.TEST_GROUPS
    assert first and second
    assert not set(first) & set(second)
    assert len(first + second) == len(set(first + second))
    assert set(first + second) == expected


@pytest.mark.parametrize("shard", [None, 0, 1])
@pytest.mark.parametrize("status", [0, 1, 2, 3, 4, 5])
def test_status_and_worker_arguments_are_preserved(monkeypatch, shard, status):
    monkeypatch.setattr(runner.importlib, "import_module", lambda name: object())
    calls = []
    monkeypatch.setattr(runner.pytest, "main", lambda args: calls.append(args) or status)
    args = ["runner", "-q", "-n", "2", "--dist", "loadfile"]
    if shard is not None:
        args += ["--shard", str(shard)]
    assert runner.main(args) == status
    names = sum(runner.TEST_GROUPS, ()) if shard is None else runner.TEST_GROUPS[shard]
    assert calls == [[*(str(SCRIPT.parent / name) for name in names), "-q", "-n", "2", "--dist", "loadfile"]]


def test_missing_sqlcipher_cannot_skip_the_suite(monkeypatch):
    def missing(name):
        raise ImportError("fixture missing driver")
    monkeypatch.setattr(runner.importlib, "import_module", missing)
    monkeypatch.setattr(runner.pytest, "main", lambda args: pytest.fail("must not run pytest"))
    assert runner.main(["runner", "--shard", "0"]) != 0


@pytest.mark.parametrize("value", ["-1", "2", "bad"])
def test_invalid_shard_never_runs_pytest(monkeypatch, value):
    monkeypatch.setattr(runner.pytest, "main", lambda args: pytest.fail("must not run pytest"))
    with pytest.raises(SystemExit) as result:
        runner.main(["runner", "--shard", value])
    assert result.value.code != 0


@pytest.mark.parametrize("groups", [((), ()), (("missing.py",), ()),
                                      (("test_budget_routes.py", "test_budget_routes.py"), ())])
def test_invalid_file_selection_never_passes(monkeypatch, groups):
    monkeypatch.setattr(runner.importlib, "import_module", lambda name: object())
    monkeypatch.setattr(runner, "TEST_GROUPS", groups)
    monkeypatch.setattr(runner.pytest, "main", lambda args: pytest.fail("must not run pytest"))
    assert runner.main(["runner", "--shard", "0"]) != 0


def test_real_pytest_failure_is_not_hidden_by_sharding(tmp_path):
    import subprocess
    import sys
    pytest.importorskip("sqlcipher3")
    script = tmp_path / SCRIPT.name
    source = SCRIPT.read_text().replace(
        'if __name__ == "__main__":',
        'TEST_GROUPS = (("test_pass.py",), ("test_fail.py",))\n\nif __name__ == "__main__":')
    script.write_text(source)
    (tmp_path / "test_pass.py").write_text("def test_pass(): assert True\n")
    (tmp_path / "test_fail.py").write_text("def test_fail(): assert False\n")
    statuses = []
    for shard in (0, 1):
        result = subprocess.run([sys.executable, str(script), "--shard", str(shard), "-q"],
                                cwd=tmp_path, capture_output=True, text=True)
        statuses.append(result.returncode)
    assert statuses == [0, 1]
