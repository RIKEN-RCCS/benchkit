"""Tests for app contract warning helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tests" / "check_app_contracts.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("check_app_contracts", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_input_provenance_visible_accepts_common_helper(tmp_path, monkeypatch):
    module = _load_script_module()
    programs_dir = tmp_path / "programs"
    app_dir = programs_dir / "demo"
    app_dir.mkdir(parents=True)
    (app_dir / "run.sh").write_text(
        "source scripts/bk_functions.sh\nbk_record_input_info metadata.json\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PROGRAMS_DIR", programs_dir)

    assert module.input_provenance_visible("demo") is True
