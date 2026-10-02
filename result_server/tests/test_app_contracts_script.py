"""Tests for app contract warning helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tests" / "check_app_contracts.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("check_app_contracts", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script, expected", [
    ("bk_record_input_info metadata.json", True),
    ("bk_record_input --directory input", True),
    ("bk_run --log output --input-file input.nml -- ./solver", True),
    ("bk_run --log output \\\n  --parameter-input -- ./solver 3", True),
    ("bk_run --log output -- ./solver", False),
    ("./solver --input-file input.nml", False),
    ("", False),
])
def test_input_provenance_visible(tmp_path, monkeypatch, script, expected):
    module = _load_script_module()
    programs_dir = tmp_path / "programs"
    app_dir = programs_dir / "demo"
    app_dir.mkdir(parents=True)
    (app_dir / "run.sh").write_text(
        f"source scripts/bk_functions.sh\n{script}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PROGRAMS_DIR", programs_dir)

    assert module.input_provenance_visible("demo") is expected


@pytest.mark.parametrize("filename", ["build.sh", "run.sh"])
@pytest.mark.parametrize("script, expected", [
    ("bk_fetch_source source checkout main", True),
    ("bk_fetch_recorded_source source checkout main", True),
    ("git clone source checkout", False),
])
def test_source_provenance_visible(tmp_path, monkeypatch, filename, script, expected):
    module = _load_script_module()
    app_dir = tmp_path / "demo"
    app_dir.mkdir()
    (app_dir / filename).write_text(script, encoding="utf-8")
    monkeypatch.setattr(module, "PROGRAMS_DIR", tmp_path)

    assert module.source_provenance_visible("demo") is expected
