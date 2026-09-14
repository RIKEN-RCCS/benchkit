import subprocess
from pathlib import Path


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
    assert groups == ["common", "result-sender", "estimation"]

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
