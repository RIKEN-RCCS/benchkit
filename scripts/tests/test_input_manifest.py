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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import input_manifest as collector


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
        return subprocess.run(
            [sys.executable, collector.__file__, *map(str, args)],
            input='{"dataset_id":"demo"}', text=True, capture_output=True, timeout=10,
        )

    def assert_cli_failure(self, *args):
        result = self.run_cli(*args)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(str(self.root), result.stderr)

    def test_directory_identity_is_independent_of_location_and_mtime(self):
        copied = self.root / "copied"
        shutil.copytree(self.source, copied)
        os.utime(copied / "config", (1, 1))
        first = collector.collect(self.source, "directory")
        second = collector.collect(copied, "directory")
        self.assertEqual(first["manifest_digest"], second["manifest_digest"])
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(first["size_bytes"], len(b"abcconfig"))
        self.assertEqual(first["file_count"], 2)
        self.assertEqual(first["verification_status"], "declared")
        self.assertNotIn(str(self.root), json.dumps(first))
        (copied / "config").write_bytes(b"Config")
        changed = collector.collect(copied, "directory")
        self.assertNotEqual(first["content_digest"], changed["content_digest"])

    def test_file_identity_does_not_include_basename_and_reads_in_chunks(self):
        one = self.source / "config"
        two = self.root / "renamed"
        two.write_bytes(one.read_bytes())
        with patch.object(collector, "CHUNK_BYTES", 2):
            first = collector.collect(one, "file")
        second = collector.collect(two, "file")
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(first["sha256"], hashlib.sha256(b"config").hexdigest())
        self.assertEqual(first["manifest"]["files"][0]["path"], "input")
        two.write_bytes(b"")
        self.assertEqual(collector.collect(two, "file")["sha256"], hashlib.sha256(b"").hexdigest())

    def test_expected_manifest_requires_exact_file_set_and_content(self):
        observed = collector.collect(self.source, "directory")
        expected_file = self.root / "expected.json"
        expected_file.write_bytes(collector.canonical_json(observed["manifest"]))
        result = self.run_cli("--directory", self.source, "--expected-manifest", expected_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        verified = json.loads(result.stdout)
        self.assertEqual(verified["verification_status"], "verified")
        self.assertEqual(verified["dataset_version"], observed["content_digest"])
        (self.source / "extra").write_bytes(b"extra")
        self.assert_cli_failure("--directory", self.source, "--expected-manifest", expected_file)
        (self.source / "extra").unlink()
        (self.source / "config").write_bytes(b"Config")
        self.assert_cli_failure("--directory", self.source, "--expected-manifest", expected_file)
        (self.source / "config").unlink()
        self.assert_cli_failure("--directory", self.source, "--expected-manifest", expected_file)

    def test_internal_symlinks_match_copied_content(self):
        link = self.source / "link"
        link.symlink_to("nested/wave data")
        first = collector.collect(self.source, "directory")
        link.unlink()
        link.write_bytes(b"abc")
        second = collector.collect(self.source, "directory")
        self.assertEqual(first["manifest_digest"], second["manifest_digest"])
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        self.assertEqual(collector.collect(alias, "directory")["manifest"], second["manifest"])

    def test_unsafe_or_unreadable_inputs_fail_without_location_disclosure(self):
        link = self.source / "link"
        outside = self.root / "outside"
        outside.write_bytes(b"do not read")
        for target in (outside, self.source, self.root / "missing"):
            with self.subTest(target=target.name):
                link.symlink_to(target)
                self.assert_cli_failure("--directory", self.source)
                link.unlink()
        os.mkfifo(link)
        self.assert_cli_failure("--directory", self.source)
        self.assert_cli_failure("--file", link)
        self.assert_cli_failure("--file", outside, "--expected-manifest", link)
        link.unlink()
        empty = self.root / "empty"
        empty.mkdir()
        self.assert_cli_failure("--directory", empty)
        self.assert_cli_failure("--file", self.source)
        self.assert_cli_failure("--directory", outside)

    def test_changes_during_collection_do_not_produce_a_manifest(self):
        original = collector.hash_file

        def replace_after_read(path, identity):
            result = original(path, identity)
            path.write_bytes(b"replacement")
            return result

        with patch.object(collector, "hash_file", side_effect=replace_after_read):
            with self.assertRaises(collector.InputError):
                collector.collect(self.source, "directory")
        with patch.object(collector, "hash_file", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                collector.collect(self.source, "directory")

    def test_manifest_validation_and_limits(self):
        expected = self.root / "expected.json"
        valid = collector.collect(self.source / "config", "file")["manifest"]
        for field, value in (("sha256", "short"), ("size_bytes", True), ("path", "../outside")):
            invalid = {**valid, "files": [{**valid["files"][0], field: value}]}
            expected.write_text(json.dumps(invalid))
            self.assert_cli_failure("--file", self.source / "config", "--expected-manifest", expected)
        expected.write_text('{"schema_version": 1}')
        self.assert_cli_failure("--file", self.source / "config", "--expected-manifest", expected)
        with patch.object(collector, "MAX_ENTRIES", 1):
            with self.assertRaises(collector.InputError):
                collector.collect(self.source, "directory")
        with patch.object(collector, "hash_file") as hasher:
            with self.assertRaises(collector.InputError):
                collector.collect(self.source / "nested/wave data", "file", valid)
            hasher.assert_not_called()

    def test_generated_metadata_and_expectations_must_be_outside_directory(self):
        self.assert_cli_failure("--directory", self.source, "--metadata-output", self.source / "result.json")
        expected = self.source / "expected.json"
        expected.write_text("{}")
        self.assert_cli_failure("--directory", self.source, "--expected-manifest", expected)

    def test_expected_manifest_rejects_duplicate_keys(self):
        source = self.source / "config"
        expected = self.root / "expected.json"
        manifest = collector.collect(source, "file")["manifest"]
        raw = collector.canonical_json(manifest).decode("ascii")
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
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
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

    def test_petsc_verifies_before_mpi_and_rejects_failed_execution(self):
        app = self.prepare_app("petsc-gmres", "GMRES-PETSc")
        data = self.root / "matrix.dat"
        data.write_bytes(b"abc")
        manifest = collector.collect(data, "file")["manifest"]
        (app / "input-manifest.json").write_bytes(collector.canonical_json(manifest))
        self.env["BK_PETSC_GMRES_MATRIX"] = str(data)
        data.write_bytes(b"abd")
        failed = self.run_app(app)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((self.root / "mpi-started").exists())
        self.assertFalse((self.root / "results/input_info.json").exists())
        data.write_bytes(b"abc")
        passed = self.run_app(app)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        info = json.loads((self.root / "results/input_info.json").read_text())
        self.assertEqual(info["inputs"][0]["verification_status"], "verified")
        self.assertIn("FOM:", (self.root / "results/result").read_text())
        self.env["TEST_MPI_STATUS"] = "13"
        failed = self.run_app(app)
        self.assertEqual(failed.returncode, 13)
        self.assertEqual((self.root / "results/result").read_text(), "")

    def test_petsc_input_location_does_not_change_experiment_identity(self):
        app = self.prepare_app("petsc-gmres", "GMRES-PETSc")
        identities = []
        for relative in ("matrix.dat", "relocated/renamed-input.bin"):
            data = self.root / relative
            data.parent.mkdir(parents=True, exist_ok=True)
            data.write_bytes(b"abc")
            if not identities:
                (app / "input-manifest.json").write_bytes(
                    collector.canonical_json(collector.collect(data, "file")["manifest"]))
            self.env["BK_PETSC_GMRES_MATRIX"] = str(data)
            passed = self.run_app(app)
            self.assertEqual(passed.returncode, 0, passed.stderr)
            result = (self.root / "results/result").read_text().split()
            experiment = next(field.removeprefix("Exp:") for field in result if field.startswith("Exp:"))
            info = json.loads((self.root / "results/input_info.json").read_text())["inputs"][0]
            self.assertTrue(experiment)
            self.assertEqual(info["verification_status"], "verified")
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
            info = json.loads((self.root / "results/input_info.json").read_text())
            restart = next(item for item in info["inputs"] if item["kind"] == "pre-staged-restart")
            effective = next(item for item in info["inputs"] if item["kind"] == "pre-staged-file")
            self.assertEqual(restart["verification_status"], "declared")
            self.assertEqual(restart["dataset_version"], restart["content_digest"])
            self.assertIn("restart/wfn.bin", [entry["path"] for entry in restart["manifest"]["files"]])
            self.assertTrue(effective["result_exp"])
            self.assertNotIn(str(source), json.dumps(info))
            identities.append(restart["content_digest"])
        self.assertNotEqual(*identities)

    def test_salmon_stops_before_mpi_when_collection_fails(self):
        app = self.prepare_app("salmon", "salmon")
        source = self.prepare_restart()
        os.mkfifo(source / "restart/pipe")
        result = self.run_app(app)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "mpi-started").exists())
        self.assertFalse((self.root / "results/input_info.json").exists())

    def test_petsc_and_salmon_consume_common_rank_output(self):
        self.env["TEST_MPI_RANK_LOG"] = "1"
        (self.root / "bin/mpiexec").symlink_to("mpirun")
        petsc = self.prepare_app("petsc-gmres", "GMRES-PETSc")
        data = self.root / "matrix.dat"
        data.write_bytes(b"abc")
        (petsc / "input-manifest.json").write_bytes(
            collector.canonical_json(collector.collect(data, "file")["manifest"]))
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
