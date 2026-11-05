"""Tests for local-development launcher safety guards."""

import os
from pathlib import Path
import subprocess
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


def test_create_dev_app_configures_execution_profile_db(tmp_path):
    # The dev factory intentionally installs process-wide authentication stubs.
    # Keep that process separate from tests exercising real authentication.
    names = ("redis", "utils.totp_manager", "routes.auth")
    before = {name: sys.modules.get(name) for name in names}
    script = '''
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import app_dev
root = Path(sys.argv[2])
app_dev.setup_dev_environment(str(root))
app = app_dev.create_dev_app(str(root))
assert app.config['EXECUTION_PROFILE_DB_PATH'] == str(root / 'cx_portal.sqlite3')
assert app.config['SESSION_TYPE'] == 'cachelib'
assert app.config['SESSION_CACHELIB']._path == str(root / 'main' / 'flask_session')
'''
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("RESULT_SERVER_") and key not in ("PYTHONPATH", "FLASK_SECRET_KEY")}
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script,
                             str(Path(__file__).resolve().parents[1]), str(tmp_path)],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert {name: sys.modules.get(name) for name in names} == before
