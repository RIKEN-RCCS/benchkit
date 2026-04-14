import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import StaticAffiliationUserStore, install_portal_test_stubs

install_portal_test_stubs(include_redis=False)

from utils.session_user_context import get_session_user_context


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True
    app.config["USER_STORE"] = StaticAffiliationUserStore({"user@example.com": ["dev"]})

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
