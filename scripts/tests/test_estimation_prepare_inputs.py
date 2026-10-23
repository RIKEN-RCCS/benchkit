"""Shared estimation preparation with synthetic, app-independent artifacts."""

import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "prepare_inputs", REPO / "scripts/estimation/prepare_inputs.py"
)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)
UUID = "12345678-1234-5678-1234-567812345678"


def archive_bytes(members):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, data, kind in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            member.linkname = "../../outside"
            archive.addfile(member, io.BytesIO(data) if member.isfile() else None)
    return output.getvalue()


class PrepareInputsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        Path("results").mkdir()
        self.calls = []
        self.responses = {
            "/api/query/measurement-artifact": b"opaque raw measurement archive",
            "/api/query/estimation-artifacts": archive_bytes([
                ("model/input.csv", b"counter,value\nsample,10\n", tarfile.REGTYPE),
            ]),
        }
        environment = patch.dict(os.environ, {"RESULT_SERVER": "https://results.example.invalid"})
        environment.start()
        self.addCleanup(environment.stop)
        mock = patch.object(prepare, "download", side_effect=self.download)
        mock.start()
        self.addCleanup(mock.stop)

    def download(self, endpoint, destination):
        self.calls.append(endpoint)
        data = self.responses.get(urlsplit(endpoint).path)
        if data is None:
            return False
        destination.write_bytes(data)
        return True

    def result(self, code="demo", uuid=UUID, paths=("results/profile.tgz",)):
        data = {"code": code, "_server_uuid": uuid, "fom_breakdown": {"sections": [{
            "name": "compute", "artifacts": [
                {"type": "file_reference", "path": path} for path in paths
            ],
        }]}}
        filename = Path("results/result0.json")
        filename.write_text(json.dumps(data))
        return filename

    def observation_bundle(self):
        payload = archive_bytes([('profile_test/discovery.sqlite', b'trace', tarfile.REGTYPE),
                                 ('profile_test/davidson-plan.json', b'{}', tarfile.REGTYPE)])
        Path('results/observation-bundle.tgz').write_bytes(payload)
        reference = dict(type='file_reference', path='results/observation-bundle.tgz',
                         sha256=hashlib.sha256(payload).hexdigest())
        manifest = dict(format='benchkit-observation-bundle/v1', summary=dict(bundle=reference),
                        files={'profile_test/discovery.sqlite': hashlib.sha256(b'trace').hexdigest(),
                               'profile_test/davidson-plan.json': hashlib.sha256(b'{}').hexdigest()})
        Path('results/manifest.json').write_text(json.dumps(manifest))
        result = self.result(paths=())
        result.write_text(json.dumps(dict(timing_observations=dict(observations=[dict(
            format=manifest['format'], artifact=dict(type='file_reference', path='results/manifest.json'),
            summary=manifest['summary'])]))))
        return result, manifest

    def test_explicit_observation_bundle_restores_local_inputs_without_server(self):
        result, _ = self.observation_bundle()
        before = result.read_bytes()
        prepare.prepare_inputs([result])
        self.assertEqual(Path('results/profile_test/discovery.sqlite').read_bytes(), b'trace')
        self.assertEqual(result.read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_observation_archive_hash_and_member_hash_are_required(self):
        result, manifest = self.observation_bundle()
        Path('results/observation-bundle.tgz').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            prepare.prepare_inputs([result])
        result, manifest = self.observation_bundle()
        manifest['files']['profile_test/discovery.sqlite'] = '0'*64
        Path('results/manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'hashes'):
            prepare.prepare_inputs([result])
        self.assertFalse(Path('results/profile_test').exists())

    def test_observation_conflict_is_checked_before_publishing_any_file(self):
        result, _ = self.observation_bundle()
        Path('results/profile_test').mkdir()
        Path('results/profile_test/discovery.sqlite').write_bytes(b'other observation')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            prepare.prepare_inputs([result])
        self.assertFalse(Path('results/profile_test/davidson-plan.json').exists())
        self.assertEqual(Path('results/profile_test/discovery.sqlite').read_bytes(), b'other observation')

    def test_bundle_cannot_restore_control_data(self):
        archive = Path('bundle.tgz')
        archive.write_bytes(archive_bytes([('result0.json', b'{}', tarfile.REGTYPE)]))
        with self.assertRaisesRegex(ValueError, 'hashes'):
            prepare.restore_bundle(archive, Path('results'), manifest={'result0.json': hashlib.sha256(b'{}').hexdigest()})
        self.assertFalse(Path('results/result0.json').exists())

    def test_initial_and_reestimate_use_same_preparation_for_different_apps(self):
        for code in ("demo_cpu", "demo_gpu"):
            result = self.result(code=code)
            before = result.read_bytes()
            prepare.prepare_inputs([result])
            self.assertEqual(result.read_bytes(), before)
            self.assertEqual(Path("results/profile.tgz").read_bytes(), self.responses["/api/query/measurement-artifact"])
            self.assertTrue(Path("results/estimation_artifacts/model/input.csv").is_file())
            measurement = next(url for url in self.calls if "measurement-artifact?" in url)
            self.assertEqual(parse_qs(urlsplit(measurement).query), {
                "uuid": [UUID], "artifact_path": ["results/profile.tgz"],
            })
            Path("results/profile.tgz").unlink()
            shutil.rmtree("results/estimation_artifacts")
            self.calls.clear()

    def test_local_inputs_are_preserved_and_manifest_uuid_is_supported(self):
        result = self.result(uuid=None)
        Path("results/server_result_meta.json").write_text(json.dumps({"result0.json": {"uuid": UUID}}))
        Path("results/profile.tgz").write_bytes(b"local measurement")
        Path("results/estimation_artifacts").mkdir()
        Path("results/estimation_artifacts/input.csv").write_bytes(b"local input")
        prepare.prepare_inputs([result])
        self.assertEqual(self.calls, [])
        self.assertEqual(Path("results/profile.tgz").read_bytes(), b"local measurement")

    def test_missing_artifact_does_not_prevent_artifact_free_estimation(self):
        self.responses = {}
        result = self.result()
        prepare.prepare_inputs([result])
        self.assertFalse(Path("results/profile.tgz").exists())
        self.assertTrue(any("estimation-inputs?" in url for url in self.calls))

    def test_transport_failure_is_not_ignored_or_treated_as_legacy_endpoint(self):
        result = self.result(paths=())
        with patch.object(prepare, "download", side_effect=RuntimeError("query failed")):
            with self.assertRaises(RuntimeError):
                prepare.prepare_inputs([result])

    def test_timing_and_node_status_references_are_restored_too(self):
        result = self.result(paths=())
        result.write_text(json.dumps({"_server_uuid": UUID,
            "timing_observations": {"observations": [{"artifact": {
                "type": "file_reference", "path": "results/timing.json"}}]},
            "node_status_snapshot": {"artifact": {
                "type": "file_reference", "path": "results/nodes.json"}},
        }))
        prepare.prepare_inputs([result])
        self.assertTrue(Path("results/timing.json").is_file())
        self.assertTrue(Path("results/nodes.json").is_file())

    def test_rejects_unsafe_destinations_and_control_file_references(self):
        for path in ("/tmp/profile.tgz", "results/../outside.tgz", "results/./profile.tgz",
                     "results//profile.tgz", "results/reestimation_context.json", "results/result1.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                prepare.prepare_inputs([self.result(paths=(path,))])
        Path("results/linked").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare.prepare_inputs([self.result(paths=("results/linked/profile.tgz",))])
        self.assertEqual(self.calls, [])

    def test_different_results_cannot_share_a_missing_download_destination(self):
        first = self.result()
        second = Path("results/result1.json")
        data = json.loads(first.read_text())
        data["_server_uuid"] = "87654321-4321-8765-4321-876543218765"
        second.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            prepare.prepare_inputs([first, second])
        self.assertEqual(self.calls, [])

    def test_different_results_cannot_reuse_a_restored_estimator_input(self):
        first = self.result(paths=())
        second = Path("results/result1.json")
        data = json.loads(first.read_text())
        data["_server_uuid"] = "87654321-4321-8765-4321-876543218765"
        second.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            prepare.prepare_inputs([first, second])

    def test_bundle_rejects_links_traversal_duplicates_and_extraction_limits(self):
        for members in (
            [("../outside", b"bad", tarfile.REGTYPE)],
            [("/outside", b"bad", tarfile.REGTYPE)],
            [("link", b"", tarfile.SYMTYPE)],
            [("link", b"", tarfile.LNKTYPE)],
            [("input", b"a", tarfile.REGTYPE), ("./input", b"b", tarfile.REGTYPE)],
        ):
            archive = Path("bundle.tgz")
            archive.write_bytes(archive_bytes(members))
            with self.assertRaises(ValueError):
                prepare.restore_bundle(archive, Path("results/estimation_artifacts"))
            self.assertFalse(Path("results/estimation_artifacts").exists())
        archive.write_bytes(archive_bytes([("input", b"abc", tarfile.REGTYPE)]))
        with patch.object(prepare, "MAX_ARCHIVE_BYTES", 2), self.assertRaises(ValueError):
            prepare.restore_bundle(archive, Path("results/estimation_artifacts"))

    def test_optional_download_distinguishes_http_and_transport_errors(self):
        for status, expected in (("200", 0), ("404", 3), ("401", 1), ("403", 1), ("302", 1), ("500", 1)):
            command = '''
source "$1"
bk_result_server_require_env() { :; }
bk_result_server_set_curl_args() { curl_auth_args=(); }
curl() { printf '%s' "$TEST_STATUS"; }
bk_result_server_download_optional_to_file /api/query/measurement-artifact download
'''
            result = subprocess.run(["bash", "-c", command, "test", str(prepare.API_HELPER)],
                                    env=dict(os.environ, TEST_STATUS=status), capture_output=True)
            self.assertEqual(result.returncode, expected, result.stderr)

    def test_normal_and_retry_entrypoints_restore_raw_csv_before_app_estimation(self):
        if not shutil.which("jq"):
            self.skipTest("jq is required by the estimation runner")
        stored = self.root / "stored"
        stored.mkdir()
        result = self.result(code="demo_gpu")
        (stored / "result.json").write_bytes(result.read_bytes())
        (stored / "estimate.json").write_text(json.dumps({
            "exp": "demo-case",
            "current_system": {"system": "DemoCPU", "target_nodes": "1", "benchmark": {"uuid": UUID}},
            "future_system": {"system": "DemoFuture", "target_nodes": "2"},
            "estimate_metadata": {
                "source_result_uuid": UUID,
                "current_package": {"requested_estimation_package": "weakscaling"},
                "future_package": {"requested_estimation_package": "instrumented_app_sections_dummy"},
            },
        }))
        raw_csv = b"counter,value\nsample,10\n"
        (stored / "measurement.tgz").write_bytes(archive_bytes([
            ("bk_profiler_artifact/raw/rep1/profile_raw.csv", raw_csv, tarfile.REGTYPE),
        ]))
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        curl = bin_dir / "curl"
        curl.write_text('''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
args = sys.argv[1:]
endpoint = urlsplit(args[-1]).path
source = {"/api/query/result": "result.json", "/api/query/estimate": "estimate.json",
          "/api/query/measurement-artifact": "measurement.tgz"}.get(endpoint)
data = (Path(os.environ["TEST_STORED"]) / source).read_bytes() if source else b""
if "-o" in args:
    Path(args[args.index("-o") + 1]).write_bytes(data)
else:
    sys.stdout.buffer.write(data)
if "-w" in args:
    print("200" if source else "404", end="")
elif not source:
    sys.exit(22)
''')
        curl.chmod(0o755)
        for name in ("client.crt", "client.key"):
            (self.root / name).touch()
        environment = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                           TEST_STORED=str(stored), code="demo_gpu", estimate_result_uuid=UUID,
                           RESULT_SERVER_CLIENT_CERT=str(self.root / "client.crt"),
                           RESULT_SERVER_CLIENT_KEY=str(self.root / "client.key"))
        for mode in ("normal", "retry"):
            workspace = self.root / mode
            (workspace / "results").mkdir(parents=True)
            app = workspace / "programs/demo_gpu"
            app.mkdir(parents=True)
            (app / "estimate.sh").write_text('''#!/bin/bash
set -euo pipefail
archive=$(jq -r '.fom_breakdown.sections[0].artifacts[0].path' "$1")
tar -xOzf "$archive" bk_profiler_artifact/raw/rep1/profile_raw.csv > results/observed.csv
printf '{"code":"demo_gpu"}\n' > results/estimate_demo_gpu.json
''')
            if mode == "normal":
                shutil.copyfile(stored / "result.json", workspace / "results/result0.json")
            else:
                completed = subprocess.run(["bash", str(REPO / "scripts/result_server/fetch_result_by_uuid.sh")],
                                           cwd=workspace, env=environment, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertFalse((workspace / "results/profile.tgz").exists())
            completed = subprocess.run(["bash", str(REPO / "scripts/estimation/run.sh"), "demo_gpu"],
                                       cwd=workspace, env=environment, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((workspace / "results/observed.csv").read_bytes(), raw_csv)
            self.assertIn("estimation_timing", json.loads((workspace / "results/estimate_demo_gpu.json").read_text()))


if __name__ == "__main__":
    unittest.main()
