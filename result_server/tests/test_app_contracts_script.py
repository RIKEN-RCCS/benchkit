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
    ("bk_build_source source main", True),
    ("bk_build_declared_source programs/demo/source.env", True),
    ("git clone source checkout", False),
])
def test_source_provenance_visible(tmp_path, monkeypatch, filename, script, expected):
    module = _load_script_module()
    app_dir = tmp_path / "demo"
    app_dir.mkdir()
    (app_dir / filename).write_text(script, encoding="utf-8")
    monkeypatch.setattr(module, "PROGRAMS_DIR", tmp_path)

    assert module.source_provenance_visible("demo") is expected


def _helper_fixture(tmp_path, monkeypatch):
    module = _load_script_module()
    app_dir = tmp_path / "programs" / "demo"
    app_dir.mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "PROGRAMS_DIR", tmp_path / "programs")
    return module, app_dir


@pytest.mark.parametrize("reference", [
    "source programs/demo/helper.sh",
    ". ./programs/demo/helper.sh",
    'source "${PWD}/programs/demo/helper.sh"',
    'source "$BK_BENCHKIT_ROOT/programs/demo/helper.sh"',
    'LOCAL_HELPERS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    'source "${LOCAL_HELPERS}/helper.sh"',
    'OTHER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    '. "$OTHER_DIR/helper.sh"',
    "bash programs/demo/helper.sh",
    "sh programs/demo/helper.sh",
    "source \\\n  programs/demo/helper.sh # local helper",
])
def test_input_provenance_follows_local_helper(tmp_path, monkeypatch, reference):
    module, app_dir = _helper_fixture(tmp_path, monkeypatch)
    (app_dir / "run.sh").write_text(reference)
    (app_dir / "helper.sh").write_text(
        "record_runtime() {\n  bk_record_input --directory data\n}\n"
    )
    assert module.input_provenance_visible("demo") is True


def test_input_provenance_nested_helpers_and_cycle(tmp_path, monkeypatch):
    module, app_dir = _helper_fixture(tmp_path, monkeypatch)
    (app_dir / "run.sh").write_text("source programs/demo/first.sh")
    (app_dir / "first.sh").write_text(
        "source programs/demo/run.sh\nsource programs/demo/second.sh"
    )
    (app_dir / "second.sh").write_text("bk_run --input-file input -- ./solver")
    assert module.input_provenance_visible("demo") is True
    (app_dir / "second.sh").write_text("echo no-recording")
    assert module.input_provenance_visible("demo") is False


@pytest.mark.parametrize("reference", [
    "echo helper.sh",
    "# source programs/demo/helper.sh",
    "source scripts/common.sh",
    "source programs/demo/../../scripts/common.sh",
    "source programs/demo/external.sh",
    "source programs/demo/loop.sh",
    "source programs/demo/missing.sh",
    'source "${UNKNOWN}/helper.sh"',
    'source "$(touch should-not-exist)/helper.sh"',
    'source "unterminated',
    'LOCAL_HELPERS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    'LOCAL_HELPERS=/elsewhere\nsource "$LOCAL_HELPERS/helper.sh"',
])
def test_input_provenance_ignores_unresolved_or_external_helpers(
    tmp_path, monkeypatch, reference,
):
    module, app_dir = _helper_fixture(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    (app_dir / "run.sh").write_text(reference)
    (app_dir / "helper.sh").write_text("bk_record_input --directory data")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    common = scripts_dir / "common.sh"
    common.write_text("bk_record_input() { :; }")
    (app_dir / "external.sh").symlink_to(common)
    (app_dir / "loop.sh").symlink_to("loop.sh")
    assert module.input_provenance_visible("demo") is False
    assert not (tmp_path / "should-not-exist").exists()


def test_unreadable_helper_does_not_fail_diagnostic(tmp_path, monkeypatch):
    module, app_dir = _helper_fixture(tmp_path, monkeypatch)
    (app_dir / "run.sh").write_text("source programs/demo/helper.sh")
    helper = app_dir / "helper.sh"
    helper.write_text("bk_record_input --directory data")
    read_text = Path.read_text

    def read_unless_helper(path, *args, **kwargs):
        if path == helper:
            raise PermissionError("unreadable synthetic helper")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_unless_helper)
    assert module.input_provenance_visible("demo") is False


def test_missing_hook_remains_nonblocking_notice(tmp_path, monkeypatch, capsys):
    module, app_dir = _helper_fixture(tmp_path, monkeypatch)
    (app_dir / "run.sh").write_text("source programs/demo/helper.sh")
    helper = app_dir / "helper.sh"
    helper.write_text("echo no-recording")
    monkeypatch.setattr(module, "changed_files", lambda: ["programs/demo/helper.sh"])
    monkeypatch.setattr(module, "build_site_diagnostics", lambda: {})
    assert module.main() == 0
    output = capsys.readouterr().out
    assert "::notice file=programs/demo/run.sh,title=Benchkit input provenance::" in output
    helper.write_text("bk_record_input --directory data")
    assert module.main() == 0
    assert "Benchkit input provenance" not in capsys.readouterr().out


def test_input_hook_flags_must_be_in_same_script(tmp_path, monkeypatch):
    module, app_dir = _helper_fixture(tmp_path, monkeypatch)
    (app_dir / "run.sh").write_text(
        "source programs/demo/helper.sh\nbk_run -- ./solver"
    )
    (app_dir / "helper.sh").write_text("./other --input-file input")
    assert module.input_provenance_visible("demo") is False
