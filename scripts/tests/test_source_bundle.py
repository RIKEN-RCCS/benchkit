"""Build/cache/run handoff with a local Git fixture and synthetic tools only."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class SourceBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[2]
        self.source = self.root / "origin.git"
        self.source.mkdir()
        self.git("init", "-q", "-b", "main")
        files = {
            "run/main_template.yaml": "xxx_lattice_size_xxx\nxxx_grid_size_xxx\nxxx_number_of_thread_xxx\n",
            "run/test_alt_Spectrum_Domainwall_5din_Hadron2ptFunction.yaml": "gauge: ../conf_04040408.txt\n",
            "conf_04040408.txt": "synthetic gauge data\n",
            "src/lib_alt_Accel/init_alt_Accel.cpp": "keep\nDeviceManager_CUDA::init_prempi();\n",
            "src/lib_alt_Accel/ResourceManager/deviceManager_CUDA.h": "synthetic header\n",
            "Makefile_target.inc": "compiler = FCCpx\n",
            "benchmark/domainwall/Makefile": "synthetic build\n",
        }
        for variant in ("fugaku_acle", "simd_avx512", "openacc", "cuda"):
            files[f"Makefile_{variant}"] = f"variant = {variant}\nuse_device_arch = auto\n"
        for name, value in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.tools = self.root / "bin"
        self.tools.mkdir()
        self.tool("module", ":")
        self.tool("make", '''
if [ "${1:-}" = --version ]; then echo 'synthetic make'; exit 0; fi
printf '%s|%s\\n' "$PWD" "$*" >> "$TEST_TRACE"
if [ "$(basename "$PWD")" = domainwall ]; then
  if [ "${1:-}" = clean ]; then rm -f bridge.elf; exit 0; fi
  variant=$(awk '$1 == "variant" {print $3}' ../../Makefile)
  printf '#!/bin/bash\\nvariant=%q\\n' "$variant" > bridge.elf
  cat "$TEST_BINARY" >> bridge.elf
  chmod +x bridge.elf
else
  variant=$(awk '$1 == "variant" {print $3}' Makefile)
  [ "$variant" != "${TEST_BUILD_FAIL:-}" ] || exit 17
  mkdir -p build
fi
''')
        self.tool("mpirun", '''
for argument in "$@"; do
  case "$argument" in ./bridge*.elf) exec "$argument" ;; esac
done
exit 99
''')
        (self.tools / "mpiexec").symlink_to("mpirun")
        self.binary = self.root / "binary-body"
        self.binary.write_text('''
test -f ../conf_04040408.txt || exit 90
test -f test_alt_Spectrum_Domainwall_5din_Hadron2ptFunction.yaml || exit 91
if grep -q xxx_ main.yaml; then exit 92; fi
residual=1e-27
if [ "$variant" = "${TEST_BAD_VARIANT:-}" ]; then residual=1e-25; fi
for iteration in {1..12}; do echo "Richardson  nconv a b c d $residual"; done
echo 'Elapsed time: Spectrum_Domainwall_alt.hadron_2ptFunction: total 12 sec'
printf 'solver performance:\\nsolver = 2 sec\\n'
''')
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("BK_", "_BK_", "LQCD_DW_"))}
        self.env.update(PATH=str(self.tools) + os.pathsep + self.env["PATH"],
                        LQCD_DW_SOLVER_REPO_URL=str(self.source),
                        TEST_BINARY=str(self.binary), TEST_TRACE=str(self.root / "make.trace"),
                        BK_BUILD_CACHE_DIR=str(self.root / "cache"), BK_BUILD_CACHE_ENV_KEY="fixture")
        self.work = self.workspace("first")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.source), *args], text=True,
                              capture_output=True, check=True, timeout=20)

    def tool(self, name, body):
        path = self.tools / name
        path.write_text("#!/bin/bash\nset -e\n" + body + "\n")
        path.chmod(0o755)

    def workspace(self, name):
        path = self.root / name
        path.mkdir()
        for directory in ("scripts", "programs"):
            (path / directory).symlink_to(self.repo / directory, target_is_directory=True)
        return path

    def shell(self, code, expected=0, work=None):
        result = subprocess.run(["bash", "-c", code], cwd=work or self.work,
                                env=self.env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def build(self, system="RIKYU", expected=0, cache=False, work=None):
        entry = ("scripts/build_with_cache.sh LQCD_dw_solver " + system + " programs/LQCD_dw_solver"
                 if cache else "programs/LQCD_dw_solver/build.sh " + system)
        return self.shell("bash " + entry, expected, work)

    def run_app(self, expected=0, work=None):
        return self.shell("bash scripts/run_benchmark.sh programs/LQCD_dw_solver/run.sh RIKYU 1 1 2",
                          expected, work)

    def provenance(self, work=None):
        return json.loads(((work or self.work) / "artifacts/runtime/build.json").read_text())

    def offline(self):
        self.source.rename(self.root / "origin-unavailable")
        self.tool("git", '''
case " $* " in *" rev-parse "*) printf '%040d\\n' 1 ;;
  *) echo 'run attempted Git access' >&2; exit 99 ;;
esac
''')

    def test_offline_run_uses_exact_build_payload_and_retains_old_tree(self):
        old = self.work / "LQCD_dw_solver"
        old.mkdir()
        (old / "sentinel").write_text("do not touch")
        self.build()
        record = self.provenance()
        change, = record["adjustments"]
        self.assertEqual(change["status"], "applied")
        self.assertNotEqual(change["before_sha256"], change["after_sha256"])
        self.assertEqual([item["label"] for item in record["variants"]], ["openacc", "cuda"])
        for item in record["variants"]:
            self.assertEqual(item["exit_code"], 0)
            binary = self.work / "artifacts/runtime/payload" / item["binary"]
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), item["binary_sha256"])
            config, = [entry for entry in item["configuration"] if entry["path"] == "Makefile"]
            self.assertIn(f'variant = {item["label"]}', config["content"])
            self.assertIn("blackwell", config["content"])
            self.assertIn("DeviceManager_CUDA", item["source_diff"])
        self.offline()
        self.run_app()
        self.assertEqual((old / "sentinel").read_text(), "do not touch")
        self.assertEqual((self.work / "results/result").read_text().count("FOM:12"), 2)
        self.assertEqual(json.loads((self.work / "results/build_provenance.json").read_text()), record)
        self.shell("bash scripts/result.sh LQCD_dw_solver RIKYU native build run 123")
        result = json.loads((self.work / "results/result0.json").read_text())
        self.assertEqual(result["source_info"]["commit_hash"], self.commit)
        self.assertEqual(result["source_info"]["repo_url"], str(self.root / "origin.git"))
        summary = result["source_info"]["build"]
        self.assertEqual(summary["variants"][0]["binary_sha256"], record["variants"][0]["binary_sha256"])
        self.assertNotIn("source_diff", summary["variants"][0])
        self.assertNotIn("content", summary["variants"][0]["configuration"][0])
        self.assertEqual(summary["record_sha256"],
                         hashlib.sha256((self.work / "results/build_provenance.json").read_bytes()).hexdigest())

    def test_cache_restores_payload_and_provenance_without_rebuilding(self):
        self.build(cache=True)
        first = self.provenance()
        trace = (self.root / "make.trace").read_text()
        second = self.workspace("second")
        self.build(cache=True, work=second)
        self.assertIn("BK_BUILD_CACHE_STATUS=hit", (second / "results/build_cache.env").read_text())
        self.assertEqual((self.root / "make.trace").read_text(), trace)
        self.assertEqual(self.provenance(second), first)
        self.assertEqual((self.work / "artifacts/runtime/inventory").read_bytes(),
                         (second / "artifacts/runtime/inventory").read_bytes())
        self.offline()
        self.run_app(work=second)
        self.assertEqual((second / "results/result").read_text().count("FOM:12"), 2)

    def test_source_override_changes_cache_identity(self):
        self.build(cache=True)
        trace = (self.root / "make.trace").read_text()
        second = self.workspace("new-url")
        other_source = self.root / "alternate.git"
        shutil.copytree(self.source, other_source)
        self.env["LQCD_DW_SOLVER_REPO_URL"] = str(other_source)
        self.build(cache=True, work=second)
        self.assertIn("BK_BUILD_CACHE_STATUS=miss", (second / "results/build_cache.env").read_text())
        self.assertNotEqual((self.root / "make.trace").read_text(), trace)
        self.shell('source scripts/bk_build.sh; test "$(bk_env_file_value results/source_info.env BK_REPO_URL)" = "$LQCD_DW_SOLVER_REPO_URL"', work=second)

    def test_pinned_source_cache_survives_branch_movement_and_override_misses(self):
        self.env["LQCD_DW_SOLVER_SOURCE_COMMIT"] = self.commit
        self.build(cache=True)
        trace = (self.root / "make.trace").read_text()
        (self.source / "conf_04040408.txt").write_text("new gauge\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "next")
        second = self.workspace("same-pin")
        self.build(cache=True, work=second)
        self.assertIn("BK_BUILD_CACHE_STATUS=hit", (second / "results/build_cache.env").read_text())
        self.assertEqual((self.root / "make.trace").read_text(), trace)
        self.env["LQCD_DW_SOLVER_SOURCE_COMMIT"] = self.git("rev-parse", "HEAD").stdout.strip()
        third = self.workspace("new-pin")
        self.build(cache=True, work=third)
        self.assertIn("BK_BUILD_CACHE_STATUS=miss", (third / "results/build_cache.env").read_text())
        self.assertEqual((third / "artifacts/runtime/payload/conf_04040408.txt").read_text(), "new gauge\n")

    def test_corrupt_cache_is_rebuilt_instead_of_used(self):
        self.build(cache=True)
        cached = self.root / "cache/LQCD_dw_solver/RIKYU/artifacts/runtime/payload/conf_04040408.txt"
        cached.unlink()
        second = self.workspace("after-corruption")
        self.build(cache=True, work=second)
        self.assertIn("BK_BUILD_CACHE_STATUS=miss", (second / "results/build_cache.env").read_text())
        self.assertTrue((second / "artifacts/runtime/payload/conf_04040408.txt").is_file())

    def test_fixed_upstream_records_unchanged_adjustment_and_pinned_commit(self):
        file = self.source / "src/lib_alt_Accel/init_alt_Accel.cpp"
        file.write_text("keep\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixed")
        self.env["LQCD_DW_SOLVER_SOURCE_COMMIT"] = self.git("rev-parse", "HEAD").stdout.strip()
        self.build()
        self.assertEqual(self.provenance()["adjustments"][0]["status"], "unchanged")

    def test_compilation_failure_keeps_record_and_does_not_publish_partial_payload(self):
        self.build()
        self.env["TEST_BUILD_FAIL"] = "cuda"
        self.build(expected=17)
        self.assertFalse((self.work / "artifacts/runtime").exists())
        record = json.loads((self.work / "results/build_provenance.json").read_text())
        self.assertEqual([entry["exit_code"] for entry in record["variants"]], [0, 17])
        self.assertEqual(len(list(self.work.glob(".source-build.*/previous-runtime"))), 1)

    def test_callbacks_keep_app_variables_visible(self):
        self.shell('''set -e
source scripts/bk_build.sh
bk_build_source "$LQCD_DW_SOLVER_REPO_URL" main
cd "$BK_SOURCE_DIR"
file=app-file binary=app-binary status=app-status label=app-label
check_app_variables() {
  [ "$file" = app-file ] && [ "$binary" = app-binary ] &&
    [ "$status" = app-status ] && [ "$label" = app-label ]
}
compile_app() {
  check_app_variables || return 23
  printf '#!/bin/bash\\nexit 0\\n' > benchmark/domainwall/bridge.elf
  chmod +x benchmark/domainwall/bridge.elf
}
bk_source_adjustment demo reason Makefile_target.inc check_app_variables
bk_build_binary demo benchmark/domainwall/bridge.elf run/app --config Makefile_target.inc -- compile_app
bk_publish_runtime run conf_04040408.txt
check_app_variables
''')
        record = self.provenance()
        self.assertEqual(record["adjustments"][0]["status"], "unchanged")
        self.assertEqual(record["variants"][0]["exit_code"], 0)

    def test_failed_adjustment_is_recorded_without_publication(self):
        self.shell('''set -e
source scripts/bk_build.sh
bk_build_source "$LQCD_DW_SOLVER_REPO_URL" main
cd "$BK_SOURCE_DIR"
bk_source_adjustment demo reason Makefile_target.inc bash -c 'exit 19'
''', 19)
        record = json.loads((self.work / "results/build_provenance.json").read_text())
        self.assertEqual(record["adjustments"][0]["exit_code"], 19)
        self.assertEqual(record["adjustments"][0]["status"], "failed")
        self.assertFalse((self.work / "artifacts/runtime").exists())

    def test_runtime_rejects_changed_missing_extra_and_linked_payloads(self):
        self.build()
        original = self.work / "artifacts/runtime"
        for mode in ("changed", "missing", "extra", "link"):
            with self.subTest(mode=mode):
                work = self.workspace(mode)
                package = work / "artifacts/runtime"
                shutil.copytree(original, package)
                gauge = package / "payload/conf_04040408.txt"
                if mode == "changed": gauge.write_text("changed")
                elif mode == "missing": gauge.unlink()
                elif mode == "extra": (package / "payload/extra").touch()
                else:
                    gauge.unlink()
                    gauge.symlink_to(original / "payload/conf_04040408.txt")
                self.run_app(1, work)
                execution = json.loads((work / "results/execution.json").read_text())
                self.assertEqual(execution["status"], "failed")
                self.assertEqual((work / "results/result").read_text(), "")

    def test_invalid_numerical_result_keeps_first_fom_and_execution_failure(self):
        self.build()
        self.env["TEST_BAD_VARIANT"] = "cuda"
        self.run_app(2)
        output = (self.work / "results/result").read_text()
        self.assertEqual(output.count("FOM:12"), 1)
        self.assertIn("Exp:total_OpenACC", output)
        execution = json.loads((self.work / "results/execution.json").read_text())
        self.assertEqual(execution["exit_code"], 2)

    def test_compute_paths_work_without_python_or_jq(self):
        tools = self.root / "shell-only-tools"
        tools.mkdir()
        for tool in ("bash", "sh", "git", "awk", "sed", "grep", "cp", "mv", "rm", "chmod",
                     "mkdir", "mktemp", "dirname", "basename", "find", "sort", "stat", "sha256sum",
                     "cat", "tr", "cmp", "base64", "date", "tee", "flock", "head", "tail",
                     "dd", "od", "realpath", "wc", "cut", "touch", "readlink"):
            (tools / tool).symlink_to(shutil.which(tool))
        self.env["PATH"] = str(self.tools) + os.pathsep + str(tools)
        self.shell("! command -v python3 && ! command -v jq")
        self.build()
        self.offline()
        self.run_app()

    def test_result_rejects_mismatched_build_provenance(self):
        self.build()
        self.run_app()
        path = self.work / "results/build_provenance.json"
        record = json.loads(path.read_text())
        record["source_info_sha256"] = "0" * 64
        path.write_text(json.dumps(record))
        self.shell("bash scripts/result.sh LQCD_dw_solver RIKYU native build run 123", 1)
        self.assertFalse((self.work / "results/.complete").exists())

    def test_all_existing_build_configurations(self):
        for system, labels, arch in (
            ("Fugaku", ["fugaku_acle"], "auto"), ("FugakuCN", ["fugaku_acle"], "auto"),
            ("MiyabiC", ["simd_avx512"], "auto"), ("AVX512", ["simd_avx512"], "auto"),
            ("MiyabiG", ["openacc", "cuda"], "hopper"),
            ("OpenACC", ["openacc"], "auto"), ("CUDA", ["cuda"], "auto"),
        ):
            with self.subTest(system=system):
                work = self.workspace(system)
                self.build(system, work=work)
                record = self.provenance(work)
                self.assertEqual([item["label"] for item in record["variants"]], labels)
                for item in record["variants"]:
                    config, = [entry for entry in item["configuration"] if entry["path"] == "Makefile"]
                    self.assertIn(f"use_device_arch = {arch}", config["content"])
                    self.assertEqual(hashlib.sha256(config["content"].encode()).hexdigest(), config["sha256"])
                if system == "FugakuCN":
                    config, = [entry for entry in record["variants"][0]["configuration"]
                               if entry["path"] == "Makefile_target.inc"]
                    self.assertIn("compiler = FCC\n", config["content"])


if __name__ == "__main__":
    unittest.main()
