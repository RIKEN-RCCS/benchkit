import os
import sys
import types

import pytest
from flask import Flask


def _setup_stubs():
    otp_mod = types.ModuleType("utils.otp_manager")
    otp_mod.get_affiliations = lambda email: ["dev"]
    otp_mod.is_allowed = lambda email: True
    sys.modules["utils.otp_manager"] = otp_mod

    otp_redis_mod = types.ModuleType("utils.otp_redis_manager")
    otp_redis_mod.get_affiliations = lambda email: ["dev"]
    otp_redis_mod.is_allowed = lambda email: True
    otp_redis_mod.send_otp = lambda email: (True, "stub")
    otp_redis_mod.verify_otp = lambda email, code: True
    otp_redis_mod.invalidate_otp = lambda email: None
    sys.modules["utils.otp_redis_manager"] = otp_redis_mod


_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.session_user_context import get_session_user_context


class _StubUserStore:
    def get_affiliations(self, email):
        if email == "user@example.com":
            return ["dev"]
        return []


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    app.config["USER_STORE"] = _StubUserStore()

    return app


def test_get_session_user_context_for_anonymous_session(app):
    with app.test_request_context("/results"):
        context = get_session_user_context()

    assert context == {
        "authenticated": False,
        "email": None,
        "affiliations": [],
    }


def test_get_session_user_context_resolves_affiliations(app):
    with app.test_request_context("/results"):
        from flask import session

        session["authenticated"] = True
        session["user_email"] = "user@example.com"
        context = get_session_user_context()

    assert context["authenticated"] is True
    assert context["email"] == "user@example.com"
    assert context["affiliations"] == ["dev"]
