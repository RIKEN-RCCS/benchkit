"""Exercise factory and legacy startup with temporary storage and fake Redis only."""

import os
import json
from pathlib import Path
import secrets
import subprocess
import sys

import pytest


def run_isolated(tmp_path, script, extra=None):
    root = Path(__file__).resolve().parents[2]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(root / "result_server"),
        "CASE_ROOT": str(tmp_path),
        **(extra or {}),
    }
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=root, env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_has_no_app_creation_or_secret_preflight(tmp_path):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from unittest.mock import patch
with patch("redis.from_url", side_effect=AssertionError("unexpected Redis setup")):
    import app
assert "app" not in vars(app) and "app_dev" not in vars(app)
assert not list(Path(os.environ["CASE_ROOT"]).iterdir())
''')


def test_public_site_information_factory_uses_only_explicit_public_fields(tmp_path):
    run_isolated(tmp_path, '''
from unittest.mock import patch
import fakeredis
from app import create_instance_app
with patch("redis.from_url", return_value=fakeredis.FakeRedis(decode_responses=True)):
    for surface in ("public", "console"):
        application = create_instance_app(surface)
        prefix = "/dev2" + ("/console" if surface == "console" else "")
        response = application.test_client().get(prefix + "/about")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert "Example operator" in page
        assert 'href="' + prefix + '/about"' in page
        assert "private-sentinel-not-public" not in page
''', {
        "BASE_PATH": str(tmp_path), "RESULT_SERVER_INSTANCE": "dev2",
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
        "RESULT_SERVER_PUBLIC_SITE_INFO": json.dumps({"operator": "Example operator"}),
        "PRIVATE_TEST_VALUE": "private-sentinel-not-public",
    })


def test_execution_history_links_keep_console_prefix_and_public_route_closed(tmp_path):
    run_isolated(tmp_path, '''
from unittest.mock import patch
import fakeredis
from app import create_instance_app
from utils.execution_profiles import ExecutionProfileStore
with patch("redis.from_url", return_value=fakeredis.FakeRedis(decode_responses=True)):
    public = create_instance_app("public")
    assert public.test_client().get("/dev2/admin/execution-profiles/history/manual/1/results").status_code == 404
    console = create_instance_app("console")
    store = ExecutionProfileStore(console.config["EXECUTION_PROFILE_DB_PATH"])
    record = store.create_execution_request(request_type="gitlab_pipeline", status="submitted",
        dry_run=False, profile_id="example", payload={
            "gitlab_project": "gitlab.example.org/group/project",
            "submit": {"response": {"id": 42}}})
    client = console.test_client()
    prefix = "/dev2/console/admin/execution-profiles"
    assert client.get(prefix + "/history/manual/1/results").status_code == 302
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["user_email"] = "admin@example.test"
        session["user_affiliations"] = ["admin"]
    page = client.get(prefix)
    assert page.status_code == 200
    assert 'action="' + prefix + '#execution-history"' in page.get_data(as_text=True)
    response = client.get(prefix + "/history/manual/" + str(record) + "/results")
    assert response.status_code == 200
    assert 'href="' + prefix + '#execution-history"' in response.get_data(as_text=True)
    assert "no-store" in response.headers["Cache-Control"]
''', {
        "BASE_PATH": str(tmp_path), "RESULT_SERVER_INSTANCE": "dev2",
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
    })


def test_invalid_public_site_information_fails_before_storage_creation(tmp_path):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from unittest.mock import patch
from app import create_instance_app
with patch("redis.from_url", side_effect=AssertionError("unexpected Redis setup")):
    try:
        create_instance_app("public")
    except ValueError as error:
        assert "private-sentinel" not in str(error)
        assert "RESULT_SERVER_PUBLIC_SITE_INFO" in str(error)
    else:
        raise AssertionError("invalid public settings accepted")
assert not list(Path(os.environ["CASE_ROOT"]).iterdir())
''', {
        "BASE_PATH": str(tmp_path), "RESULT_SERVER_INSTANCE": "dev2",
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
        "RESULT_SERVER_PUBLIC_SITE_INFO": '{"private-sentinel":"not-allowed"}',
    })


def test_opt_in_observation_receiver_has_no_startup_database_access(tmp_path):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from unittest.mock import patch
import fakeredis
from app import create_instance_app
root = Path(os.environ["CASE_ROOT"])
with patch("redis.from_url", return_value=fakeredis.FakeRedis(decode_responses=True)), \\
     patch("routes.runner_observation_ingest.RunnerObservations", side_effect=AssertionError("unexpected store access")):
    for surface in ("public", "console"):
        application = create_instance_app(surface)
        assert ("runner_observation_ingest" in application.blueprints) == (surface == "console")
        prefix = "/dev2" + ("/console" if surface == "console" else "")
        response = application.test_client().post(prefix + "/api/v1/runner-observations")
        assert response.status_code == (404 if surface == "public" else 401)
assert not (root / "absent.db").exists() and not (root / "absent.key").exists()
''', {
        "BASE_PATH": str(tmp_path), "RESULT_SERVER_INSTANCE": "dev2",
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
        "RESULT_SERVER_RUNNER_MONITOR_DB_PATH": str(tmp_path / "absent.db"),
        "RESULT_SERVER_RUNNER_MONITOR_KEY_FILE": str(tmp_path / "absent.key"),
        "RESULT_SERVER_GITLAB_TARGETS": "example=gitlab.example.org/group/project",
        "RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED": "true",
        "RESULT_SERVER_RUNNER_OBSERVATION_SOURCES": json.dumps({"example-source": {
            "collector_id": "example-collector", "generation": "11111111-1111-4111-8111-111111111111",
            "key_sha256": "0" * 64, "targets": [{"target_id": "example", "server_id": "example-server"}],
        }}),
    })


@pytest.mark.parametrize("name,prefix,identity", [
    ("main", "", "main"), ("dev1", "/dev", "dev"), ("dev2", "/dev2", "dev2"),
])
def test_public_console_and_trigger_share_only_the_selected_instance(tmp_path, name, prefix, identity):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from unittest.mock import patch
import fakeredis
from flask import url_for
from gunicorn.util import import_app
from utils.instance_config import resolve_instance_settings
root = Path(os.environ["CASE_ROOT"])
settings = resolve_instance_settings()
with patch("redis.from_url", return_value=fakeredis.FakeRedis(decode_responses=True)):
    from app import create_instance_app
    for surface in ("public", "console"):
        # The explicit surface, not a stale env flag, controls the public guard.
        os.environ["RESULT_SERVER_PUBLIC_PORTAL_MODE"] = "false" if surface == "public" else "true"
        application = import_app("app:create_instance_app(" + repr(surface) + ")")
        config = application.config
        assert config["EXECUTION_PROFILE_DB_PATH"] == settings.profile_db_path
        assert config["REDIS_PREFIX"] == os.environ["EXPECTED_IDENTITY"] + ":"
        assert config["SESSION_COOKIE_NAME"] == "session_" + os.environ["EXPECTED_IDENTITY"]
        assert config["TOTP_ISSUER"] == settings.totp_issuer
        assert Path(config["SESSION_CACHELIB"]._path) == Path(settings.data_dir) / "flask_session"
        assert Path(config["RECEIVED_DIR"]) == Path(settings.data_dir) / "received"
        assert config["BUDGET_REGISTRY_DB_PATH"] == str(root / "shared-budget.sqlite3")
        assert config["RUNNER_MONITOR_DB_PATH"] == str(root / "shared-runner.sqlite3")
        assert config["PUBLIC_PORTAL_MODE"] == (surface == "public")
        prefix = os.environ["EXPECTED_PREFIX"] + ("/console" if surface == "console" else "")
        with application.test_request_context():
            assert url_for("static", filename="x.css") == prefix + "/static/x.css"
        with application.test_client() as client:
            response = client.get(prefix + "/budgets/")
            assert response.status_code == (404 if surface == "public" else 302)
            if surface == "public":
                assert client.get(prefix + "/runners/").status_code == 404
    try:
        create_instance_app("invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid surface accepted")
assert {p.name for p in root.iterdir()} == {settings.name}
''', {
        "BASE_PATH": str(tmp_path),
        "RESULT_SERVER_INSTANCE": name,
        "EXPECTED_PREFIX": prefix,
        "EXPECTED_IDENTITY": identity,
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
        "RESULT_SERVER_BUDGET_DB_PATH": str(tmp_path / "shared-budget.sqlite3"),
        "RESULT_SERVER_BUDGET_DB_KEY_FILE": str(tmp_path / "absent-budget.key"),
        "RESULT_SERVER_RUNNER_MONITOR_DB_PATH": str(tmp_path / "shared-runner.sqlite3"),
        "RESULT_SERVER_RUNNER_MONITOR_KEY_FILE": str(tmp_path / "absent-runner.key"),
    })


@pytest.mark.parametrize("entry,name", [("app", "main"), ("app_dev", "dev1")])
def test_legacy_wsgi_only_creates_requested_instance(tmp_path, entry, name):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from unittest.mock import patch
import fakeredis
from gunicorn.util import import_app
with patch("redis.from_url", return_value=fakeredis.FakeRedis(decode_responses=True)):
    import app
    application = import_app("app:" + os.environ["ENTRY"])
    assert application is getattr(app, os.environ["ENTRY"])
assert {p.name for p in Path(os.environ["CASE_ROOT"]).iterdir()} == {os.environ["EXPECTED_NAME"]}
''', {
        "BASE_PATH": str(tmp_path), "ENTRY": entry, "EXPECTED_NAME": name,
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
    })


def test_direct_data_directory_and_identity_overrides_need_no_base_path(tmp_path):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from unittest.mock import patch
import fakeredis
from app import create_instance_app
with patch("redis.from_url", return_value=fakeredis.FakeRedis(decode_responses=True)):
    application = create_instance_app("console")
config = application.config
assert config["EXECUTION_PROFILE_DB_PATH"] == os.environ["RESULT_SERVER_DB_PATH"]
assert config["REDIS_PREFIX"] == "fixture:"
assert config["SESSION_COOKIE_NAME"] == "fixture_session"
assert config["RECEIVED_DIR"] == os.environ["RESULT_SERVER_DATA_DIR"] + "/received"
assert {p.name for p in Path(os.environ["CASE_ROOT"]).iterdir()} == {"kept-data"}
''', {
        "RESULT_SERVER_INSTANCE": "dev2",
        "RESULT_SERVER_DATA_DIR": str(tmp_path / "kept-data"),
        "RESULT_SERVER_DB_PATH": str(tmp_path / "separate.sqlite3"),
        "RESULT_SERVER_REDIS_PREFIX": "fixture:",
        "RESULT_SERVER_SESSION_COOKIE_NAME": "fixture_session",
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
    })


def test_factory_requires_instance_even_with_valid_secrets(tmp_path):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from app import create_instance_app
try:
    create_instance_app()
except ValueError:
    pass
else:
    raise AssertionError("unspecified instance accepted")
assert not list(Path(os.environ["CASE_ROOT"]).iterdir())
''', {
        "BASE_PATH": str(tmp_path),
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "fixture:" + secrets.token_hex(32),
    })


def test_invalid_secrets_still_fail_before_creating_data(tmp_path):
    run_isolated(tmp_path, '''
import os
from pathlib import Path
from app import create_instance_app
try:
    create_instance_app()
except SystemExit as error:
    assert error.code == 1
else:
    raise AssertionError("missing credentials accepted")
assert not list(Path(os.environ["CASE_ROOT"]).iterdir())
''', {"BASE_PATH": str(tmp_path), "RESULT_SERVER_INSTANCE": "dev2"})
