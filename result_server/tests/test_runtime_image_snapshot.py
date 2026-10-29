"""Shared image observation works without an application or container runtime."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


HELPER = Path(__file__).resolve().parents[2] / "scripts/record_runtime_image.py"


@pytest.mark.parametrize("existing", [False, True])
def test_standalone_image_snapshot(tmp_path, existing):
    image = tmp_path / "arbitrary image.sif"
    image.write_bytes(b"synthetic image, not executable")
    snapshot = tmp_path / "run.json"
    original = {"schema_version": 1, "ci": {"job_id": "fixture"},
                "host": {"name": "fixture"}, "toolchain": {"modules": ["fixture"]}}
    if existing:
        snapshot.write_text(json.dumps(original))
    result = subprocess.run(
        [sys.executable, str(HELPER), str(image), str(snapshot)],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(snapshot.read_text())
    assert observed["toolchain"]["container"] == {
        "image_path": str(image), "image_sha256sum": hashlib.sha256(image.read_bytes()).hexdigest(),
        "observation_status": "observed",
    }
    if existing:
        del observed["toolchain"]["container"]
        assert observed == original


def test_unavailable_does_not_open_image_and_clears_old_hash(tmp_path):
    image = tmp_path / "fifo.sif"
    os.mkfifo(image)
    snapshot = tmp_path / "run.json"
    snapshot.write_text(json.dumps({"toolchain": {"container": {"image_sha256sum": "a" * 64}}}))
    result = subprocess.run(
        [sys.executable, str(HELPER), str(image), str(snapshot), "timeout"],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    record = json.loads(snapshot.read_text())["toolchain"]["container"]
    assert record["image_sha256sum"] == ""
    assert record["observation_status"] == "timeout"


def test_invalid_snapshot_cli_preserves_original(tmp_path):
    snapshot = tmp_path / "run.json"
    snapshot.write_text("not JSON")
    result = subprocess.run(
        [sys.executable, str(HELPER), str(tmp_path / "missing.sif"), str(snapshot)],
        cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 1
    assert snapshot.read_text() == "not JSON"
    assert not list(tmp_path.glob(".sif-observation-*"))
