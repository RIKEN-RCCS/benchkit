"""Tests for the lightweight Result/Estimate JSON contract validator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_result_json.py"

spec = importlib.util.spec_from_file_location("validate_result_json", VALIDATOR_PATH)
validator = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = validator
spec.loader.exec_module(validator)


def severities(issues):
    return [issue.severity for issue in issues]


def messages(issues):
    return [issue.message for issue in issues]


def test_valid_result_payload_has_no_errors():
    payload = {
        "code": "qws",
        "system": "Fugaku",
        "FOM": "74.804",
        "FOM_unit": "s",
        "FOM_version": "v1",
        "Exp": "p8",
        "node_count": "1",
        "numproc_node": "48",
        "nthreads": "1",
        "source_info": {
            "source_type": "git",
            "repo_url": "https://example.org/app.git",
            "branch": "main",
            "commit_hash": "0123456789abcdef0123456789abcdef01234567",
            "resolved_commit": "0123456789abcdef0123456789abcdef01234567",
        },
        "input_info": {
            "schema_version": 1,
            "kind": "repo-local-input",
            "source": "source_info",
            "repo_relative_path": "inputs/case0",
            "verification_status": "covered_by_source_commit",
        },
        "pipeline_timing": {"build_time": 10, "queue_time": 0, "run_time": 42.5},
        "build_cache": {"status": "hit", "stored": False, "entry": {}},
    }

    _, issues = validator.validate_payload(Path("result.json"), payload)

    assert "error" not in severities(issues)
    assert "warning" not in severities(issues)


def test_result_payload_reports_required_field_errors_and_optional_notices():
    payload = {
        "code": "qws",
        "system": "Fugaku",
        "FOM_unit": "s",
        "FOM_version": "v1",
        "Exp": "p8",
        "node_count": "1",
        "numproc_node": "48",
        "nthreads": "1",
        "source_info": None,
    }

    _, issues = validator.validate_payload(Path("result.json"), payload)

    assert "error" in severities(issues)
    assert any("required field is missing" in message for message in messages(issues))
    assert any(issue.path == "$.source_info" and issue.severity == "notice" for issue in issues)
    assert any(issue.path == "$.input_info" and issue.severity == "notice" for issue in issues)


def test_valid_estimate_payload_has_no_errors():
    benchmark = {
        "system": "Fugaku",
        "fom": 74.804,
        "nodes": "1",
        "numproc_node": "48",
        "timestamp": "2026-09-05 00:16:04",
        "uuid": "11111111-2222-3333-4444-555555555555",
    }
    payload = {
        "code": "genesis",
        "exp": "p8",
        "current_system": {
            "system": "Fugaku",
            "fom": 74.804,
            "target_nodes": "2",
            "scaling_method": "weakscaling",
            "benchmark": benchmark,
        },
        "future_system": {
            "system": "FugakuNEXT",
            "fom": 43.989,
            "target_nodes": "1",
            "scaling_method": "instr-app-sec",
            "benchmark": {**benchmark, "system": "MiyabiG"},
        },
        "performance_ratio": 1.7,
        "estimate_metadata": {
            "estimation_package": "instrumented_app_sections",
            "source_result": {
                "uuid": "11111111-2222-3333-4444-555555555555",
                "input_info": {"kind": "repo-local-input"},
            },
        },
        "estimation_timing": {"elapsed_time": 8, "unit": "s"},
        "applicability": {"status": "applicable"},
    }

    _, issues = validator.validate_payload(Path("estimate.json"), payload)

    assert "error" not in severities(issues)
    assert "warning" not in severities(issues)


def test_estimate_payload_reports_missing_benchmark_fields():
    payload = {
        "code": "genesis",
        "exp": "p8",
        "current_system": {
            "system": "Fugaku",
            "fom": 74.804,
            "target_nodes": "2",
            "scaling_method": "weakscaling",
            "benchmark": {},
        },
        "future_system": {
            "system": "FugakuNEXT",
            "fom": "not-a-number",
            "target_nodes": "1",
            "scaling_method": "weakscaling",
            "benchmark": {},
        },
        "performance_ratio": "not-a-number",
        "applicability": {"status": "unexpected-status"},
    }

    _, issues = validator.validate_payload(Path("estimate.json"), payload)

    assert "error" in severities(issues)
    assert "warning" in severities(issues)
    assert any(issue.path == "$.performance_ratio" for issue in issues)
    assert any(issue.path.endswith(".benchmark.uuid") for issue in issues)
    assert any(issue.path == "$.applicability.status" for issue in issues)


def test_cli_accepts_directory_and_fails_on_errors(tmp_path):
    valid = tmp_path / "result_valid.json"
    invalid = tmp_path / "result_invalid.json"
    valid.write_text(
        json.dumps(
            {
                "code": "qws",
                "system": "Fugaku",
                "FOM": 1.0,
                "FOM_unit": "s",
                "FOM_version": "v1",
                "Exp": "case0",
                "node_count": "1",
                "numproc_node": "48",
                "nthreads": "1",
                "source_info": None,
            }
        ),
        encoding="utf-8",
    )
    invalid.write_text(json.dumps({"code": "qws", "system": "Fugaku"}), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), str(tmp_path), "--quiet"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 1
    assert str(invalid) in result.stdout
    assert "required field is missing" in result.stdout
