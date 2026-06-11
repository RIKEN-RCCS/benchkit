"""Tests for structured audit logging."""

import json
import logging
import os
import shutil
import sys
import tempfile

from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_api_route_app, build_portal_route_app, install_portal_test_stubs
from utils.audit_logging import JsonAuditFormatter, audit_event, configure_audit_logging

install_portal_test_stubs()

API_KEY = "test-api-key-12345678901234567890"
WRONG_API_KEY = "wrong-api-key-should-not-appear"


class _Store:
    def __init__(self):
        self._users = {
            "admin@test.com": {
                "email": "admin@test.com",
                "totp_secret": "SECRET",
                "affiliations": ["admin"],
            },
            "second-admin@test.com": {
                "email": "second-admin@test.com",
                "totp_secret": "SECRET2",
                "affiliations": ["admin"],
            },
        }

    def get_user(self, email):
        return self._users.get(email)

    def list_users(self):
        return list(self._users.values())

    def has_totp_secret(self, email):
        user = self._users.get(email)
        return bool(user and user.get("totp_secret"))

    def delete_user(self, email):
        return self._users.pop(email, None) is not None

    def user_exists(self, email):
        return email in self._users

    def get_affiliations(self, email):
        user = self._users.get(email)
        return user["affiliations"] if user else []

    def update_affiliations(self, email, affiliations):
        if email in self._users:
            self._users[email]["affiliations"] = list(affiliations)
            return True
        return False

    def clear_totp_secret(self, email):
        if email in self._users:
            self._users[email]["totp_secret"] = ""
            return True
        return False

    def create_invitation(self, email, affiliations):
        return "token-1"


def _api_app():
    received = tempfile.mkdtemp()
    received_padata = tempfile.mkdtemp()
    received_estimation_artifacts = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_api_route_app(
        received_dir=received,
        received_padata_dir=received_padata,
        received_estimation_artifacts_dir=received_estimation_artifacts,
        estimated_dir=estimated,
    )
    app.config["INGEST_KEYS"] = {API_KEY: "test-runner"}
    return app, (received, received_padata, received_estimation_artifacts, estimated)


def _portal_app():
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=received,
        estimated_dir=estimated,
        user_store=_Store(),
    )
    return app, (received, estimated)


def _cleanup(paths):
    for path in paths:
        shutil.rmtree(path)


def _audit_records(caplog, event_type):
    return [
        record
        for record in caplog.records
        if getattr(record, "audit_event_type", None) == event_type
    ]


def test_invalid_api_key_emits_audit_failure_without_key_value(caplog):
    app, temp_dirs = _api_app()
    try:
        with app.test_client() as client, caplog.at_level(logging.INFO, logger="benchkit.audit"):
            resp = client.post(
                "/api/ingest/result",
                data=b'{"code":"test"}',
                headers={"X-API-Key": WRONG_API_KEY, "Content-Type": "application/json"},
            )

        assert resp.status_code == 401
        records = _audit_records(caplog, "api_auth_failed")
        assert len(records) == 1
        fields = records[0].audit_fields
        assert fields["endpoint"] == "/api/ingest/result"
        assert fields["result"] == "failure"
        assert WRONG_API_KEY not in records[0].getMessage()
        assert WRONG_API_KEY not in json.dumps(fields)
    finally:
        _cleanup(temp_dirs)


def test_successful_ingest_emits_runner_scoped_audit_event(caplog):
    app, temp_dirs = _api_app()
    try:
        with app.test_client() as client, caplog.at_level(logging.INFO, logger="benchkit.audit"):
            resp = client.post(
                "/api/ingest/result",
                data=b'{"code":"test"}',
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            )

        assert resp.status_code == 200
        records = _audit_records(caplog, "ingest_accepted")
        assert len(records) == 1
        fields = records[0].audit_fields
        assert fields["actor"] == "test-runner"
        assert fields["result"] == "success"
        assert fields["details"]["ingest_type"] == "result"
        assert fields["target"].startswith("result_")
    finally:
        _cleanup(temp_dirs)


def test_admin_delete_emits_audit_event(caplog):
    app, temp_dirs = _portal_app()
    try:
        with app.test_client() as client, caplog.at_level(logging.INFO, logger="benchkit.audit"):
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_email"] = "admin@test.com"
                sess["user_affiliations"] = ["admin"]
            resp = client.post("/admin/users/second-admin@test.com/delete")

        assert resp.status_code == 302
        records = _audit_records(caplog, "admin_user_deleted")
        assert len(records) == 1
        fields = records[0].audit_fields
        assert fields["actor"] == "admin@test.com"
        assert fields["target"] == "second-admin@test.com"
        assert fields["result"] == "success"
    finally:
        _cleanup(temp_dirs)


def test_audit_event_redacts_sensitive_detail_fields(caplog):
    app, temp_dirs = _api_app()
    try:
        with app.test_request_context("/auth/login", method="POST"):
            with caplog.at_level(logging.INFO, logger="benchkit.audit"):
                audit_event(
                    "login_failure",
                    actor="user@example.com",
                    result="failure",
                    details={"totp_code": "123456", "reason": "invalid_totp"},
                )

        records = _audit_records(caplog, "login_failure")
        assert len(records) == 1
        fields = records[0].audit_fields
        assert fields["details"]["totp_code"] == "<redacted>"
        assert "123456" not in json.dumps(fields)
    finally:
        _cleanup(temp_dirs)


def test_audit_event_uses_route_template_without_invitation_token(caplog):
    app = Flask(__name__)
    configure_audit_logging(app)

    @app.route("/auth/setup/<token>", methods=["POST"])
    def setup(token):
        audit_event("setup_failure", actor="user@example.com", result="failure")
        return "ok"

    with app.test_client() as client, caplog.at_level(logging.INFO, logger="benchkit.audit"):
        resp = client.post("/auth/setup/invitation-secret-token")

    assert resp.status_code == 200
    records = _audit_records(caplog, "setup_failure")
    assert len(records) == 1
    fields = records[0].audit_fields
    assert fields["endpoint"] == "/auth/setup/<token>"
    assert "invitation-secret-token" not in json.dumps(fields)


def test_audit_event_uses_route_template_without_admin_email(caplog):
    app = Flask(__name__)
    configure_audit_logging(app)

    @app.route("/admin/users/<email>/delete", methods=["POST"])
    def delete_user(email):
        audit_event("admin_user_deleted", actor="admin@example.com", target=email, result="success")
        return "ok"

    with app.test_client() as client, caplog.at_level(logging.INFO, logger="benchkit.audit"):
        resp = client.post("/admin/users/user@example.com/delete")

    assert resp.status_code == 200
    records = _audit_records(caplog, "admin_user_deleted")
    assert len(records) == 1
    fields = records[0].audit_fields
    assert fields["endpoint"] == "/admin/users/<email>/delete"
    assert fields["target"] == "user@example.com"


def test_json_audit_formatter_outputs_event_payload(caplog):
    app, temp_dirs = _api_app()
    try:
        with app.test_request_context("/api/ingest/result", method="POST"):
            with caplog.at_level(logging.INFO, logger="benchkit.audit"):
                audit_event(
                    "ingest_accepted",
                    actor="runner-a",
                    result="success",
                    details={"ingest_type": "result"},
                )

        formatted = JsonAuditFormatter().format(_audit_records(caplog, "ingest_accepted")[0])
        payload = json.loads(formatted)
        assert payload["event_type"] == "ingest_accepted"
        assert payload["actor"] == "runner-a"
        assert payload["details"] == {"ingest_type": "result"}
        assert payload["timestamp"].endswith("Z")
    finally:
        _cleanup(temp_dirs)


def test_configure_audit_logging_adds_default_json_stderr_handler():
    logger = logging.getLogger("benchkit.audit")
    original_handlers = list(logger.handlers)
    logger.handlers = [
        handler
        for handler in logger.handlers
        if not getattr(handler, "_benchkit_audit_stderr_handler", False)
    ]
    try:
        app = Flask(__name__)
        configured = configure_audit_logging(app)
        handlers = [
            handler
            for handler in configured.handlers
            if getattr(handler, "_benchkit_audit_stderr_handler", False)
        ]

        assert app.audit_logger is configured
        assert len(handlers) == 1
        assert isinstance(handlers[0].formatter, JsonAuditFormatter)

        configure_audit_logging(app)
        handlers_after_second_call = [
            handler
            for handler in configured.handlers
            if getattr(handler, "_benchkit_audit_stderr_handler", False)
        ]
        assert handlers_after_second_call == handlers
    finally:
        for handler in logger.handlers:
            if handler not in original_handlers:
                handler.close()
        logger.handlers = original_handlers


def test_configure_audit_logging_can_mirror_to_file(monkeypatch, tmp_path):
    logger = logging.getLogger("benchkit.audit")
    original_handlers = list(logger.handlers)
    logger.handlers = [
        handler
        for handler in logger.handlers
        if not getattr(handler, "_benchkit_audit_stderr_handler", False)
        and not getattr(handler, "_benchkit_audit_file_handler", False)
    ]
    audit_log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("RESULT_SERVER_AUDIT_LOG_FILE", str(audit_log))
    try:
        app = Flask(__name__)
        configure_audit_logging(app)

        with app.test_request_context("/api/ingest/result", method="POST"):
            audit_event("ingest_accepted", actor="runner-a", result="success")

        for handler in logger.handlers:
            handler.flush()

        lines = audit_log.read_text(encoding="utf-8").splitlines()
        payload = json.loads(lines[-1])
        assert payload["event_type"] == "ingest_accepted"
        assert payload["actor"] == "runner-a"
        assert payload["result"] == "success"

        configure_audit_logging(app)
        file_handlers = [
            handler
            for handler in logger.handlers
            if getattr(handler, "_benchkit_audit_file_handler", False)
        ]
        assert len(file_handlers) == 1
    finally:
        for handler in logger.handlers:
            if handler not in original_handlers:
                handler.close()
        logger.handlers = original_handlers
