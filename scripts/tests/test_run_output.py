"""Common execution contracts using synthetic launchers, not benchmark values."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


class RunOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[2]
        self.state = self.root / "state"
        tools = self.root / "bin"
        tools.mkdir()
        for name in ("bash", "realpath", "mktemp", "rm", "find", "head", "sort",
                     "stat", "dd", "sha256sum", "tail", "od", "tr", "cat", "mv"):
            (tools / name).symlink_to(shutil.which(name))
        self.env = dict(os.environ, PATH=str(tools))
        self.log = self.root / "combined.log"
        self.log.write_bytes(b"launcher\n")
        self.rank = self.root / "output.job/0/1/stdout.1.0"
        self.rank.parent.mkdir(parents=True)
        self.rank.write_bytes(b"old success\n")

    def collector(self, command, *, check=True):
        result = subprocess.run([shutil.which("bash"), str(self.repo / "scripts/run_output.sh"),
                                 command, "--state", str(self.state), "--log", str(self.log)],
                                cwd=self.root, env=self.env, capture_output=True, timeout=15)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_collects_only_current_rank_zero_output(self):
        self.collector("snapshot")
        (self.rank.parent / "stdout.1.1").write_bytes(b"other rank\n")
        (self.root / "input").mkdir()
        (self.root / "input/stdout.1.0").write_bytes(b"input contents\n")
        (self.root / "stdout.2.0").write_bytes(b"current output\n")
        (self.root / "stderr.2.0").write_bytes(b"current error\n")
        self.collector("collect")
        text = self.log.read_text()
        for included in ("launcher", "current output", "current error"):
            self.assertIn(included, text)
        for excluded in ("old success", "other rank", "input contents"):
            self.assertNotIn(excluded, text)

    def test_append_overwrite_and_replacement_are_scoped(self):
        for operation in ("append", "overwrite", "replace"):
            with self.subTest(operation=operation):
                self.log.write_bytes(b"")
                self.rank.write_bytes(b"old success\n")
                self.collector("snapshot")
                if operation == "replace":
                    replacement = self.rank.with_suffix(".replacement")
                    replacement.write_bytes(b"new success\n")
                    replacement.replace(self.rank)
                elif operation == "append":
                    with self.rank.open("ab") as output:
                        output.write(b"new success\n")
                else:
                    self.rank.write_bytes(b"new success\n")
                self.collector("collect")
                self.assertIn("new success", self.log.read_text())
                self.assertNotIn("old success", self.log.read_text())

    def test_partial_old_line_cannot_complete_a_success_pattern(self):
        self.rank.write_bytes(b"old partial")
        self.collector("snapshot")
        with self.rank.open("ab") as output:
            output.write(b" success\nnew line\n")
        self.collector("collect")
        self.assertNotIn("success", self.log.read_text())
        self.assertIn("new line", self.log.read_text())

    def test_links_special_files_and_limits(self):
        outside = self.root / "private"
        outside.write_bytes(b"must not collect")
        (self.root / "stdout.9.0").symlink_to(outside)
        (self.root / "output.link").symlink_to(outside.parent, target_is_directory=True)
        os.mkfifo(self.root / "stdout.8.0")
        self.collector("snapshot")
        self.collector("collect")
        self.assertEqual(self.log.read_bytes(), b"launcher\n")
        with self.rank.open("wb") as stream:
            stream.truncate(256 * 1024 * 1024 + 1)
        self.assertNotEqual(self.collector("collect", check=False).returncode, 0)
        self.assertEqual(self.log.read_bytes(), b"launcher\n")
        self.rank.unlink()
        for index in range(10001):
            (self.root / f"ignored-{index}").touch()
        self.assertNotEqual(self.collector("snapshot", check=False).returncode, 0)

    def test_binary_output_unusual_paths_and_depth(self):
        directory = self.root / "output. space\n'[]$()" / "0" / "1"
        directory.mkdir(parents=True)
        rank = directory / "stdout.3.0"
        rank.write_bytes(b"old\0\n")
        too_deep = self.root / "output.deep/1/2/3/4/5/stdout.1.0"
        too_deep.parent.mkdir(parents=True)
        too_deep.write_bytes(b"too deep\n")
        self.collector("snapshot")
        with rank.open("ab") as stream:
            stream.write(b"new\0binary\n")
        too_deep.write_bytes(b"changed but too deep\n")
        self.collector("collect")
        self.assertEqual(self.log.read_bytes(), b"launcher\n\nnew\0binary\n")

    def test_failed_scan_does_not_publish_partial_output(self):
        self.collector("snapshot")
        (self.root / "stdout.1.0").write_bytes(b"valid new output\n")
        with (self.root / "stdout.9.0").open("wb") as stream:
            stream.truncate(256 * 1024 * 1024 + 1)
        self.assertNotEqual(self.collector("collect", check=False).returncode, 0)
        self.assertEqual(self.log.read_bytes(), b"launcher\n")

    def test_incomplete_state_is_rejected(self):
        self.collector("snapshot")
        self.state.write_bytes(self.state.read_bytes()[:-1])
        self.assertNotEqual(self.collector("collect", check=False).returncode, 0)
        self.assertEqual(self.log.read_bytes(), b"launcher\n")

    def test_source_changes_and_replacements_during_read_are_rejected(self):
        self.collector("snapshot")
        wrapper = self.root / "bin/dd"
        wrapper.unlink()
        wrapper.write_text('''#!/bin/bash
set -eu
for argument in "$@"; do
  case "$argument" in if=*) source_file="${argument#if=}" ;; esac
done
case "$CHANGE_MODE" in
  symlink) rm -- "$source_file"; "$REAL_LN" -s "$OUTSIDE" "$source_file" ;;
  fifo) rm -- "$source_file"; "$REAL_MKFIFO" "$source_file" ;;
esac
"$REAL_DD" "$@"
[ "$CHANGE_MODE" != mutate ] || printf changed >> "$source_file"
''')
        wrapper.chmod(0o700)
        outside = self.root / "private"
        outside.write_bytes(b"must not collect\n")
        self.env.update(REAL_DD=shutil.which("dd"), REAL_LN=shutil.which("ln"),
                        REAL_MKFIFO=shutil.which("mkfifo"), OUTSIDE=str(outside))
        for mode in ("mutate", "symlink", "fifo"):
            with self.subTest(mode=mode):
                self.rank.unlink()
                self.rank.write_bytes(b"new output\n")
                self.env["CHANGE_MODE"] = mode
                self.assertNotEqual(self.collector("collect", check=False).returncode, 0)
                self.assertEqual(self.log.read_bytes(), b"launcher\n")


class RuntimeMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[2]
        tools = self.root / "bin"
        tools.mkdir()
        for name in ("bash", "dirname", "basename", "mkdir", "flock", "cmp", "rm"):
            (tools / name).symlink_to(shutil.which(name))
        self.env = dict(os.environ, PATH=str(tools))
        self.directory = self.root / "results space\n'[]$()"
        self.directory.mkdir()
        self.info = self.directory / "info.json"
        self.items = self.directory / "items.jsonl"
        self.context = self.directory / ".workflow_session.json"

    def command(self, session, kind="timing", items=None):
        return [shutil.which("bash"), str(self.repo / "scripts/runtime_metadata.sh"),
                "--session", session, "--kind", kind, "--info", str(self.info),
                "--items", str(items or self.items)]

    def initialize(self, session, **options):
        subprocess.run(self.command(session, **options), env=self.env,
                       check=True, capture_output=True, timeout=15)

    def seed(self):
        for path in (self.info, self.items, self.context):
            path.write_bytes(b"recorded data")

    def test_once_per_session_and_item_destination(self):
        self.seed()
        self.initialize("first")
        self.assertFalse(any(path.exists() for path in (self.info, self.items, self.context)))
        self.seed()
        self.initialize("first")
        self.assertTrue(all(path.read_bytes() == b"recorded data"
                            for path in (self.info, self.items, self.context)))
        replacement = self.directory / "other-items"
        replacement.touch()
        self.initialize("first", items=replacement)
        self.assertFalse(replacement.exists())
        self.assertTrue(self.items.exists())
        self.seed()
        self.initialize("second")
        self.assertFalse(any(path.exists() for path in (self.info, self.items, self.context)))

    def test_input_initialization_leaves_timing_context(self):
        self.seed()
        self.initialize("first", kind="input")
        self.assertFalse(self.info.exists())
        self.assertFalse(self.items.exists())
        self.assertTrue(self.context.exists())

    def test_concurrent_children_do_not_reset_same_session(self):
        self.initialize("shared")
        self.seed()
        processes = [subprocess.Popen(self.command("shared"), env=self.env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(8)]
        try:
            for process in processes:
                _, error = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, error)
            self.assertEqual(self.info.read_bytes(), b"recorded data")
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_failed_reset_does_not_mark_session_initialized(self):
        self.info.mkdir()
        result = subprocess.run(self.command("first"), env=self.env,
                                capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.info.rmdir()
        self.seed()
        self.initialize("first")
        self.assertFalse(self.info.exists())

    def test_session_read_error_keeps_existing_records(self):
        self.initialize("first")
        self.seed()
        comparator = self.root / "bin/cmp"
        comparator.unlink()
        comparator.write_text("#!/bin/bash\nexit 2\n")
        comparator.chmod(0o700)
        result = subprocess.run(self.command("second"), env=self.env,
                                capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(path.read_bytes() == b"recorded data"
                            for path in (self.info, self.items, self.context)))


class RunHelperTests(unittest.TestCase):
    def input_info(self, path=None):
        env = dict(os.environ)
        if path:
            env["BK_INPUT_INFO_FILE"] = str(path)
        result = subprocess.run(["bash", str(self.repo / "scripts/result_server/input_info.sh"),
                                 "--results-dir", str(self.root / "results")],
                                env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[2]
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("BK_", "_BK_"))}
        self.env["PYTHON_BIN"] = sys.executable
        self.env["TEST_REPO"] = str(self.repo)

    def run_shell(self, code):
        return subprocess.run(["bash", "-c", '''
set -euo pipefail
source "$TEST_REPO/scripts/bk_functions.sh"
''' + code], cwd=self.root, env=self.env, text=True, capture_output=True, timeout=15)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def profile_tools(self):
        directory = self.root / "bin"
        directory.mkdir(exist_ok=True)
        tool = directory / "ncu"
        tool.write_text('''#!/bin/bash
set -eu
if [ "$1" = --import ]; then
  [ "${FAIL_EXPORT:-0}" != 1 ] || exit 9
  printf 'metric,value\\nfake,1\\n'
  exit 0
fi
output=""; counts=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    --launch-count) counts=$((counts+1)); shift 2 ;;
    --launch-count=*) counts=$((counts+1)); shift ;;
    --set|--target-processes|--kernel-name-base|--kernel-name|--launch-skip) shift 2 ;;
    --*) shift ;;
    *) break ;;
  esac
done
test "$counts" -eq 1
"$@"
[ "${FAIL_CAPTURE:-0}" != 1 ] || exit 7
[ "${MISSING_REPORT:-0}" != 1 ] || exit 0
printf report > "$output.ncu-rep"
''')
        tool.chmod(0o700)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]

    def test_managed_profiles_keep_distinct_outputs_and_section_artifacts(self):
        self.profile_tools()
        result = self.run_shell('''
bk_run --log first.log -- true
bk_emit_result --from-log first.log --exp First --fom 1 > results/result
bk_emit_section solve 1 >> results/result
bk_run --log second.log -- true
bk_profile --from-log second.log -- bk_acquire_ncu --profile-name sample --kernel-regex sample --level detailed --section solve -- true
bk_emit_result --from-log second.log --exp Second --fom 2 >> results/result
bk_emit_section solve 2 >> results/result
bk_profile --from-log first.log -- bk_acquire_ncu --profile-name sample --kernel-regex sample --section solve -- true
bash "$TEST_REPO/scripts/result.sh" sample SampleSystem cross build run 42 > conversion.log
''')
        self.assert_ok(result)
        archives = list((self.root / "results").glob("profile_*/profile.tgz"))
        self.assertEqual(len(archives), 2)
        references = []
        for index, exp in ((0, "First"), (1, "Second")):
            document = json.loads((self.root / f"results/result{index}.json").read_text())
            self.assertEqual(document["Exp"], exp)
            references.append([item["path"] for item in document["fom_breakdown"]["sections"][0]["artifacts"]])
        self.assertTrue(all(len(items) == 2 and items[0].endswith(".tgz") for items in references))
        self.assertFalse(set(references[0]) & set(references[1]))
        for archive in archives:
            with tarfile.open(archive) as stream:
                self.assertIn("bk_profiler_artifact/meta.json", stream.getnames())
                self.assertIn("bk_profiler_artifact/raw/rep1/profile_raw.csv", stream.getnames())
                self.assertTrue(all(name.startswith("bk_profiler_artifact/") or name == "bk_profiler_artifact"
                                    for name in stream.getnames()))
                self.assertFalse(any(name.endswith(".ncu-rep") for name in stream.getnames()))

    def test_failed_acquisition_and_timeout_do_not_register_profiles(self):
        self.profile_tools()
        result = self.run_shell('''
bk_run --log out.log -- true
bk_emit_result --from-log out.log --exp Sample --fom 1 > results/result
for failure in capture missing timeout; do
  status=0
  case "$failure" in
    capture) FAIL_CAPTURE=1 bk_profile --from-log out.log -- bk_acquire_ncu --profile-name sample --kernel-regex sample --section solve -- true || status=$? ;;
    missing) MISSING_REPORT=1 bk_profile --from-log out.log -- bk_acquire_ncu --profile-name sample --kernel-regex sample --section solve -- true || status=$? ;;
    timeout) bk_profile --from-log out.log -- bk_acquire_ncu --profile-name sample --kernel-regex sample --section solve --timeout 1 -- sleep 3 || status=$? ;;
  esac
  test "$status" -ne 0
done
bk_emit_section solve 1 >> results/result
''')
        self.assert_ok(result)
        result_text = (self.root / "results/result").read_text()
        self.assertIn("FOM:1", result_text)
        self.assertIn("SECTION:solve time:1", result_text)
        self.assertNotIn("artifact:", result_text)
        documents = [json.loads(path.read_text()) for path in (self.root / "results").glob("workflow_timing_*.json")]
        stages = [stage for doc in documents for stage in doc["stages"]]
        self.assertTrue(any(stage.get("exit_code") == 124 for stage in stages))
        self.assertTrue(any(stage.get("exit_code") == 7 for stage in stages))

    def test_export_failure_keeps_archive_and_report_retention_is_explicit(self):
        self.profile_tools()
        result = self.run_shell('''
bk_run --log out.log -- true
FAIL_EXPORT=1 BK_PROFILER_ARCHIVE_NCU_REPORT=true bk_profile --from-log out.log -- \\
  bk_acquire_ncu --profile-name sample --kernel-regex sample --section solve -- true
bk_emit_result --from-log out.log --exp Sample --fom 1 > results/result
bk_emit_section solve 1 >> results/result
''')
        self.assert_ok(result)
        archive, = (self.root / "results").glob("profile_*/profile.tgz")
        with tarfile.open(archive) as stream:
            self.assertTrue(any(name.endswith(".ncu-rep") for name in stream.getnames()))
        document, = (self.root / "results").glob("workflow_timing_*.json")
        self.assertEqual(len(json.loads(document.read_text())["section_artifacts"]["solve"]), 2)

    def test_timing_parser_is_saved_and_registered_without_app_paths(self):
        result = self.run_shell('''
parser() { printf '{"schema_version":1,"kind":"sample_timing","summary":{"timer_count":1}}'; }
broken() { printf '{partial'; return 7; }
bk_run --log first.log -- true
bk_run --log second.log -- true
bk_emit_result --from-log first.log --from-log second.log --timing-parser parser --timing-producer sample --exp Combined --fom 2 > results/result
bk_emit_result --from-log first.log --timing-parser broken --exp Combined --fom 2 >> results/result
bash "$TEST_REPO/scripts/result.sh" sample SampleSystem cross build run 42 > conversion.log
''')
        self.assert_ok(result)
        items = json.loads((self.root / "results/timing_observations.json").read_text())["observations"]
        self.assertEqual(len(items), 2)
        self.assertEqual(len({item["id"] for item in items}), 2)
        self.assertTrue(all(item["result_exp"] == "Combined" for item in items))
        for item in items:
            self.assertEqual(json.loads((self.root / item["artifact"]["path"]).read_text())["kind"], "sample_timing")
        self.assertIn("FOM is retained", result.stderr)
        self.assertEqual(len(list((self.root / "results").glob("profile_*/timing.json"))), 2)

    def test_profile_registration_rejects_missing_scope_and_external_artifacts(self):
        self.profile_tools()
        (self.root / "outside.json").write_text("{}")
        result = self.run_shell('''
if bk_profile --from-log missing.log -- bk_acquire_ncu --profile-name sample --kernel-regex sample -- touch must-not-run; then exit 1; fi
test ! -e must-not-run
bk_run --log out.log -- true
if bk_profile --from-log out.log -- _bk_profile_register solve "$PWD/outside.json"; then exit 1; fi
bk_emit_result --from-log out.log --exp Sample --fom 1 > results/result
bk_emit_section solve 1 >> results/result
''')
        self.assert_ok(result)
        self.assertNotIn("artifact:", (self.root / "results/result").read_text())

    def test_stdin_functions_arguments_and_sequential_stage_isolation(self):
        result = self.run_shell('''
launcher() {
  test "$1" = 'two words'
  mkdir -p output.job/0/1
  cat > output.job/0/1/stdout.1.0
}
bk_run --log gs.log --elapsed gs_seconds -- launcher 'two words' <<< 'GS complete'
bk_run --log rt.log --elapsed rt_seconds -- launcher 'two words' <<< 'RT failed'
grep -q 'GS complete' gs.log
! grep -q 'GS complete' rt.log
grep -q 'RT failed' rt.log
[[ "$gs_seconds" =~ ^[0-9]+[.][0-9]+$ ]]
[[ "$rt_seconds" =~ ^[0-9]+[.][0-9]+$ ]]
''')
        self.assert_ok(result)
        stages = [stage for path in (self.root / "results").glob("workflow_timing_*.json")
                  for stage in json.loads(path.read_text())["stages"]]
        self.assertEqual(len(stages), 2)
        self.assertTrue(all(stage["status"] == "completed" for stage in stages))

    def test_failure_preserves_exit_code_and_diagnoses_collected_output(self):
        result = self.run_shell('''
bk_run --log failed.log -- bash -c 'printf "rank error\\n" > stderr.1.0; exit 23'
touch must-not-run
''')
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertIn("rank error", result.stderr)
        self.assertFalse((self.root / "must-not-run").exists())

    def test_stale_output_cannot_make_a_later_invocation_succeed(self):
        result = self.run_shell('''
printf 'success\n' > stdout.1.0
bk_run --log result.log -- true
! grep -q success result.log
test ! -e .run_marker
''')
        self.assert_ok(result)

    def test_log_capture_and_session_reset_do_not_require_python(self):
        result = self.run_shell('''
mkdir results
printf stale > results/input_info.json
printf stale > results/.workflow_session.json
export PYTHON_BIN=/nonexistent/python
bk_run --log captured.log -- bash -c 'printf "current output\\n" > stdout.1.0'
grep -q 'current output' captured.log
test ! -e results/input_info.json
test -f results/.workflow_session.json
status=0
bk_run --log failed.log -- bash -c 'printf "rank failure\\n" > stderr.1.0; exit 23' || status=$?
test "$status" -eq 23
grep -q 'rank failure' failed.log
! grep -q 'current output' failed.log
''')
        self.assert_ok(result)
        self.assertNotIn("/nonexistent/python", result.stderr)
        documents = [json.loads(path.read_text()) for path in (self.root / "results").glob("workflow_timing_*.json")]
        self.assertEqual(sorted(stage["exit_code"] for doc in documents for stage in doc["stages"]), [0, 23])

    def test_direct_output_remains_unmodified(self):
        result = self.run_shell("bk_run -- printf 'hello'; bk_run --elapsed duration -- printf ' world'")
        self.assert_ok(result)
        self.assertEqual(result.stdout, "hello world")

    def test_timing_and_output_binding_without_python_jq_or_curl(self):
        tools = self.root / "shell-tools"
        tools.mkdir()
        for name in ("bash", "date", "awk", "dirname", "basename", "mkdir", "mktemp",
                     "rm", "mv", "cp", "cat", "flock", "cmp", "sha256sum", "cut",
                     "od", "tr", "realpath", "find", "head", "sort", "stat", "dd", "tail",
                     "tee", "wc", "mkfifo"):
            (tools / name).symlink_to(shutil.which(name))
        self.env.update(PATH=str(tools), PYTHON_BIN="/nonexistent/python")
        result = self.run_shell('''
! command -v python3
! command -v jq
! command -v curl
printf 'actual input' > input
bk_run --log out.log --input-file input --elapsed duration -- printf 'output'
[[ "$duration" =~ ^[0-9]+[.][0-9]+$ ]]
bk_emit_result --from-log out.log --exp Sample --fom "$duration" > results/result
status=0
bk_profile --from-log out.log -- bk_profile_execute --tool example -- bash -c 'exit 23' || status=$?
test "$status" -eq 23
''')
        self.assert_ok(result)
        path, = (self.root / "results").glob("workflow_timing_*.json")
        document = json.loads(path.read_text())
        self.assertEqual(document["exp"], "Sample")
        self.assertEqual(document["elapsed_clock"], "realtime")
        self.assertEqual([stage["exit_code"] for stage in document["stages"]], [0, 23])
        self.assertNotIn("/nonexistent/python", result.stderr)
        item, = self.input_info()["inputs"]
        self.assertEqual(item["result_exp"], "Sample")
        self.assertEqual(item["sha256"], hashlib.sha256(b"actual input").hexdigest())
        self.assertEqual(json.loads(path.read_text()), document)

    def test_clock_samples_surround_command_not_recorder(self):
        result = self.run_shell('''
bash() {
  if [[ "$1" == */profiling/workflow_timing.sh ]]; then
    printf 'recorder-%s\\n' "$4" >> order
  fi
  command bash "$@"
}
_bk_clock_sample() {
  printf 'clock\\n' >> order
  if [ -f executed ]; then
    printf '1700000001.125000000|2023-11-14T22:13:21.125000000Z'
  else
    printf '1700000000.875000000|2023-11-14T22:13:20.875000000Z'
  fi
}
solver() { printf 'command\\n' >> order; : > executed; }
bk_run --elapsed duration -- solver
test "$duration" = 0.250000000
''')
        self.assert_ok(result)
        self.assertEqual((self.root / "order").read_text().splitlines(),
                         ["recorder-start", "clock", "command", "clock", "recorder-finish"])
        path, = (self.root / "results").glob("workflow_timing_*.json")
        stage = json.loads(path.read_text())["stages"][0]
        self.assertEqual(stage["elapsed_seconds"], 0.25)
        self.assertEqual(stage["command_started_at"], "2023-11-14T22:13:20.875000000Z")

    def test_backward_clock_cannot_publish_elapsed_or_hide_command_failure(self):
        result = self.run_shell('''
_bk_clock_sample() {
  if [ -f executed ]; then
    printf '1700000000.000000000|2023-11-14T22:13:20.000000000Z'
  else
    printf '1700000001.000000000|2023-11-14T22:13:21.000000000Z'
  fi
}
solver() { : > executed; return "$1"; }
for expected in 0 23; do
  rm -f executed
  duration=old
  status=0
  bk_run --elapsed duration -- solver "$expected" || status=$?
  test -z "$duration"
  if [ "$expected" -eq 0 ]; then test "$status" -ne 0; else test "$status" -eq 23; fi
done
''')
        self.assert_ok(result)
        path, = (self.root / "results").glob("workflow_timing_*.json")
        for stage in json.loads(path.read_text())["stages"]:
            self.assertEqual(stage["status"], "running")
            self.assertNotIn("elapsed_seconds", stage)

    def test_unsupported_date_output_stops_required_elapsed_before_launch(self):
        result = self.run_shell('''
date() { printf '1700000000.N|2023-11-14T22:13:20.NZ'; }
duration=old
status=0
bk_run --elapsed duration -- touch must-not-run || status=$?
test "$status" -ne 0
test -z "$duration"
test ! -e must-not-run
''')
        self.assert_ok(result)

    def test_result_and_delayed_profile_are_bound_by_output_not_execution_order(self):
        result = self.run_shell('''
bk_run --log first.log -- printf 'first\n'
bk_emit_result --from-log first.log --exp First --fom 1 > results/result
bk_run --log second.log -- printf 'second\n'
bk_emit_result --from-log second.log --exp Second --fom 2 >> results/result
bk_profile --from-log first.log -- bk_profile_execute --tool ncu --phase collect -- true
bash "$TEST_REPO/scripts/result_server/workflow_timing.sh" --results-dir results manifest > manifest.json
''')
        self.assert_ok(result)
        observations = json.loads((self.root / "manifest.json").read_text())["observations"]
        self.assertEqual({item["result_exp"] for item in observations}, {"First", "Second"})
        documents = {item["result_exp"]: json.loads((self.root / item["artifact"]["path"]).read_text())
                     for item in observations}
        self.assertEqual([stage["stage"] for stage in documents["First"]["stages"]], ["benchmark", "collect"])
        self.assertEqual([stage["stage"] for stage in documents["Second"]["stages"]], ["benchmark"])
        self.assertNotIn(str(self.root), json.dumps(documents))

    def test_profile_before_emission_and_multiple_runs_per_result(self):
        result = self.run_shell('''
bk_run --log gs.log -- true
bk_run --log rt.log -- true
bk_profile --from-log gs.log -- bk_profile_execute --tool nsys --phase collect -- true
bk_emit_result --from-log gs.log --from-log rt.log --exp Combined --fom 1 > results/result
bash "$TEST_REPO/scripts/result_server/workflow_timing.sh" --results-dir results manifest > manifest.json
''')
        self.assert_ok(result)
        observations = json.loads((self.root / "manifest.json").read_text())["observations"]
        self.assertEqual(len(observations), 2)
        self.assertTrue(all(item["result_exp"] == "Combined" for item in observations))

    def test_missing_conflicting_and_reused_outputs_do_not_relabel_old_runs(self):
        result = self.run_shell('''
bk_run --log out.log -- true
bk_emit_result --from-log out.log --exp First --fom 1 > results/result
bk_emit_result --from-log out.log --exp Wrong --fom 2 >> results/result
bk_emit_result --from-log missing.log --exp Missing --fom 2 >> results/result
bk_profile --from-log missing.log -- bk_profile_execute --tool ncu -- true
bk_run --log out.log -- true
bk_emit_result --from-log out.log --exp Second --fom 2 >> results/result
bk_run --log unbound.log -- true
bash "$TEST_REPO/scripts/result_server/workflow_timing.sh" --results-dir results manifest > manifest.json
''')
        self.assert_ok(result)
        observations = json.loads((self.root / "manifest.json").read_text())["observations"]
        self.assertEqual(sorted(item["result_exp"] for item in observations), ["First", "Second"])
        self.assertIn("association unavailable", result.stderr)

    def test_metadata_follows_root_without_app_exports_or_reset(self):
        (self.root / "results").mkdir()
        (self.root / "results/input_info.json").write_text('{"inputs":[{"dataset_id":"old"}]}')
        result = self.run_shell('''
mkdir work
bk_record_input --dataset-id first --parameter value one
cd work
bk_record_input --dataset-id second --parameter value two
bk_run --log out.log -- true
bk_emit_result --from-log out.log --exp Sample --fom 1 > ../results/result
test ! -d results
''')
        self.assert_ok(result)
        items = self.input_info()["inputs"]
        self.assertEqual([item["dataset_id"] for item in items], ["first", "second"])
        result = self.run_shell('bk_run --log new.log -- true')
        self.assert_ok(result)
        self.assertFalse((self.root / "results/input_info.json").exists())

    def test_input_files_and_parameters_are_observed_before_launch(self):
        (self.root / "input file").write_bytes(b"original input")
        result = self.run_shell('''
launcher() { test "$1" = private-launch-option; shift; "$@"; }
solver() {
  test "$1" = 'two words'
  test "$2" = ''
  printf changed > '../input file'
}
mkdir work
cd work
bk_run --log out.log --input-file '../input file' --parameter-input \\
  --launcher launcher private-launch-option -- solver 'two words' ''
bk_emit_result --from-log out.log --exp Sample --fom 1 > ../results/result
bk_emit_result --from-log out.log --exp Sample --fom 1 >> ../results/result
''')
        self.assert_ok(result)
        items = self.input_info()["inputs"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["result_exp"] == "Sample" for item in items))
        file_item = next(item for item in items if "sha256" in item)
        self.assertEqual(file_item["sha256"], hashlib.sha256(b"original input").hexdigest())
        parameters = next(item for item in items if "command" in item)
        self.assertEqual(parameters["command"], "solver")
        self.assertEqual(parameters["arguments"], ["two words", ""])
        self.assertNotIn("private-launch-option", json.dumps(items))
        self.assertNotIn(str(self.root), json.dumps(items))
        self.assertEqual(list((self.root / "results").glob(".run-input.*")), [])

    def test_input_destination_overrides_are_respected_on_result_binding(self):
        result = self.run_shell('''
export BK_INPUT_INFO_FILE="$PWD/custom/inputs.json"
export BK_INPUT_INFO_ITEMS_FILE="$PWD/custom/items/inputs.jsonl"
bk_record_input --dataset-id declared --parameter value one
bk_run --log out.log --parameter-input -- printf '%s' two
bk_emit_result --from-log out.log --exp Sample --fom 1 > results/result
bk_record_input --dataset-id later --parameter value three
test ! -f results/input_info.json
''')
        self.assert_ok(result)
        items = self.input_info(self.root / "custom/inputs.json")["inputs"]
        self.assertCountEqual([item["dataset_id"] for item in items],
                              ["declared", "command-parameters", "later"])
        parameters = next(item for item in items if item["dataset_id"] == "command-parameters")
        self.assertEqual(parameters["result_exp"], "Sample")

    def test_sender_omits_old_and_unbound_inputs_and_handles_large_records(self):
        self.assert_ok(self.run_shell('''
bk_run --log old.log --parameter-input -- printf old
bk_emit_result --from-log old.log --exp Old --fom 1 > results/result
'''))
        self.assert_ok(self.run_shell('''
bk_run --log current.log --parameter-input -- printf current
bk_emit_result --from-log current.log --exp Current --fom 1 > results/result
bk_run --log unbound.log --parameter-input -- printf unbound
'''))
        for path in (self.root / "results").glob("workflow_timing_*.json"):
            record = json.loads(path.read_text())
            if record["exp"] == "Current":
                record["inputs"][0]["arguments"] = ["x" * 200000]
                path.write_text(json.dumps(record))
        before = {p.name: p.read_bytes() for p in (self.root / "results").glob("*.json")}
        item, = self.input_info()["inputs"]
        self.assertEqual(item["result_exp"], "Current")
        self.assertEqual(item["arguments"], ["x" * 200000])
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / "results").glob("*.json")})

    def test_missing_input_is_recorded_without_stopping_launch_and_arguments_are_opt_in(self):
        result = self.run_shell('''
bk_run --log fail.log --input-file missing -- touch launched
test -e launched
bk_emit_result --from-log fail.log --exp Missing --fom 2 > results/result
bk_run --log out.log -- printf '%s' do-not-publish
bk_emit_result --from-log out.log --exp Sample --fom 1 >> results/result
''')
        self.assert_ok(result)
        item = self.input_info()["inputs"][0]
        self.assertEqual(item["collection_status"], "unavailable")
        self.assertEqual(item["result_exp"], "Missing")
        self.assertNotIn("content_digest", item)
        for path in (self.root / "results").glob("*.json"):
            self.assertNotIn("do-not-publish", path.read_text())

    def test_unavailable_input_collector_does_not_mask_application_failure(self):
        self.env["PYTHON_BIN"] = "/nonexistent/python"
        result = self.run_shell('''
status=0
bk_run --log failed.log --input-file missing -- bash -c 'echo launched; exit 23' || status=$?
test "$status" -eq 23
grep -q launched failed.log
''')
        self.assert_ok(result)
        path, = (self.root / "results").glob("workflow_timing_*.json")
        record = json.loads(path.read_text())
        self.assertEqual(record["inputs"][0]["observation_capture"]["collection_status"], "unavailable")
        self.assertEqual(record["stages"][0]["exit_code"], 23)
        self.assertFalse((self.root / "results/result").exists())

    def test_retained_logs_follow_each_input_even_when_fom_extraction_fails(self):
        (self.root / "application.sh").write_text('''
set -euo pipefail
source "$TEST_REPO/scripts/bk_functions.sh"
printf first > input
bk_run --log solver.log --input-file input -- bash -c 'echo first-output; exit 23' || :
printf second > input
bk_run --log solver.log --input-file input -- echo second-output
exit 17
''')
        result = self.run_shell('bash "$TEST_REPO/scripts/run_benchmark.sh" application.sh')
        self.assertEqual(result.returncode, 17, result.stderr)
        execution = json.loads((self.root / "results/execution.json").read_text())
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(execution["exit_code"], 17)
        self.assertFalse((self.root / "results/result").exists())
        records = list((self.root / "results").glob("workflow_timing_*.json"))
        self.assertEqual(len(records), 2)
        expected = {hashlib.sha256(content).hexdigest(): (text, code) for content, text, code in
                    [(b"first", "first-output", 23), (b"second", "second-output", 0)]}
        for path in records:
            record = json.loads(path.read_text())
            stage, = record["stages"]
            text, code = expected[record["inputs"][0]["observation_capture"]["manifest"]["files"][0]["sha256"]]
            self.assertEqual(stage["exit_code"], code)
            scope = path.stem.removeprefix("workflow_timing_")
            log = self.root / "results" / f"execution-output_{scope}_{stage['id']}.log"
            self.assertEqual(log.read_text().strip(), text)

    def test_rejected_launch_does_not_retain_previous_output_as_new_evidence(self):
        result = self.run_shell('''
bk_run --log solver.log -- echo previous-output
_bk_clock_sample() { return 1; }
if bk_run --log solver.log --elapsed seconds -- touch launched; then exit 1; fi
test ! -e launched
''')
        self.assert_ok(result)
        records = list((self.root / "results").glob("workflow_timing_*.json"))
        self.assertEqual(len(records), 2)
        self.assertEqual(len(list((self.root / "results").glob("execution-output_*.log"))), 1)
        for path in records:
            stage, = json.loads(path.read_text())["stages"]
            scope = path.stem.removeprefix("workflow_timing_")
            log = self.root / "results" / f"execution-output_{scope}_{stage['id']}.log"
            self.assertEqual(log.exists(), stage["status"] == "completed")

    def test_failed_new_recorder_cannot_publish_previous_session(self):
        self.assert_ok(self.run_shell('''
bk_run --log old.log -- true
bk_emit_result --from-log old.log --exp Old --fom 1 > results/result
'''))
        result = self.run_shell('''
bash() {
  local arg
  if [[ "$1" == */profiling/workflow_timing.sh ]]; then
    for arg in "$@"; do [ "$arg" != start ] || return 9; done
  fi
  command bash "$@"
}
bk_run --log current.log -- true
bash "$TEST_REPO/scripts/result_server/workflow_timing.sh" --results-dir results manifest > manifest.json
''')
        self.assert_ok(result)
        self.assertEqual(json.loads((self.root / "manifest.json").read_text())["observations"], [])

    def test_log_destination_survives_a_shell_function_changing_directory(self):
        result = self.run_shell('''
change_directory() {
  mkdir -p work
  cd work
  printf 'command output\n'
}
bk_run --log output.log -- change_directory
test ! -e output.log
grep -q 'command output' ../output.log
''')
        self.assert_ok(result)

    def test_diagnostics_have_a_byte_limit_as_well_as_a_line_limit(self):
        (self.root / "large.log").write_bytes(b"x" * 100000)
        result = self.run_shell("bk_diagnose_log large.log")
        self.assert_ok(result)
        self.assertLess(len(result.stderr), 20000)

    def test_required_elapsed_failure_stops_before_launch(self):
        result = self.run_shell('''
duration=old
status=0
_bk_clock_sample() { return 1; }
bk_run --elapsed duration -- touch must-not-run || status=$?
test "$status" -ne 0
test -z "$duration"
test ! -e must-not-run
''')
        self.assert_ok(result)

    def test_required_elapsed_finish_failure_cannot_reuse_old_value(self):
        result = self.run_shell('''
bash() {
  local arg
  if [[ "$1" == */profiling/workflow_timing.sh ]]; then
    for arg in "$@"; do [ "$arg" != finish ] || return 9; done
  fi
  command bash "$@"
}
duration=old
status=0
bk_run --elapsed duration -- true || status=$?
test "$status" -ne 0
test -z "$duration"
status=0
bk_run --elapsed duration -- bash -c 'exit 23' || status=$?
test "$status" -eq 23
''')
        self.assert_ok(result)

    def test_output_collection_failure_preserves_command_failure(self):
        result = self.run_shell('''
bash() {
  if [[ "$1" == */run_output.sh && "$2" == collect ]]; then
    return 9
  fi
  command bash "$@"
}
for expected in 0 23; do
  status=0
  bk_run --log failure.log -- bash -c 'exit "$1"' bash "$expected" || status=$?
  if [ "$expected" -eq 0 ]; then
    test "$status" -ne 0
  else
    test "$status" -eq "$expected"
  fi
done
''')
        self.assert_ok(result)

    def test_lqcd_and_genesis_use_the_invocation_log(self):
        (self.root / "scripts").symlink_to(self.repo / "scripts", target_is_directory=True)
        (self.root / "programs").symlink_to(self.repo / "programs", target_is_directory=True)
        (self.root / "artifacts").mkdir()
        (self.root / "bin").mkdir()
        self.env["PATH"] = str(self.root / "bin") + os.pathsep + self.env["PATH"]
        launcher = self.root / "bin/mpiexec"
        launcher.write_text('''#!/bin/sh
printf 'Elapsed time: Spectrum_Domainwall_alt.hadron_2ptFunction: total 12 sec\nsolver performance:\nsolver = 2 sec\ndynamics = 3.5\n' > stdout.17.0
printf 'launcher warning\n' >&2
''')
        launcher.chmod(0o700)
        lqcd = self.root / "LQCD_dw_solver/run"
        lqcd.mkdir(parents=True)
        (lqcd / "main_template.yaml").write_text("xxx_lattice_size_xxx\n")
        (self.root / "artifacts/bridge.elf").touch()
        (lqcd / "stdout.1.0").write_text("old result\n")
        result = self.run_shell('bash programs/LQCD_dw_solver/run.sh Fugaku 1 1 1')
        self.assert_ok(result)
        self.assertIn("FOM:", (self.root / "results/result").read_text())
        self.assertNotIn("old result", (lqcd / "run.log").read_text())

        source = self.root / "genesis_benchmark_input"
        work = source / "npt/genesis2.0beta_3.5fs/apoa1"
        work.mkdir(parents=True)
        (work / "p8.inp").write_text("../../../inputs/apoa1/\n")
        (work / "stdout.1.0").write_text("dynamics = 999\n")
        inputs = source / "inputs/apoa1"
        inputs.mkdir(parents=True)
        for name in ("top_all27_prot_lipid.rtf", "par_all27_prot_lipid.prm", "apoa1.psf", "apoa1.pdb", "apoa1.rst"):
            (inputs / name).touch()
        (source / ".git").mkdir()
        (source / ".git/config").touch()
        git = self.root / "bin/git"
        git.write_text("#!/bin/sh\nprintf '%040d\\n' 1\n")
        git.chmod(0o700)
        (self.root / "artifacts/spdyn").touch()
        result = self.run_shell('bash programs/genesis/run.sh Fugaku 1 1 1')
        self.assert_ok(result)
        self.assertNotIn("999", (self.root / "results/log_p8.txt").read_text())
        self.assertIn("dynamics = 3.5", (self.root / "results/log_p8.txt").read_text())

    def test_qws_flow2_build_and_run_routes(self):
        (self.root / "scripts").symlink_to(self.repo / "scripts", target_is_directory=True)
        (self.root / "programs").symlink_to(self.repo / "programs", target_is_directory=True)
        work = self.root / "qws"
        work.mkdir()
        (self.root / "bin").mkdir()
        commands = {
            "git": "printf '%040d\\n' 1",
            "sleep": ":", "sync": ":",
            "module": 'printf "%s\\n" "$*" >> ../modules.log',
            "make": 'printf "%s\\n" "$@" > ../make.args; printf executable > main',
            "mpirun": '''printf '%s\\n' "$@" > ../mpi.args
printf '%s\\n' "$OMP_NUM_THREADS" > ../threads
[ "${FAIL_MPI:-0}" != 1 ] || exit 7
printf 'etime for solver = 2.5\\netime for solver = 1.5\\n'
''',
        }
        for name, code in commands.items():
            path = self.root / "bin" / name
            path.write_text("#!/bin/sh\n" + code + "\n")
            path.chmod(0o700)
        check = work / "check.sh"
        check.write_text('''#!/bin/sh
[ "${FAIL_CHECK:-0}" != 1 ] || exit 8
[ "$2" = data/CASE0 ] && grep -q "etime for solver" "$1"
''')
        check.chmod(0o700)
        self.env["PATH"] = str(self.root / "bin") + os.pathsep + self.env["PATH"]
        self.env["QWS_PROFILER_TOOL"] = "none"
        for system in ("Flow2_Type1", "Flow2_Type2"):
            with self.subTest(system=system):
                modules = self.root / "modules.log"
                modules.unlink(missing_ok=True)
                self.assert_ok(self.run_shell(f"bash programs/qws/build.sh {system}"))
                self.assertTrue((self.root / "artifacts/main").is_file())
                build_modules = modules.read_text().splitlines()
                self.assertEqual(build_modules[0], "purge")
                make_args = (self.root / "make.args").read_text().splitlines()
                self.assertIn("mpi=1", make_args)
                self.assertIn("omp=1", make_args)
                if system == "Flow2_Type1":
                    self.assertIn("compiler=intel", make_args)
                    flags = next(arg for arg in make_args if arg.startswith("CFLAGS="))
                    self.assertIn("-march=", flags)
                    self.assertNotIn("-xCORE", flags)
                else:
                    self.assertIn("arch=grace", make_args)
                    self.assertIn("CXX=mpic++ -mp", make_args)
                modules.unlink()
                # A synthetic thread count checks forwarding without fixing list.csv policy.
                self.assert_ok(self.run_shell(f"bash programs/qws/run.sh {system} 1 1 3"))
                self.assertEqual(modules.read_text().splitlines(), build_modules)
                args = (self.root / "mpi.args").read_text().splitlines()
                self.assertEqual(args[:2], ["-n", "1"])
                if system == "Flow2_Type2":
                    self.assertIn("ppr:1:node:PE=3", args)
                self.assertEqual((self.root / "threads").read_text().strip(), "3")
                result_file = self.root / "results/result"
                self.assertIn("FOM:", result_file.read_text())
                self.assertIn("Exp:CASE0", result_file.read_text())
                for failure in ("FAIL_MPI", "FAIL_CHECK"):
                    self.env[failure] = "1"
                    result = self.run_shell(f"bash programs/qws/run.sh {system} 1 1 3")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("FOM:", result_file.read_text())
                    del self.env[failure]
                for nodes, ranks in ((2, 1), (1, 2)):
                    (self.root / "mpi.args").unlink(missing_ok=True)
                    result = self.run_shell(f"bash programs/qws/run.sh {system} {nodes} {ranks} 3")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("one node and one MPI rank", result.stderr)
                    self.assertFalse((self.root / "mpi.args").exists())
                    self.assertNotIn("FOM:", result_file.read_text())

    def test_qws_does_not_depend_on_scheduler_output_sequence_numbers(self):
        (self.root / "scripts").symlink_to(self.repo / "scripts", target_is_directory=True)
        (self.root / "programs").symlink_to(self.repo / "programs", target_is_directory=True)
        (self.root / "artifacts").mkdir()
        (self.root / "artifacts/main").touch()
        work = self.root / "qws"
        work.mkdir()
        (work / "output.old/0/1").mkdir(parents=True)
        (work / "output.old/0/1/stdout.1.0").write_text("stale result\n")
        (self.root / "bin").mkdir()
        commands = {
            "git": "printf '%040d\\n' 1",
            "sleep": ":", "sync": ":",
            "mpiexec": '''mkdir -p output.sample/0/17
printf 'etime for solver = 2.5\netime for solver = 1.5\n' > output.sample/0/17/stdout.17.0
''',
        }
        for name, code in commands.items():
            path = self.root / "bin" / name
            path.write_text("#!/bin/sh\n" + code + "\n")
            path.chmod(0o700)
        check = work / "check.sh"
        check.write_text('#!/bin/sh\ngrep -q "etime for solver" "$1"\n')
        check.chmod(0o700)
        self.env["PATH"] = str(self.root / "bin") + os.pathsep + self.env["PATH"]
        self.env["QWS_PROFILER_TOOL"] = "none"
        result = self.run_shell('bash programs/qws/run.sh Fugaku 1 1 1')
        self.assert_ok(result)
        self.assertIn("FOM:", (self.root / "results/result").read_text())
        self.assertNotIn("stale result", (work / "CASE0").read_text())
        self.assertNotIn("stale result", (work / "CASE1").read_text())

        profiler = self.root / "bin/fapp"
        profiler.write_text('''#!/bin/sh
if [ "$1" = -A ]; then printf 'summary\\n'; exit 0; fi
while [ "$#" -gt 0 ]; do
  case "$1" in
    -C|-Hevent=*) shift ;;
    -d) mkdir -p "$2"; printf observed > "$2/counters"; shift 2 ;;
    *) break ;;
  esac
done
exec "$@"
''')
        profiler.chmod(0o700)
        self.env["QWS_PROFILER_TOOL"] = "fapp"
        self.env["QWS_PROFILER_LEVEL"] = "single"
        result = self.run_shell('''
bash programs/qws/run.sh Fugaku 1 1 1
bash "$TEST_REPO/scripts/result_server/workflow_timing.sh" --results-dir results manifest > manifest.json
''')
        self.assert_ok(result)
        observations = json.loads((self.root / "manifest.json").read_text())["observations"]
        documents = {item["result_exp"]: json.loads((self.root / item["artifact"]["path"]).read_text())
                     for item in observations}
        self.assertEqual(set(documents), {"CASE0", "CASE1"})
        self.assertTrue(any(stage["tool"] == "fapp" and stage["stage"] == "collect"
                            for stage in documents["CASE0"]["stages"]))
        self.assertTrue(all(stage["stage"] == "benchmark" for stage in documents["CASE1"]["stages"]))
        self.assertTrue(list((self.root / "results").glob("profile_*/profile.tgz")))
        self.assert_ok(self.run_shell('''
bash "$TEST_REPO/scripts/result_server/workflow_timing.sh" --results-dir results publish-primary --exp CASE0 --destination padata0.tgz
'''))
        self.assertTrue((self.root / "results/padata0.tgz").is_file())
        self.assert_ok(self.run_shell('''
touch results/padata1.tgz
bash "$TEST_REPO/scripts/result.sh" qws SampleSystem cross build run 42 > conversion.log
test ! -f results/padata1.tgz
'''))
        first = json.loads((self.root / "results/result0.json").read_text())
        second = json.loads((self.root / "results/result1.json").read_text())
        self.assertEqual(first["profile_data"]["tool"], "fapp")
        self.assertNotIn("profile_data", second)

    def test_ffb_and_scale_keep_domain_parsing_and_elapsed_fom(self):
        (self.root / "scripts").symlink_to(self.repo / "scripts", target_is_directory=True)
        (self.root / "artifacts/bin").mkdir(parents=True)
        (self.root / "bin").mkdir()
        for name, code in {
            "module": ":",
            "mpiexec": '''mkdir -p output.sample/0/17
printf ' 1 USRT:TIME-LOOP 1.25\\n' > output.sample/0/17/stdout.17.0
''',
        }.items():
            path = self.root / "bin" / name
            path.write_text("#!/bin/sh\n" + code + "\n")
            path.chmod(0o700)
        self.env["PATH"] = str(self.root / "bin") + os.pathsep + self.env["PATH"]
        archive = self.root / "input.tar.gz"
        with tarfile.open(archive, "w:gz"):
            pass
        for name in ("les3x.mpi", "bin/scale-rm_pp_ens", "bin/scale-rm_init_ens", "bin/scale-rm_ens", "bin/letkf"):
            (self.root / "artifacts" / name).touch()
        template = self.root / "artifacts/test/benchmark.RC_GH200_128x128"
        (template / "bin").mkdir(parents=True)
        (template / "prep.sh").write_text(":\n")
        (self.root / "artifacts/setup-env.RC_GH200.sh").write_text(":\n")
        for name, system, variables in (
            ("ffb", "FugakuCN", "INPUT_ARCHIVE_CPU"),
            ("scale-letkf", "RC_GH200", "SCALE_DATABASE|SCALE_TESTDATA"),
        ):
            with self.subTest(app=name):
                app = self.root / "programs" / name
                app.mkdir(parents=True)
                shutil.copyfile(self.repo / "programs" / name / "run.sh", app / "run.sh")
                # Substitute only fixture input locations, leaving executable logic intact.
                script = (app / "run.sh").read_text()
                script = re.sub(rf'^(\s*(?:{variables})=).*$',
                                lambda match: match[1] + '"' + str(archive) + '"', script, flags=re.M)
                (app / "run.sh").write_text(script)
                result = self.run_shell(f'bash programs/{name}/run.sh {system} 1 1 1')
                self.assert_ok(result)
                self.assertIn("FOM:", (self.root / "results/result").read_text())


if __name__ == "__main__":
    unittest.main()
