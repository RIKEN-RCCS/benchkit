"""Synthetic files only: never invoke a container, scheduler or training."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "programs/omnilearned"
spec = importlib.util.spec_from_file_location("omni_sif", APP / "record_sif.py")
sif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sif)


def test_snapshot_preserves_existing_evidence(tmp_path):
    image = tmp_path / "image.sif"
    image.write_bytes(b"synthetic image")
    snapshot = tmp_path / "snapshot.json"
    original = {"schema_version": 1, "ci": {"commit": "example"},
                "toolchain": {"modules": ["fixture"], "container": {"image_path": "old"}}}
    snapshot.write_text(json.dumps(original))
    sif.record_image(image, snapshot)
    data = json.loads(snapshot.read_text())
    assert data["ci"] == original["ci"]
    assert data["toolchain"]["modules"] == ["fixture"]
    assert data["toolchain"]["container"] == {
        "image_path": str(image), "image_sha256sum": hashlib.sha256(image.read_bytes()).hexdigest(),
        "observation_status": "observed"}


@pytest.mark.parametrize("kind", ["missing", "directory", "fifo"])
def test_unavailable_images_never_look_verified(tmp_path, kind):
    image = tmp_path / "image.sif"
    if kind == "directory":
        image.mkdir()
    if kind == "fifo":
        os.mkfifo(image)
    data = sif.observe(image)
    assert data["image_sha256sum"] == ""
    assert data["observation_status"] == ("missing" if kind == "missing" else "unavailable")


def test_read_failure(tmp_path, monkeypatch):
    def denied(*args):
        raise PermissionError()
    monkeypatch.setattr(sif.os, "open", denied)
    assert sif.observe(tmp_path / "image")["observation_status"] == "unavailable"


def test_changed_image_has_no_digest(tmp_path, monkeypatch):
    image = tmp_path / "image.sif"
    image.write_bytes(b"before")
    real_sha256 = hashlib.sha256
    class Digest:
        def __init__(self):
            self.digest = real_sha256()
        def update(self, block):
            self.digest.update(block)
            image.write_bytes(b"after replacement")
        def hexdigest(self):
            return self.digest.hexdigest()
    monkeypatch.setattr(sif.hashlib, "sha256", Digest)
    assert sif.observe(image)["observation_status"] == "changed"


@pytest.mark.parametrize("body", ["not json", "[]", '{"toolchain":[]}'])
def test_invalid_snapshot_is_not_overwritten(tmp_path, body):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(body)
    with pytest.raises(ValueError):
        sif.record_image(tmp_path / "missing.sif", snapshot)
    assert snapshot.read_text() == body
    assert not list(tmp_path.glob(".sif-observation-*"))


def test_atomic_replace_failure_preserves_snapshot(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"schema_version":1}')
    def denied(*args):
        raise OSError()
    monkeypatch.setattr(sif.os, "replace", denied)
    with pytest.raises(OSError):
        sif.record_image(tmp_path / "missing", snapshot)
    assert snapshot.read_text() == '{"schema_version":1}'
    assert not list(tmp_path.glob(".sif-observation-*"))


@pytest.mark.parametrize("override,missing", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("dataset_state", ["present", "changed", "missing"])
def test_runtime_to_result(tmp_path, override, missing, dataset_state):
    assert shutil.which("jq"), "Result assembly requires the existing jq tool"
    results = tmp_path / "results"
    results.mkdir()
    data = tmp_path / ("override data" if override else "data")
    for split in ("train", "val", "test"):
        (data / "top" / split).mkdir(parents=True)
        (data / "top" / split / "sample.h5").write_bytes(split.encode())
    (data / "top" / "file_manifest.json").write_text('{"fixture":true}')
    if dataset_state == "changed":
        (data / "top" / "train/sample.h5").write_bytes(b"changed input")
    if dataset_state == "missing":
        shutil.rmtree(data / "top")
    image = tmp_path / ("override.sif" if override else "default.sif")
    if not missing:
        image.write_bytes(b"override" if override else b"default")
    build = {"schema_version": 1, "toolchain": {"container": {"image_sha256sum": "a" * 64}}}
    (results / "environment_snapshot_build.json").write_text(json.dumps(build))
    (results / "environment_snapshot_run.json").write_text(json.dumps({"schema_version": 1, "ci": {"job_id": "fixture"}}))
    (results / "source_info.env").write_text("BK_SOURCE_TYPE=git\nBK_REPO_URL=https://example.test/source\nBK_COMMIT_HASH=original\n")
    source_before = (results / "source_info.env").read_bytes()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "APP_DIR": str(APP),
           "RESULTS_DIR": str(results), "INPUT": str(data), "IMAGE": str(image), "ROOT": str(ROOT)}
    cmd = 'source "$ROOT/scripts/bk_functions.sh"; source "$APP_DIR/record_runtime.sh"; record_omnilearned_runtime "$INPUT" "$IMAGE"'
    run = subprocess.run(["bash", "-c", cmd], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    (results / "result").write_text("FOM:12.5 FOM_unit:events/s FOM_version:fixture Exp:top-medium-pretrain-b8 node_count:1 numproc_node:4 nthreads:12\n")
    out = subprocess.run(["bash", str(ROOT / "scripts/result.sh"), "omnilearned", "Fugaku", "cross", "1", "2", "3"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    files = list(results.glob("result[0-9]*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert float(record["FOM"]) == 12.5
    assert record["source_info"]["commit_hash"] == "original"
    assert (results / "source_info.env").read_bytes() == source_before
    payload = record["environment_snapshot"]["payload"]
    container = payload["stages"]["run"]["toolchain"]["container"]
    assert container["image_path"] == str(image)
    assert container["observation_status"] == ("missing" if missing else "observed")
    assert payload["stages"]["build"] == build
    observation = record["input_info"]["inputs"][0]
    if dataset_state == "missing":
        assert observation["collection_status"] != "recorded"
    else:
        assert observation["collection_status"] == "recorded"
        files = observation["manifest"]["files"]
        actual = next(f["sha256"] for f in files if f["path"] == "train/sample.h5")
        expected = b"changed input" if dataset_state == "changed" else b"train"
        assert actual == hashlib.sha256(expected).hexdigest()
        assert any(f["path"] == "file_manifest.json" for f in files)


@pytest.mark.parametrize("exit_code,marker", [(0, True), (7, True), (0, False)])
@pytest.mark.parametrize("system", ["Fugaku", "RIKYU", "RC_GH200", "RC_DGXSP", "RC_GENOA"])
def test_run_uses_observed_image_and_preserves_exit(tmp_path, exit_code, marker, system):
    tools = tmp_path / "tools"
    tools.mkdir()
    artifact = tmp_path / "artifacts"
    pf = artifact / "pytorch-fugaku/fugaku"
    pf.mkdir(parents=True)
    (pf / "pf-setup").write_text("#!/bin/bash\nexit 0\n")
    (pf / "pf-setup").chmod(0o700)
    launcher = tools / "mpiexec"
    launcher.write_text(
        '#!/bin/bash\nprintf "%s" "$SIF" > selected-image\n'
        + "printf 'Train pass wall: 2.0 sec\\n' > train.log\n"
        + ("echo 'Training Complete' >> train.log\n" if marker else "")
        + "exit {}\n".format(exit_code))
    launcher.chmod(0o700)
    (artifact / "venv/bin").mkdir(parents=True)
    torch = artifact / "venv/bin/torchrun"
    torch.write_text("#!/bin/bash\nprintf 'Train pass wall: 2.0 sec\\n'\n"
                     + ("echo 'Training Complete'\n" if marker else "")
                     + "exit {}\n".format(exit_code))
    torch.chmod(0o700)
    # Any accidental external acquisition must fail rather than reach a service.
    for name in ("curl", "wget", "ssh", "singularity", "apptainer"):
        path = tools / name
        path.write_text("#!/bin/bash\nexit 99\n")
        path.chmod(0o700)
    image = tmp_path / "fake image.sif"
    image.write_bytes(b"not a container")
    data = tmp_path / "input"
    (data / "top").mkdir(parents=True)
    (data / "top" / "fixture.h5").write_bytes(b"not HDF5")
    (artifact / "top_medium_pretrain_fugaku.yaml").write_text("iterations: 2\nbatch: 8\npath: __OMNILEARNED_DATA__\n")
    for config in ("top_medium_pretrain.yaml", "top_medium_pretrain_b64.yaml", "top_medium_pretrain_cpu.yaml"):
        (artifact / config).write_text("iterations: 2\nbatch: 8\npath: __OMNILEARNED_DATA__\n")
    (data / "top/train").mkdir()
    (data / "top/train/data.h5").write_bytes(b"fixture")
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    env = {"PATH": str(tools) + ":/usr/bin:/bin", "HOME": str(tmp_path),
           "BK_OMNILEARNED_DATA": str(data), "BK_OMNILEARNED_SIF": str(image)}
    run = subprocess.run(["bash", str(ROOT / "scripts/run_benchmark.sh"), str(APP / "run.sh"),
                          system, "1", "1", "2"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=30)
    ok = exit_code == 0 and marker
    assert (run.returncode == 0) == ok, run.stderr
    execution = json.loads((tmp_path / "results/execution.json").read_text())
    assert execution["status"] == ("completed" if ok else "failed")
    assert (tmp_path / "results/execution.log").is_file()
    if system == "Fugaku":
        container = json.loads((tmp_path / "results/environment_snapshot_run.json").read_text())["toolchain"]["container"]
        assert container["image_path"] == (tmp_path / "selected-image").read_text()
        assert container["image_sha256sum"] == hashlib.sha256(image.read_bytes()).hexdigest()
    else:
        assert not (tmp_path / "results/environment_snapshot_run.json").exists()
    observation = json.loads((tmp_path / "results/input_info.json").read_text())["inputs"][0]
    if system == "RC_DGXSP":
        assert observation["collection_error"] == "skipped_unified_memory"
        assert "observation_capture" not in observation
    else:
        assert observation["observation_capture"]["collection_status"] == "recorded"
    fom = (tmp_path / "results/result").read_text()
    if ok:
        assert "FOM:8.0" in fom
    else:
        assert not fom


def test_recording_failure_does_not_block_launcher(tmp_path):
    env = {"PATH": os.environ["PATH"], "APP_DIR": str(APP), "RESULTS_DIR": str(tmp_path / "absent")}
    cmd = 'source "$APP_DIR/record_runtime.sh"; bk_record_input() { return 1; }; record_omnilearned_runtime /not-real /not-real; echo FAKE_LAUNCHER'
    run = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0
    assert "FAKE_LAUNCHER" in run.stdout


@pytest.mark.parametrize("mode", ["sif_delay", "dataset_delay", "dataset_interrupt"])
def test_observation_timeout_or_interrupt_continues_without_partial_hash(tmp_path, mode):
    results = tmp_path / "results"
    results.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    image = tmp_path / "image.sif"
    image.write_bytes(b"fixture")
    data = tmp_path / "data/top"
    data.mkdir(parents=True)
    (data / "input.h5").write_bytes(b"fixture")
    snapshot = results / "environment_snapshot_run.json"
    snapshot.write_text('{"schema_version":1,"ci":{"job_id":"keep"}}')
    # Only the observation worker is delayed; fallback publication remains real.
    python = tools / "python3"
    python.write_text('#!/bin/bash\nif [[ "$1" == */record_sif.py && "$#" == 3 && "$MODE" == sif_delay ]]; then sleep 10; fi\nexec "$REAL_PYTHON" "$@"\n')
    python.chmod(0o700)
    sha = tools / "sha256sum"
    sha.write_text('#!/bin/bash\nif [[ "$MODE" == dataset_delay ]]; then sleep 10; fi\nif [[ "$MODE" == dataset_interrupt ]]; then kill -TERM "$PPID"; exit 143; fi\nexec /usr/bin/sha256sum "$@"\n')
    sha.chmod(0o700)
    env = {"PATH": str(tools) + ":/usr/bin:/bin", "HOME": str(tmp_path), "APP_DIR": str(APP),
           "RESULTS_DIR": str(results), "INPUT": str(data.parent), "IMAGE": str(image), "ROOT": str(ROOT),
           "BK_OMNILEARNED_OBSERVATION_SECONDS": "1", "MODE": mode, "REAL_PYTHON": sys.executable}
    cmd = 'source "$ROOT/scripts/bk_functions.sh"; source "$APP_DIR/record_runtime.sh"; record_omnilearned_runtime "$INPUT" "$IMAGE"; echo FAKE_LAUNCHER'
    start = time.monotonic()
    run = subprocess.run(["bash", "-c", cmd], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=8)
    assert time.monotonic() - start < 7
    assert run.returncode == 0, run.stderr
    assert "FAKE_LAUNCHER" in run.stdout
    container = json.loads(snapshot.read_text())["toolchain"]["container"]
    assert json.loads(snapshot.read_text())["ci"]["job_id"] == "keep"
    item = json.loads((results / "input_info.json").read_text())["inputs"][0]
    if mode == "sif_delay":
        assert container["observation_status"] == "timeout"
        assert container["image_sha256sum"] == ""
        assert item["observation_capture"]["collection_status"] == "recorded"
    else:
        assert item["collection_status"] == "unavailable"
        assert item["collection_error"] in ("timeout", "interrupted", "collector_failed")
        assert "observation_capture" not in item
    assert not list(results.glob(".omni-input.*"))


def test_dgx_does_not_walk_dataset_and_preserves_prior_input(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    prior = {"dataset_id": "existing", "kind": "runtime-parameters", "source": "inline"}
    (results / "input_info.json").write_text(json.dumps({"schema_version": 1, "inputs": [prior]}))
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "APP_DIR": str(APP), "RESULTS_DIR": str(results), "ROOT": str(ROOT)}
    cmd = 'source "$ROOT/scripts/bk_functions.sh"; source "$APP_DIR/record_runtime.sh"; system=RC_DGXSP; mktemp() { echo unexpected-walk >&2; return 9; }; record_omnilearned_runtime /does-not-exist; echo FAKE_LAUNCHER'
    run = subprocess.run(["bash", "-c", cmd], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=5)
    assert run.returncode == 0
    assert "unexpected-walk" not in run.stderr
    items = json.loads((results / "input_info.json").read_text())["inputs"]
    assert items[0] == prior
    assert items[1]["collection_error"] == "skipped_unified_memory"
    (results / "result").write_text("FOM:8.0 FOM_unit:events/s Exp:fixture node_count:1 numproc_node:1 nthreads:2\n")
    assembled = subprocess.run(["bash", str(ROOT / "scripts/result.sh"), "omnilearned", "RC_DGXSP", "cross", "1", "2", "3"],
                               cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15)
    assert assembled.returncode == 0, assembled.stderr
    published = json.loads((results / "result0.json").read_text())["input_info"]["inputs"]
    skipped = next(item for item in published if item["dataset_id"] == "omnilearned-top-staged")
    assert skipped["collection_status"] == "unavailable"
    assert skipped["verification_status"] == "unavailable"
    assert not skipped.get("content_digest")


@pytest.mark.parametrize("mode", ["failure", "delay"])
def test_cleanup_failure_or_timeout_retains_files_and_continues(tmp_path, mode):
    results = tmp_path / "results"
    results.mkdir()
    tools = tmp_path / "tools"
    tools.mkdir()
    data = tmp_path / "data/top"
    data.mkdir(parents=True)
    (data / "input.h5").write_bytes(b"synthetic data")
    remover = tools / "rm"
    remover.write_text(
        '#!/bin/bash\ntarget="${!#}"\ncase "${target##*/}" in\n'
        '  .omni-input.*)\n'
        '    if [[ "$CLEANUP_MODE" == delay ]]; then sleep 10; fi\n'
        '    exit 1 ;;\n'
        'esac\nexec /usr/bin/rm "$@"\n')
    remover.chmod(0o700)
    env = {"PATH": str(tools) + ":/usr/bin:/bin", "HOME": str(tmp_path),
           "APP_DIR": str(APP), "RESULTS_DIR": str(results), "ROOT": str(ROOT),
           "INPUT": str(data.parent), "CLEANUP_MODE": mode}
    # errexit matches the real application: cleanup must not stop the next command.
    cmd = 'set -euo pipefail; source "$ROOT/scripts/bk_functions.sh"; source "$APP_DIR/record_runtime.sh"; record_omnilearned_runtime "$INPUT"; echo FAKE_LAUNCHER'
    started = time.monotonic()
    run = subprocess.run(["bash", "-c", cmd], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=8)
    assert time.monotonic() - started < 7
    assert run.returncode == 0, run.stderr
    assert "FAKE_LAUNCHER" in run.stdout
    assert "cleanup incomplete" in run.stderr
    retained = list(results.glob(".omni-input.*"))
    assert len(retained) == 1
    assert (retained[0] / "input_info.json").is_file()
    recorded = json.loads((results / "input_info.json").read_text())["inputs"][0]
    assert recorded["observation_capture"]["collection_status"] == "recorded"
