"""Instance resolution stays independent of live stores, credentials, and Flask."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.instance_config import resolve_instance_settings
import trigger_runner


@pytest.mark.parametrize("name,prefix,identity", [
    ("main", "", "main"), ("dev1", "/dev", "dev"), ("dev2", "/dev2", "dev2"),
])
def test_instance_defaults_are_isolated(tmp_path, name, prefix, identity):
    root = tmp_path / "not-created"
    source = {"BASE_PATH": str(root), "RESULT_SERVER_INSTANCE": name}
    before = source.copy()
    settings = resolve_instance_settings(source)
    assert settings.data_dir == str(root / name)
    assert settings.profile_db_path == str(root / name / "cx_portal.sqlite3")
    assert settings.url_prefix == prefix
    assert settings.redis_prefix == identity + ":"
    assert settings.session_cookie_name == "session_" + identity
    assert source == before
    assert not root.exists()


@pytest.mark.parametrize("name", ["", "development", "../main", "/main"])
def test_no_implicit_production_instance(tmp_path, name):
    with pytest.raises(ValueError, match="RESULT_SERVER_INSTANCE"):
        resolve_instance_settings({"BASE_PATH": str(tmp_path), "RESULT_SERVER_INSTANCE": name})


def test_explicit_existing_references_are_preserved(tmp_path):
    source = {
        "RESULT_SERVER_INSTANCE": "dev2",
        "RESULT_SERVER_DATA_DIR": str(tmp_path / "separate-results"),
        "RESULT_SERVER_DB_PATH": str(tmp_path / "separate-profiles.sqlite3"),
        "RESULT_SERVER_REDIS_PREFIX": "custom:",
        "RESULT_SERVER_SESSION_COOKIE_NAME": "custom_session",
        "TOTP_ISSUER": "Example",
    }
    settings = resolve_instance_settings(source)
    assert settings.data_dir == source["RESULT_SERVER_DATA_DIR"]
    assert settings.profile_db_path == source["RESULT_SERVER_DB_PATH"]
    assert settings.redis_prefix == "custom:"
    assert settings.session_cookie_name == "custom_session"
    assert settings.totp_issuer == "Example-Dev2"


@pytest.mark.parametrize("extra", [
    {}, {"BASE_PATH": "relative"}, {"RESULT_SERVER_DATA_DIR": "relative"},
    {"RESULT_SERVER_DATA_DIR": "/example", "RESULT_SERVER_DB_PATH": "relative.db"},
])
def test_missing_or_relative_storage_is_rejected(extra):
    with pytest.raises(ValueError):
        resolve_instance_settings({"RESULT_SERVER_INSTANCE": "dev1", **extra})


def test_empty_mapping_does_not_use_process_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RESULT_SERVER_INSTANCE", "main")
    monkeypatch.setenv("BASE_PATH", str(tmp_path))
    with pytest.raises(ValueError, match="RESULT_SERVER_INSTANCE"):
        resolve_instance_settings({})


@pytest.mark.parametrize("name", ["main", "dev1", "dev2"])
def test_trigger_uses_same_instance_db_without_submitting(monkeypatch, tmp_path, name):
    monkeypatch.setenv("RESULT_SERVER_INSTANCE", name)
    monkeypatch.setenv("RESULT_SERVER_DATA_DIR", str(tmp_path / name))
    monkeypatch.delenv("RESULT_SERVER_DB_PATH", raising=False)
    calls = []
    monkeypatch.setattr(trigger_runner, "run_triggers", lambda **kw: calls.append(kw) or [])
    assert trigger_runner.main([]) == 0
    assert calls[0]["db_path"] == resolve_instance_settings().profile_db_path
    assert calls[0]["dry_run"] is True
    assert calls[0]["submit"] is False
    assert not (tmp_path / name).exists()


def test_trigger_preserves_explicit_legacy_db(monkeypatch, tmp_path):
    monkeypatch.delenv("RESULT_SERVER_INSTANCE", raising=False)
    calls = []
    monkeypatch.setattr(trigger_runner, "run_triggers", lambda **kw: calls.append(kw) or [])
    path = str(tmp_path / "legacy.sqlite3")
    assert trigger_runner.main(["--db", path]) == 0
    assert calls[0]["db_path"] == path


def test_trigger_without_instance_cannot_fall_back_to_main(monkeypatch):
    monkeypatch.delenv("RESULT_SERVER_INSTANCE", raising=False)
    monkeypatch.setenv("RESULT_SERVER_DB_PATH", "/not-to-be-opened.sqlite3")
    monkeypatch.setattr(trigger_runner, "run_triggers", lambda **kw: pytest.fail("must not open stores"))
    with pytest.raises(SystemExit) as error:
        trigger_runner.main([])
    assert error.value.code == 2
