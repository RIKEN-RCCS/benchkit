"""Exercise bounded concurrency and complete failure reporting of shell cases."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/tests/run_shell_test_cases.py"


@pytest.mark.parametrize("failed", ["", "first.sh", "last.sh"])
def test_two_workers_finish_all_cases_and_report_failures(tmp_path, failed):
    tools = tmp_path / "tools"
    tools.mkdir()
    state = tmp_path / "state"
    state.write_text(json.dumps({"active": 0, "max": 0, "seen": []}))
    bash = tools / "bash"
    bash.write_text("#!" + sys.executable + "\n" + textwrap.dedent('''
        import fcntl, json, os, pathlib, sys, time
        def update(delta):
            with open(os.environ['STATE'], 'r+') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                data = json.load(stream)
                data['active'] += delta
                data['max'] = max(data['max'], data['active'])
                if delta > 0: data['seen'].append(sys.argv[1:])
                stream.seek(0); json.dump(data,stream); stream.truncate()
        update(1)
        time.sleep(0.08)
        update(-1)
        print(pathlib.Path(sys.argv[1]).name)
        raise SystemExit(7 if pathlib.Path(sys.argv[1]).name==os.environ['FAILED'] else 0)
    '''))
    bash.chmod(0o700)
    cases = ["first.sh::part", "space name.sh", "line\nbreak.sh", "last.sh"]
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), *cases],
        env=dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'],
                 STATE=str(state), FAILED=failed), capture_output=True)
    assert result.returncode == (7 if failed else 0)
    data = json.loads(state.read_text())
    expected = []
    for case in cases:
        path, sep, part = case.partition("::")
        expected.append([str(tmp_path/path)] + ([part] if sep else []))
    assert sorted(data['seen']) == sorted(expected)
    assert data['max'] == 2 and data['active'] == 0
    assert b"first.sh" in result.stdout and b"last.sh" in result.stdout


@pytest.mark.parametrize("cases", [[], ["same", "same"]])
def test_missing_or_duplicate_cases_are_rejected(tmp_path, cases):
    assert subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), *cases],
                          capture_output=True).returncode == 2


@pytest.mark.parametrize("name", ["test_run_output.py", "test_input_manifest.py"])
def test_execution_test_parts_cover_each_case_once(name):
    path = ROOT / "scripts/tests" / name
    spec = importlib.util.spec_from_file_location("execution_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import unittest
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    groups = module.split_run_tests(suite)
    ids = [case.id() for group in groups for case in group]
    assert ids and len(ids) == len(set(ids)) == suite.countTestCases()
    assert all(groups)


@pytest.mark.parametrize("name", ["test_bk_profiler.sh", "test_bk_input_info.sh", "test_build_cache.sh", "test_bk_run.sh"])
@pytest.mark.parametrize("failed", [False, True])
def test_default_part_dispatch_is_complete_and_propagates_failure(tmp_path, name, failed):
    import shutil
    helper = ROOT / "scripts/tests/shell_test_parts.sh"
    parts = subprocess.check_output(["bash", str(ROOT / "scripts/tests" / name), "--list-parts"], text=True).splitlines()
    tools = tmp_path / "tools"
    tools.mkdir()
    record = tmp_path / "record"
    fake = tools / "bash"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$2" >> "$RECORD"\n[ "$2" != "$FAIL_PART" ] || exit 7\n')
    fake.chmod(0o700)
    command = 'set -euo pipefail; source "$1"; shell_test_parts_init "$2"'
    result = subprocess.run([shutil.which("bash"), "-c", command, "bash", str(helper), name],
        env=dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'], RECORD=str(record),
                 FAIL_PART=parts[0] if failed else ""), capture_output=True)
    assert result.returncode == (7 if failed else 0)
    assert record.read_text().splitlines() == (parts[:1] if failed else parts)



def test_shell_parts_keep_every_original_scenario_registered():
    expected = {
        "test_bk_profiler.sh": ["fapp-basic", "fapp-detailed", "ncu-failures"],
        "test_bk_input_info.sh": ["declarations", "verification", "directory"] +
                                  ["manifest-" + str(i) for i in range(4)],
        "test_build_cache.sh": ["cache", "git-tools"],
        "test_bk_run.sh": [str(i) for i in range(8)],
    }
    for name, parts in expected.items():
        actual = subprocess.check_output(["bash", str(ROOT / "scripts/tests" / name), "--list-parts"], text=True).splitlines()
        assert actual == parts
