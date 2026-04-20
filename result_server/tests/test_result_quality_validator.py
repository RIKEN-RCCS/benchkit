import json
import os
import subprocess
import sys
import importlib.util
from pathlib import Path


SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "scripts",
    "validate_result_quality.py",
)


def _load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "validate_result_quality_module",
        Path(SCRIPT_PATH),
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


def test_validator_reports_quality_and_actions(tmp_path):
    _write_json(
        tmp_path / "result_basic.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 1.0,
        },
    )

    completed = subprocess.run(
        [sys.executable, SCRIPT_PATH, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Scanned files: 1" in completed.stdout
    assert "[Basic]" in completed.stdout
    assert "policy-tier: strict" in completed.stdout
    assert "populate top-level source_info for provenance tracking" in completed.stdout
    assert "validator-candidate: source_info present" in completed.stdout
    assert "policy-candidate: source_info present" in completed.stdout


def test_validator_can_emit_json_and_skip_non_result_files(tmp_path):
    _write_json(
        tmp_path / "result_ready.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 1.0,
            "fom_breakdown": {
                "sections": [{"name": "solver", "time": 1.0, "estimation_package": "identity"}],
                "overlaps": [],
            },
        },
    )
    _write_json(tmp_path / "note.json", {"hello": "world"})

    completed = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--format", "json", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["scanned_files"] == 2
    assert payload["validated_results"] == 1
    assert payload["skipped_files"] == 1
    assert payload["default_tier"] == "relaxed"
    ready_row = next(row for row in payload["rows"] if row["status"] == "ok")
    assert ready_row["quality_level"] == "ready"
    assert ready_row["policy_tier"] == "strict"
    skipped_row = next(row for row in payload["rows"] if row["status"] == "skipped")
    assert "missing FOM or system" in skipped_row["reason"]


def test_validator_fail_on_candidate_returns_nonzero(tmp_path):
    _write_json(
        tmp_path / "result_basic.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 1.0,
        },
    )

    completed = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--fail-on", "candidate", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1


def test_validator_fail_on_policy_uses_internal_tier(tmp_path):
    _write_json(
        tmp_path / "result_genesis.json",
        {
            "code": "genesis",
            "system": "RC_GENOA",
            "FOM": 1.0,
            "source_info": {"source_type": "mystery"},
        },
    )

    completed = subprocess.run(
        [sys.executable, SCRIPT_PATH, "--fail-on", "policy", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "policy-tier: standard" in completed.stdout
    assert "policy-candidate: recognized source_info.source_type" in completed.stdout


def test_build_quality_report_applies_redis_tier_overrides(tmp_path, monkeypatch):
    module = _load_validator_module()
    _write_json(
        tmp_path / "result_qws.json",
        {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 1.0,
        },
    )

    monkeypatch.setattr(
        module,
        "_load_redis_app_tier_overrides",
        lambda redis_url, redis_key: {"qws": "relaxed"},
    )

    report = module.build_quality_report(
        [str(tmp_path)],
        redis_url="redis://example.invalid/0",
    )

    assert report["redis_override_count"] == 1
    assert report["redis_override_key"] == module.DEFAULT_REDIS_KEY
    row = next(row for row in report["rows"] if row["status"] == "ok")
    assert row["policy_tier"] == "relaxed"
    assert row["enforced_candidates"] == []
