#!/usr/bin/env python3
"""Synthetic input collection contracts; no application dataset constants."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
REPO = Path(__file__).resolve().parents[2]


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def input_info(root):
    result = subprocess.run(["bash", str(REPO / "scripts/result_server/input_info.sh"),
                             "--results-dir", str(root / "results")],
                            env={k: v for k, v in os.environ.items() if not k.startswith(("BK_", "_BK_"))},
                            text=True, capture_output=True, timeout=15, check=True)
    return json.loads(result.stdout)


def run_collection(root, *args, env=None, metadata_output=None):
    env = {k: v for k, v in (env or os.environ).items() if not k.startswith(("BK_", "_BK_"))}
    if metadata_output is not None:
        env["BK_INPUT_INFO_FILE"] = str(metadata_output)
    return subprocess.run(["bash", "-c", '''
set -e
source "$1/scripts/bk_functions.sh"
shift
bk_record_input --dataset-id demo "$@"
''', "collect", str(REPO), *map(str, args)],
        cwd=root, env=env, text=True, capture_output=True, timeout=15)


def observed(source, kind):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        result = run_collection(root, "--" + kind, source)
        if result.returncode:
            raise AssertionError(result.stderr)
        return input_info(root)["inputs"][0]


class InputManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "nested").mkdir()
        (self.source / "nested" / "wave data").write_bytes(b"abc")
        (self.source / "config").write_bytes(b"config")

    def run_cli(self, *args):
        result = run_collection(self.root, *args)
        if result.returncode == 0:
            result.stdout = json.dumps(input_info(self.root)["inputs"][0])
        return result

    def assert_unavailable(self, *args, reference=False):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)
        self.assertEqual(item["verification_status"], "unavailable")
        if reference:
            self.assertEqual(item["collection_status"], "recorded")
            self.assertIn("reference_error", item)
        else:
            self.assertEqual(item["collection_status"], "unavailable")
            self.assertNotIn("content_digest", item)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)

    def test_directory_identity_is_independent_of_location_and_mtime(self):
        copied = self.root / "copied"
        shutil.copytree(self.source, copied)
        os.utime(copied / "config", (1, 1))
        first = observed(self.source, "directory")
        second = observed(copied, "directory")
        self.assertEqual(first["manifest_digest"], second["manifest_digest"])
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(first["size_bytes"], len(b"abcconfig"))
        self.assertEqual(first["file_count"], 2)
        self.assertEqual(first["verification_status"], "declared")
        self.assertNotIn(str(self.root), json.dumps(first))
        (copied / "config").write_bytes(b"Config")
        changed = observed(copied, "directory")
        self.assertNotEqual(first["content_digest"], changed["content_digest"])

    def test_compute_capture_without_python_jq_or_curl_preserves_identity(self):
        commands = self.root / "bin"
        commands.mkdir()
        for name in ("bash", "dirname", "basename", "realpath", "mktemp", "rm", "mkdir", "stat", "find", "head",
                     "sort", "sha256sum", "dd", "tee", "wc", "mkfifo", "cmp", "date", "awk", "tr",
                     "cp", "mv", "cat", "flock", "od", "sed", "cut"):
            (commands / name).symlink_to(shutil.which(name))
        env = dict(os.environ, PATH=str(commands), PYTHON_BIN="/unavailable/python")
        for name in ('quote"\\line\n\t\x7f', '\u65e5\U0001f600'):
            (self.source / name).write_bytes(b"sample")
        result = run_collection(self.root, "--directory", self.source, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "results/input_info.json").exists(), result.stderr)
        before = (self.root / "results/input_info.json").read_bytes()
        item = input_info(self.root)["inputs"][0]
        self.assertEqual(item["collection_status"], "recorded")
        self.assertEqual(item["file_count"], 4)
        expected = "sha256:" + hashlib.sha256(canonical_json(item["manifest"])).hexdigest()
        self.assertEqual(item["content_digest"], expected)
        self.assertEqual(item["dataset_version"], expected)
        self.assertEqual((self.root / "results/input_info.json").read_bytes(), before)

    def test_file_identity_does_not_include_basename_and_handles_empty_files(self):
        one = self.source / "config"
        two = self.root / "renamed"
        two.write_bytes(one.read_bytes())
        first = observed(one, "file")
        second = observed(two, "file")
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(first["sha256"], hashlib.sha256(b"config").hexdigest())
        self.assertEqual(first["manifest"]["files"][0]["path"], "input")
        two.write_bytes(b"")
        self.assertEqual(observed(two, "file")["sha256"], hashlib.sha256(b"").hexdigest())

    def test_reference_differences_record_actual_content_without_rejection(self):
        original = observed(self.source, "directory")
        expected_file = self.root / "expected.json"
        expected_file.write_bytes(canonical_json(original["manifest"]))
        result = self.run_cli("--directory", self.source, "--expected-manifest", expected_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        verified = json.loads(result.stdout)
        self.assertEqual(verified["verification_status"], "verified")
        self.assertEqual(verified["dataset_version"], original["content_digest"])
        (self.source / "extra").write_bytes(b"extra")
        result = self.run_cli("--directory", self.source, "--expected-manifest", expected_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verification_status"], "mismatch")
        (self.source / "extra").unlink()
        (self.source / "config").write_bytes(b"Config")
        result = self.run_cli("--directory", self.source, "--expected-manifest", expected_file)
        changed = json.loads(result.stdout)
        self.assertEqual(changed["verification_status"], "mismatch")
        self.assertNotEqual(changed["content_digest"], original["content_digest"])
        (self.source / "config").unlink()
        result = self.run_cli("--directory", self.source, "--expected-manifest", expected_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["verification_status"], "mismatch")

    def test_internal_symlinks_match_copied_content(self):
        link = self.source / "link"
        link.symlink_to("nested/wave data")
        first = observed(self.source, "directory")
        link.unlink()
        link.write_bytes(b"abc")
        second = observed(self.source, "directory")
        self.assertEqual(first["manifest_digest"], second["manifest_digest"])
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        self.assertEqual(observed(alias, "directory")["manifest"], second["manifest"])

    def test_unsafe_or_unreadable_inputs_fail_without_location_disclosure(self):
        link = self.source / "link"
        outside = self.root / "outside"
        outside.write_bytes(b"do not read")
        for target in (outside, self.source, self.root / "missing"):
            with self.subTest(target=target.name):
                link.symlink_to(target)
                self.assert_unavailable("--directory", self.source)
                link.unlink()
        os.mkfifo(link)
        self.assert_unavailable("--directory", self.source)
        self.assert_unavailable("--file", link)
        self.assert_unavailable("--file", outside, "--expected-manifest", link, reference=True)
        link.unlink()
        empty = self.root / "empty"
        empty.mkdir()
        self.assert_unavailable("--directory", empty)
        self.assert_unavailable("--file", self.source)
        self.assert_unavailable("--directory", outside)
        self.assert_unavailable("--file", self.root / "missing")

    def test_changes_during_collection_do_not_produce_a_manifest(self):
        commands = self.root / "bin"
        commands.mkdir()
        wrapper = commands / "dd"
        wrapper.write_text('#!/bin/bash\n' + shutil.which("dd") + ' "$@"\n'
                           'printf changed >> "$TEST_INPUT"\n')
        wrapper.chmod(0o700)
        env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
                   TEST_INPUT=str(self.source / "config"))
        result = run_collection(self.root, "--directory", self.source, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        item = input_info(self.root)["inputs"][0]
        self.assertEqual(item["collection_status"], "unavailable")
        self.assertNotIn("content_digest", item)

    def test_manifest_validation_and_limits(self):
        expected = self.root / "expected.json"
        valid = observed(self.source / "config", "file")["manifest"]
        for field, value in (("sha256", "short"), ("size_bytes", True), ("path", "../outside")):
            invalid = {**valid, "files": [{**valid["files"][0], field: value}]}
            expected.write_text(json.dumps(invalid))
            self.assert_unavailable("--file", self.source / "config", "--expected-manifest", expected, reference=True)
        expected.write_text('{"schema_version": 1}')
        self.assert_unavailable("--file", self.source / "config", "--expected-manifest", expected, reference=True)
        deep = self.source
        for _ in range(66):
            deep = deep / "d"
            deep.mkdir()
        self.assert_unavailable("--directory", self.source)

    def test_invalid_utf8_name_is_unavailable_not_a_replaced_name(self):
        path = os.fsencode(self.source) + b"/invalid-\xff"
        with open(path, "wb") as stream:
            stream.write(b"input")
        self.assert_unavailable("--directory", self.source)

    def test_generated_metadata_and_expectations_must_be_outside_directory(self):
        destination = self.source / "result.json"
        result = run_collection(self.root, "--directory", self.source, metadata_output=destination)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("metadata output must be outside the input", result.stderr)
        self.assertFalse(destination.exists())
        expected = self.source / "expected.json"
        expected.write_text("{}")
        self.assert_unavailable("--directory", self.source, "--expected-manifest", expected, reference=True)

    def test_expected_manifest_rejects_duplicate_keys(self):
        source = self.source / "config"
        expected = self.root / "expected.json"
        manifest = observed(source, "file")["manifest"]
        raw = canonical_json(manifest).decode("ascii")
        entry = manifest["files"][0]
        cases = [
            raw.replace('"schema_version":1', '"schema_version":2,"schema_version":1'),
            raw.replace('"files":', '"files":[],"files":'),
            raw.replace('"sha256":', '"sha256":"' + "0" * 64 + '","sha256":'),
            raw.replace('"size_bytes":', '"size_bytes":0,"size_bytes":'),
            raw.replace('"path":', '"path":"DO_NOT_EXPORT","path":'),
            raw.replace('"sha256":', '"sha256":' + json.dumps(entry["sha256"]) + ',"sha256":'),
        ]
        for value in cases:
            with self.subTest(manifest=value):
                expected.write_text(value)
                result = self.run_cli("--file", source, "--expected-manifest", expected)
                self.assertEqual(result.returncode, 0, result.stderr)
                item = json.loads(result.stdout)
                self.assertEqual(item["verification_status"], "unavailable")
                self.assertEqual(item["collection_status"], "recorded")
                self.assertNotIn("DO_NOT_EXPORT", result.stdout)
                self.assertNotIn("DO_NOT_EXPORT", result.stderr)
                self.assertNotIn(str(self.root), result.stderr)


class ApplicationInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[2]
        (self.root / "scripts").symlink_to(self.repo / "scripts", target_is_directory=True)
        (self.root / "bin").mkdir()
        (self.root / "artifacts").mkdir()
        self.executable(self.root / "bin" / "module", "#!/bin/sh\nexit 0\n")
        self.executable(self.root / "bin" / "mpirun", """#!/bin/sh
touch "$TEST_MPI_MARKER"
if [ "${TEST_MPI_RANK_LOG:-0}" = 1 ]; then
    mkdir -p output.sample/0/17
    exec > output.sample/0/17/stdout.17.0
fi
printf 'FOM: ranks=1 ksp_iter_time_s=1.25\n'
printf 'rt iterations 1.25 a b c\ntotal calculation time 1.25\n'
exit "${TEST_MPI_STATUS:-0}"
""")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("BK_", "_BK_", "RESULT_SERVER_"))}
        self.env.update({"PATH": str(self.root / "bin") + os.pathsep + os.environ["PATH"],
                         "PYTHON_BIN": sys.executable,
                         "TEST_MPI_MARKER": str(self.root / "mpi-started")})

    def executable(self, path, text):
        path.write_text(text)
        path.chmod(0o700)

    def prepare_app(self, name, artifact):
        app = self.root / "programs" / name
        app.mkdir(parents=True)
        shutil.copyfile(self.repo / "programs" / name / "run.sh", app / "run.sh")
        self.executable(self.root / "artifacts" / artifact, "#!/bin/sh\nexit 0\n")
        return app

    def run_app(self, app, system="RIKYU"):
        return subprocess.run(["bash", str(app / "run.sh"), system, "1", "1", "1"],
                              cwd=self.root, env=self.env, capture_output=True, text=True, timeout=15)

    def test_petsc_records_changed_input_and_failed_execution(self):
        app = self.prepare_app("petsc-gmres", "GMRES-PETSc")
        data = self.root / "matrix.dat"
        data.write_bytes(b"abc")
        manifest = observed(data, "file")["manifest"]
        (app / "input-manifest.json").write_bytes(canonical_json(manifest))
        self.env["BK_PETSC_GMRES_MATRIX"] = str(data)
        data.write_bytes(b"abd")
        changed = self.run_app(app)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertTrue((self.root / "mpi-started").exists())
        info = input_info(self.root)
        self.assertEqual(info["inputs"][0]["sha256"], hashlib.sha256(b"abd").hexdigest())
        data.write_bytes(b"abc")
        passed = self.run_app(app)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        info = input_info(self.root)
        self.assertEqual(info["inputs"][0]["verification_status"], "declared")
        self.assertIn("FOM:", (self.root / "results/result").read_text())
        self.env["TEST_MPI_STATUS"] = "13"
        failed = self.run_app(app)
        self.assertEqual(failed.returncode, 13)
        self.assertEqual((self.root / "results/result").read_text(), "")
        self.assertTrue((self.root / "results/input_info.json").exists())
        records = [json.loads(path.read_text()) for path in (self.root / "results").glob("workflow_timing_*.json")]
        self.assertTrue(any(stage.get("exit_code") == 13 for record in records for stage in record["stages"]))

    def test_petsc_input_location_does_not_change_experiment_identity(self):
        app = self.prepare_app("petsc-gmres", "GMRES-PETSc")
        identities = []
        for relative in ("matrix.dat", "relocated/renamed-input.bin"):
            data = self.root / relative
            data.parent.mkdir(parents=True, exist_ok=True)
            data.write_bytes(b"abc")
            if not identities:
                (app / "input-manifest.json").write_bytes(
                    canonical_json(observed(data, "file")["manifest"]))
            self.env["BK_PETSC_GMRES_MATRIX"] = str(data)
            passed = self.run_app(app)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            result = (self.root / "results/result").read_text().split()
            experiment = next(field.removeprefix("Exp:") for field in result if field.startswith("Exp:"))
            info = input_info(self.root)["inputs"][0]
            self.assertTrue(experiment)
            self.assertEqual(info["verification_status"], "declared")
            self.assertEqual(info["result_exp"], experiment)
            identities.append((experiment, info["dataset_id"], info["dataset_version"], info["sha256"]))
        self.assertEqual(*identities)

    def prepare_restart(self):
        source = self.root / "restart-source"
        (source / "restart").mkdir(parents=True)
        (source / "restart/wfn.bin").write_bytes(b"abc")
        (source / "Si-3-3-3-tddft.nml").write_text("&parallel\n/\n")
        (source / "demo.psp8").write_bytes(b"potential")
        self.env["BK_SALMON_RESTART_DIR"] = str(source)
        return source

    def test_salmon_records_restart_and_effective_input_content(self):
        app = self.prepare_app("salmon", "salmon")
        source = self.prepare_restart()
        identities = []
        for content in (b"abc", b"abd"):
            (source / "restart/wfn.bin").write_bytes(content)
            result = self.run_app(app)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = input_info(self.root)
            restart = next(item for item in info["inputs"] if item["kind"] == "pre-staged-restart")
            effective = next(item for item in info["inputs"] if item["kind"] == "pre-staged-file")
            self.assertEqual(restart["verification_status"], "declared")
            self.assertEqual(restart["dataset_version"], restart["content_digest"])
            self.assertIn("restart/wfn.bin", [entry["path"] for entry in restart["manifest"]["files"]])
            self.assertTrue(effective["result_exp"])
            self.assertNotIn(str(source), json.dumps(info))
            identities.append(restart["content_digest"])
        self.assertNotEqual(*identities)

    def test_salmon_records_collection_failure_without_stopping_mpi(self):
        app = self.prepare_app("salmon", "salmon")
        source = self.prepare_restart()
        os.mkfifo(source / "restart/pipe")
        result = self.run_app(app)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "mpi-started").exists())
        info = input_info(self.root)
        restart = next(item for item in info["inputs"] if item["kind"] == "pre-staged-restart")
        self.assertEqual(restart["collection_status"], "unavailable")
        self.assertNotIn("content_digest", restart)

    def test_petsc_and_salmon_consume_common_rank_output(self):
        self.env["TEST_MPI_RANK_LOG"] = "1"
        (self.root / "bin/mpiexec").symlink_to("mpirun")
        petsc = self.prepare_app("petsc-gmres", "GMRES-PETSc")
        data = self.root / "matrix.dat"
        data.write_bytes(b"abc")
        (petsc / "input-manifest.json").write_bytes(
            canonical_json(observed(data, "file")["manifest"]))
        self.env["BK_PETSC_GMRES_MATRIX"] = str(data)
        salmon = self.prepare_app("salmon", "salmon")
        self.prepare_restart()
        for app in (petsc, salmon):
            with self.subTest(app=app.name):
                passed = self.run_app(app, "Fugaku")
                self.assertEqual(passed.returncode, 0, passed.stderr)
                self.assertIn("FOM:", (self.root / "results/result").read_text())
                self.env["TEST_MPI_STATUS"] = "23"
                failed = self.run_app(app, "Fugaku")
                self.assertEqual(failed.returncode, 23, failed.stderr)
                self.assertEqual((self.root / "results/result").read_text(), "")
                self.env.pop("TEST_MPI_STATUS")


if __name__ == "__main__":
    unittest.main()
