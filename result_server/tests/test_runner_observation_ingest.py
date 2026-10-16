"""Receiver authentication and HTTP boundaries with a fake observation store."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from flask import Flask, jsonify
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import runner_observation_ingest as receiver  # noqa: E402
from utils.csrf import init_csrf  # noqa: E402
from utils.encrypted_sqlite import EncryptedDatabaseError  # noqa: E402
from utils.portal_access import ACCESS_COLLECTOR_API, classify_endpoint, register_public_portal_guard  # noqa: E402
from utils.runner_observation_auth import (  # noqa: E402
    ObservationConfigurationError, authenticate_observation_key, configured_observation_sources,
)
from utils.runner_observation_protocol import ProtocolError  # noqa: E402
from test_runner_observation_protocol import GENERATION, NOW, batch, policy, raw  # noqa: E402


KEY = "synthetic-observation-key-not-a-secret-1234"
INGEST_KEY = "synthetic-result-key-not-a-secret-123456"
PATH = "/api/v1/runner-observations"


def source_settings():
    return {"source": {"collector_id": "collector", "generation": GENERATION,
                       "key_sha256": hashlib.sha256(KEY.encode()).hexdigest(),
                       "targets": [{"target_id": "first", "server_id": "server"}]}}


def settings(**overrides):
    return {"RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED": "true",
            "RESULT_SERVER_RUNNER_OBSERVATION_SOURCES": json.dumps(source_settings()),
            "RESULT_SERVER_GITLAB_TARGETS": "first=gitlab.example.org/group/first.git", **overrides}


class FakeRedis:
    def __init__(self):
        self.counts = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, _key, _seconds):
        return True


@pytest.fixture
def portal(tmp_path, monkeypatch):
    calls = []
    opens = []

    class FakeStore:
        def __init__(self, path, key):
            assert Path(path).is_relative_to(tmp_path) and Path(key).is_relative_to(tmp_path)
            opens.append(path)

        def ingest(self, data, scope, *, received_at):
            calls.append((data, scope, received_at))
            return SimpleNamespace(acknowledgement={"status": "accepted", "sequence": 1})

    monkeypatch.setattr(receiver, "RunnerObservations", FakeStore)
    monkeypatch.setattr(receiver, "datetime", SimpleNamespace(now=lambda _tz: NOW))

    def make(env=None, *, public=False, prefix=""):
        app = Flask(__name__)
        app.secret_key = "synthetic-session-secret"
        app.config.update(TESTING=True, PUBLIC_PORTAL_MODE=public, REDIS_CONN=FakeRedis(),
                          AUTH_REQUIRES_REDIS=True, RUNNER_MONITOR_DB_PATH=str(tmp_path / "observations.db"),
                          RUNNER_MONITOR_KEY_FILE=str(tmp_path / "key"), INGEST_KEYS={INGEST_KEY: "runner"})
        app.config["TEST_STORE_OPENS"] = opens
        register_public_portal_guard(app)
        receiver.register_runner_observation_ingest(app, prefix, env=settings() if env is None else env)
        init_csrf(app, exempt_blueprints=(receiver.runner_observation_ingest_bp,))

        @app.post("/browser")
        def browser():
            return jsonify(ok=True)

        return app, calls

    return make


def post(app, value=None, **kwargs):
    return app.test_client().post(PATH, data=raw(batch() if value is None else value),
                                  content_type="application/json", headers={"X-Collector-Key": KEY}, **kwargs)


@pytest.mark.parametrize("prefix", ["", "/preview/console"])
def test_valid_request_uses_dedicated_policy_without_csrf(portal, prefix):
    app, calls = portal(prefix=prefix)
    response = app.test_client().post(prefix + PATH, data=raw(batch()), content_type="application/json",
                                      headers={"X-Collector-Key": KEY})
    assert response.status_code == 200 and response.json["status"] == "accepted"
    assert response.headers["Cache-Control"] == "no-store"
    assert calls[0][1] == policy() and calls[0][2] == NOW
    assert classify_endpoint("runner_observation_ingest.ingest") == ACCESS_COLLECTOR_API
    assert app.test_client().post("/browser").status_code == 400


@pytest.mark.parametrize("headers", [
    {}, {"X-API-Key": INGEST_KEY}, {"X-Collector-Key": INGEST_KEY},
    {"X-Result-Server-Client-Verify": "SUCCESS", "X-Result-Server-Client-DN": "fixture"},
    {"X-Collector-Key": "non-ascii-\u00e9"}, {"X-Collector-Key": "x" * 257},
    {"X-Collector-Key": KEY + "," + KEY},
])
def test_other_authentication_never_opens_store(portal, headers):
    app, calls = portal()
    app.config["TRUSTED_PROXY_AUTH"] = "mtls"
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(authenticated=True, user_email="admin@example.org")
    response = client.post(PATH, data=raw(batch()), content_type="application/json", headers=headers)
    assert response.status_code == 401 and response.json == {"error": "invalid_collector_key"}
    assert calls == [] and not app.config["TEST_STORE_OPENS"] and not app.config["REDIS_CONN"].counts


def test_observation_key_is_not_a_result_key(portal):
    from routes.api import api_bp

    app, calls = portal()
    app.register_blueprint(api_bp)
    response = app.test_client().get("/api/query/result", headers={"X-API-Key": KEY})
    assert response.status_code == 401 and calls == []


@pytest.mark.parametrize("public, env", [(False, {}), (True, settings())])
def test_disabled_or_public_receiver_is_not_registered(portal, public, env):
    app, calls = portal(env, public=public)
    assert "runner_observation_ingest" not in app.blueprints
    for method in ("GET", "POST", "OPTIONS"):
        assert app.test_client().open(PATH, method=method).status_code == 404
    assert calls == []


@pytest.mark.parametrize("value, status", [
    (batch(source_id="another"), 403), (batch(schema_version=2), 422),
    (batch(targets=[]), 422),
])
def test_rejected_payload_does_not_open_store(portal, value, status):
    app, calls = portal()
    assert post(app, value).status_code == status
    assert calls == [] and not app.config["TEST_STORE_OPENS"]


def test_body_size_media_and_compression_limits(portal):
    app, calls = portal()
    client = app.test_client()
    assert client.post(PATH, data=raw(batch()), headers={"X-Collector-Key": KEY}).status_code == 415
    assert client.post(PATH, data=raw(batch()), content_type="application/json",
                       headers={"X-Collector-Key": KEY, "Content-Encoding": "gzip"}).status_code == 415
    data = b" " * (receiver.MAX_BYTES + 1)
    for overrides in ({}, {"CONTENT_LENGTH": "", "wsgi.input_terminated": True}):
        response = client.post(PATH, data=data, content_type="application/json",
                               headers={"X-Collector-Key": KEY}, environ_overrides=overrides)
        assert response.status_code == 413
    assert calls == []


def test_stricter_app_limit_keeps_the_receiver_error_format(portal):
    app, calls = portal()
    app.config["MAX_CONTENT_LENGTH"] = 1

    @app.errorhandler(413)
    def global_limit(_error):
        return jsonify(error="global-limit-format"), 413

    response = post(app)
    assert response.status_code == 413 and response.json == {"error": "payload_too_large"}
    assert calls == []


def test_storage_configuration_failure_and_errors_are_value_free(portal, monkeypatch, caplog):
    app, calls = portal()
    app.config["RUNNER_MONITOR_KEY_FILE"] = ""
    assert post(app).status_code == 503 and calls == []
    app.config["RUNNER_MONITOR_KEY_FILE"] = "unused-fixture-key"

    class Unavailable:
        def __init__(self, *_args):
            raise EncryptedDatabaseError("synthetic-private-path-and-key")

    monkeypatch.setattr(receiver, "RunnerObservations", Unavailable)
    response = post(app)
    assert response.status_code == 503
    assert response.json == {"error": "observation_storage_unavailable"}
    assert "synthetic-private" not in response.text + caplog.text
    assert KEY not in response.text + caplog.text


def test_rate_limit_and_backend_failure_are_closed(portal):
    app, calls = portal()
    app.config["RATE_LIMITS"] = {"runner_observation": 1}
    assert post(app).status_code == 200
    assert post(app).status_code == 429 and len(calls) == 1
    app.config["REDIS_CONN"] = None
    assert post(app).status_code == 503 and len(calls) == 1


def test_invalid_settings_cannot_activate_a_fallback(portal):
    app, calls = portal(settings(RESULT_SERVER_RUNNER_OBSERVATION_SOURCES="private-invalid-json"))
    response = post(app)
    assert response.status_code == 503 and response.json == {"error": "observation_configuration_unavailable"}
    assert calls == [] and "private-invalid" not in response.text


def test_reusing_a_result_key_cannot_activate_the_receiver(portal):
    spec = source_settings()
    spec["source"]["key_sha256"] = hashlib.sha256(INGEST_KEY.encode()).hexdigest()
    app, calls = portal(settings(RESULT_SERVER_RUNNER_OBSERVATION_SOURCES=json.dumps(spec)))
    response = post(app)
    assert response.status_code == 503 and calls == [] and not app.config["TEST_STORE_OPENS"]


@pytest.mark.parametrize("mutate", [
    lambda s: s["source"].update(token="do-not-log"),
    lambda s: s["source"].update(key_sha256="bad"),
    lambda s: s["source"].update(targets=[{"target_id": "missing", "server_id": "server"}]),
    lambda s: s["source"]["targets"][0].update(server_url="https://not-allowed.example.org"),
    lambda s: s["source"]["targets"][0].update(runner_types=["bad"]),
    lambda s: s.update(other={**deepcopy(s["source"]), "key_sha256": "a" * 64}),
])
def test_invalid_source_configuration_has_fixed_errors(mutate):
    spec = source_settings()
    mutate(spec)
    with pytest.raises(ObservationConfigurationError, match="^observation_configuration_unavailable$"):
        configured_observation_sources(settings(RESULT_SERVER_RUNNER_OBSERVATION_SOURCES=json.dumps(spec)))


def test_duplicate_json_keys_and_invalid_catalog_are_rejected():
    with pytest.raises(ObservationConfigurationError):
        configured_observation_sources(settings(RESULT_SERVER_RUNNER_OBSERVATION_SOURCES='{"x":{},"x":{}}'))
    for catalog in ("first=https://gitlab.example.org/group/p", "first=gitlab.example.org/group/p?secret=x",
                    "first=gitlab.example.org/group/p#fragment", "first=gitlab.example.org/group/p,first=other/p"):
        with pytest.raises(ObservationConfigurationError):
            configured_observation_sources(settings(RESULT_SERVER_GITLAB_TARGETS=catalog))


def test_only_dedicated_verifier_authenticates_and_repr_does_not_show_it():
    sources = configured_observation_sources(settings())
    assert authenticate_observation_key(KEY, sources) == policy()
    assert sources[0].key_sha256 not in repr(sources[0])
    with pytest.raises(ProtocolError):
        authenticate_observation_key(INGEST_KEY, sources)
