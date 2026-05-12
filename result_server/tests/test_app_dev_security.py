"""Tests for local-development launcher safety guards."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app_dev


def test_setup_dev_environment_uses_ephemeral_missing_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("RESULT_SERVER_KEYS", raising=False)
    monkeypatch.delenv("RESULT_SERVER_KEY", raising=False)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)

    with pytest.warns(RuntimeWarning):
        app_dev.setup_dev_environment(str(tmp_path))

    assert os.environ["RESULT_SERVER_KEYS"].startswith("local-dev:")
    assert os.environ["RESULT_SERVER_KEYS"] != "local-dev:dev-api-key"
    assert os.environ["FLASK_SECRET_KEY"] != "dev-secret-key"


def test_dev_debug_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("RESULT_SERVER_DEV_DEBUG", raising=False)
    assert app_dev.dev_debug_enabled() is False

    monkeypatch.setenv("RESULT_SERVER_DEV_DEBUG", "1")
    assert app_dev.dev_debug_enabled() is True


def test_validate_dev_runtime_rejects_non_loopback_host(monkeypatch):
    monkeypatch.delenv("FLASK_ENV", raising=False)
    unsafe_host = ".".join(["0", "0", "0", "0"])
    with pytest.raises(SystemExit):
        app_dev.validate_dev_runtime(unsafe_host)


def test_validate_dev_runtime_rejects_production_env(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    with pytest.raises(SystemExit):
        app_dev.validate_dev_runtime("127.0.0.1")
