"""Standalone receiver startup uses synthetic configuration and no live stores."""

import configparser
import json
from pathlib import Path
import runpy
import shlex
import socket
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "result_server"))
from observation_app import create_app  # noqa: E402
from utils.runner_observation_service import ObservationServiceError, service_settings  # noqa: E402
from test_runner_observation_ingest import FakeRedis, KEY, PATH, settings  # noqa: E402
from test_runner_observation_protocol import batch, raw  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*_args, **_kwargs):
        raise AssertionError("unexpected socket connection")
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)


@pytest.fixture
def env(tmp_path):
    return settings(
        RESULT_SERVER_RUNNER_MONITOR_DB_PATH=str(tmp_path / "db/observations.sqlite3"),
        RESULT_SERVER_RUNNER_MONITOR_KEY_FILE=str(tmp_path / "keys/observations.key"),
        RESULT_SERVER_RUNNER_OBSERVATION_REDIS_SOCKET=str(tmp_path / "redis/redis.sock"),
        RESULT_SERVER_RUNNER_OBSERVATION_REDIS_PREFIX="fixture-observations:",
        RESULT_SERVER_RUNNER_OBSERVATION_PREFIX="/observations",
        RESULT_SERVER_RUNNER_OBSERVATION_BIND="127.0.0.1:8810",
        RESULT_SERVER_RUNNER_OBSERVATION_TLS_CERT_FILE=str(tmp_path / "tls/server.crt"),
        RESULT_SERVER_RUNNER_OBSERVATION_TLS_KEY_FILE=str(tmp_path / "tls/server.key"),
    )


@pytest.mark.parametrize("field", [
    "RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED", "RESULT_SERVER_GITLAB_TARGETS",
    "RESULT_SERVER_RUNNER_OBSERVATION_SOURCES", "RESULT_SERVER_RUNNER_MONITOR_DB_PATH",
    "RESULT_SERVER_RUNNER_MONITOR_KEY_FILE", "RESULT_SERVER_RUNNER_OBSERVATION_REDIS_SOCKET",
    "RESULT_SERVER_RUNNER_OBSERVATION_REDIS_PREFIX", "RESULT_SERVER_RUNNER_OBSERVATION_BIND",
    "RESULT_SERVER_RUNNER_OBSERVATION_TLS_CERT_FILE", "RESULT_SERVER_RUNNER_OBSERVATION_TLS_KEY_FILE",
])
def test_missing_configuration_cannot_start(env, field):
    del env[field]
    with pytest.raises(ObservationServiceError, match="^observation_service_configuration_unavailable$"):
        create_app(env)


@pytest.mark.parametrize("field, value", [
    ("RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED", "false"),
    ("RESULT_SERVER_PUBLIC_PORTAL_MODE", "true"),
    ("RESULT_SERVER_RUNNER_MONITOR_DB_PATH", "relative.db"),
    ("RESULT_SERVER_RUNNER_MONITOR_KEY_FILE", "/example/../key"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_REDIS_SOCKET", "redis.sock"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_REDIS_PREFIX", ""),
    ("RESULT_SERVER_RUNNER_OBSERVATION_REDIS_PREFIX", "without-colon"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_PREFIX", "/../admin"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_PREFIX", "/observations/"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_PREFIX", "/observations?query"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_PREFIX", None),
    ("RESULT_SERVER_RUNNER_OBSERVATION_BIND", "0.0.0.0:8810"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_BIND", "localhost:8810"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_BIND", "127.0.0.1:0"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_BIND", "127.0.0.1:65536"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_TLS_CERT_FILE", ""),
    ("RESULT_SERVER_RUNNER_OBSERVATION_TLS_KEY_FILE", "relative.key"),
    ("RESULT_SERVER_RUNNER_OBSERVATION_SOURCES", "synthetic-private-value"),
])
def test_invalid_configuration_is_value_free(env, field, value):
    env[field] = value
    with pytest.raises(ObservationServiceError) as error:
        create_app(env)
    assert str(error.value) == "observation_service_configuration_unavailable"


@pytest.mark.parametrize("other", ["database", "key", "redis", "certificate"])
def test_aliased_sensitive_paths_rejected(env, other):
    reference = service_settings(env)
    env["RESULT_SERVER_RUNNER_OBSERVATION_TLS_KEY_FILE"] = {
        "database": reference.database, "key": reference.key_file,
        "redis": reference.redis_socket, "certificate": reference.certificate,
    }[other]
    with pytest.raises(ObservationServiceError):
        create_app(env)


def test_db_key_must_be_in_a_separate_directory(env):
    env["RESULT_SERVER_RUNNER_MONITOR_KEY_FILE"] = str(Path(env["RESULT_SERVER_RUNNER_MONITOR_DB_PATH"]).with_name("key"))
    with pytest.raises(ObservationServiceError):
        create_app(env)


def test_target_catalog_does_not_fall_back_to_a_portal_repo(env):
    env["RESULT_SERVER_GITLAB_TARGETS"] = " "
    env["RESULT_SERVER_GITLAB_REPO"] = "gitlab.example.org/unrelated/project.git"
    with pytest.raises(ObservationServiceError):
        create_app(env)


def test_factory_does_not_initialize_or_connect(env, monkeypatch, tmp_path):
    from utils import encrypted_sqlite
    import sqlite3
    original = dict(env)
    env.update(BASE_PATH=str(tmp_path / "unused-portal"), RESULT_SERVER_INSTANCE="main",
               RESULT_SERVER_DB_PATH=str(tmp_path / "unused-profile.db"),
               REDIS_URL="redis://unused.example.org", FLASK_SECRET_KEY="unused-browser-secret")

    def reject(*_args, **_kwargs):
        raise AssertionError("unexpected storage initialization")
    monkeypatch.setattr(encrypted_sqlite, "_read_key", reject)
    monkeypatch.setattr(sqlite3, "connect", reject)
    monkeypatch.setattr(Path, "mkdir", reject)
    app = create_app(env)
    assert app.secret_key is None and "USER_STORE" not in app.config
    assert "EXECUTION_PROFILE_DB_PATH" not in app.config
    assert app.config["REDIS_CONN"].connection_pool.connection_kwargs["path"] == original["RESULT_SERVER_RUNNER_OBSERVATION_REDIS_SOCKET"]
    assert app.config["REDIS_PREFIX"] == original["RESULT_SERVER_RUNNER_OBSERVATION_REDIS_PREFIX"]
    assert list(tmp_path.iterdir()) == []
    assert set(app.blueprints) == {"runner_observation_ingest"}
    assert {rule.rule for rule in app.url_map.iter_rules()} == {"/observations" + PATH}
    assert app.test_client().get("/observations/static/test.js").status_code == 404


def test_cleartext_and_forged_forwarded_headers_never_reach_storage(env, monkeypatch):
    import routes.runner_observation_ingest as receiver
    monkeypatch.setattr(receiver, "RunnerObservations", lambda *_args: pytest.fail("cleartext store access"))
    app = create_app(env)
    response = app.test_client().post("/observations" + PATH, data=raw(batch()), content_type="application/json",
                                      headers={"X-Collector-Key": KEY, "X-Forwarded-Proto": "https"})
    assert response.status_code == 400 and response.json == {"error": "https_required"}


def test_dedicated_auth_and_missing_storage_remain_closed(env, monkeypatch):
    app = create_app(env)
    app.config["REDIS_CONN"] = FakeRedis()
    client = app.test_client()
    assert client.post("/observations" + PATH, base_url="https://localhost", data=raw(batch()),
                       content_type="application/json", headers={"X-API-Key": KEY}).status_code == 401
    response = client.post("/observations" + PATH, base_url="https://localhost", data=raw(batch()),
                           content_type="application/json", headers={"X-Collector-Key": KEY})
    assert response.status_code == 503 and response.json == {"error": "observation_storage_unavailable"}
    assert not Path(env["RESULT_SERVER_RUNNER_MONITOR_DB_PATH"]).exists()


def test_gunicorn_configuration_and_factory_share_settings(env, monkeypatch):
    from gunicorn.config import Config
    from gunicorn.util import import_app
    for key in list(__import__("os").environ):
        if key.startswith("RESULT_SERVER_"):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    values = runpy.run_path(str(ROOT / "result_server/observation_gunicorn.py"))
    config = Config()
    for key in ("bind", "certfile", "keyfile", "workers", "timeout", "graceful_timeout",
                "preload_app", "accesslog", "errorlog", "forwarded_allow_ips", "secure_scheme_headers"):
        config.set(key, values[key])
    assert config.bind == ["127.0.0.1:8810"] and config.workers == 1
    assert config.accesslog is None and config.secure_scheme_headers == {}
    assert config.forwarded_allow_ips == []
    assert config.certfile == env["RESULT_SERVER_RUNNER_OBSERVATION_TLS_CERT_FILE"]
    assert config.keyfile == env["RESULT_SERVER_RUNNER_OBSERVATION_TLS_KEY_FILE"]
    app = import_app("observation_app:create_app()")
    assert set(app.blueprints) == {"runner_observation_ingest"}


@pytest.mark.parametrize("portal_stubs_first", [False, True])
def test_no_portal_modules_imported_in_a_fresh_process(env, tmp_path, portal_stubs_first):
    code = '''
import builtins, json, sys
sys.path.insert(0, sys.argv[1])
if sys.argv[3] == "True":
    from test_support import install_portal_test_stubs
    install_portal_test_stubs(include_otp=False)
original = builtins.__import__
def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and (name in {"app", "app_dev", "routes.api", "utils.execution_profiles", "utils.user_store", "sqlcipher3"} or name.startswith(("flask_session", "cachelib"))):
        raise AssertionError("Portal dependency imported")
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = guarded
import observation_app
app = observation_app.create_app(json.loads(sys.argv[2]))
assert set(app.blueprints) == {"runner_observation_ingest"}
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT / "result_server"), json.dumps(env), str(portal_stubs_first)],
                            cwd=tmp_path, env={"HOME": str(tmp_path)}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_deployment_examples_are_scoped_and_not_installers():
    directory = ROOT / "deploy/runner-observations"
    receiver = configparser.ConfigParser(interpolation=None)
    receiver.read(directory / "receiver.service.example")
    assert receiver["Service"]["UMask"] == "0077"
    assert "observation_app:create_app()" in receiver["Service"]["ExecStart"]
    assert "observation-api" in receiver["Service"]["EnvironmentFile"]
    collector = configparser.ConfigParser(interpolation=None)
    collector.read(directory / "collector.service.example")
    assert "EnvironmentFile" not in collector["Service"]
    assert "collector_cli.py collect --config" in collector["Service"]["ExecStart"]
    assert "SSL_CERT_FILE" in collector["Service"]["Environment"]
    env = {}
    for line in (directory / "receiver.env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key] = shlex.split(value)[0]
    assert service_settings(env).bind == "127.0.0.1:8810"
