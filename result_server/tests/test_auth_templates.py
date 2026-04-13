import os
import sys
import types


def _setup_stubs():
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")


_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, Blueprint


def _make_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    results_bp = Blueprint("results", __name__)
    estimated_bp = Blueprint("estimated", __name__)
    auth_bp = Blueprint("auth", __name__)
    admin_bp = Blueprint("admin", __name__)

    @results_bp.route("/")
    def results():
        return ""

    @estimated_bp.route("/")
    def estimated_results():
        return ""

    @auth_bp.route("/login")
    def login():
        return ""

    @auth_bp.route("/setup/<token>")
    def setup(token):
        return token

    @admin_bp.route("/users")
    def users():
        return ""

    @admin_bp.route("/users/add", methods=["POST"])
    def add_user():
        return ""

    @admin_bp.route("/users/<path:email>/affiliations", methods=["POST"])
    def update_affiliations(email):
        return email

    @admin_bp.route("/users/<path:email>/reinvite", methods=["POST"])
    def reinvite_user(email):
        return email

    @admin_bp.route("/users/<path:email>/delete", methods=["POST"])
    def delete_user(email):
        return email

    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.route("/")
    def home():
        return ""

    @app.route("/systemlist")
    def systemlist():
        return ""

    return app


def test_auth_login_template_renders_portal_shell():
    app = _make_app()
    with app.test_request_context("/auth/login"):
        from flask import render_template

        html = render_template("auth_login.html", step="email")

    assert "Sign in with your email address and TOTP code" in html
    assert "Step 2 of 2" not in html
    assert "Continue" in html


def test_auth_setup_template_renders_portal_shell():
    app = _make_app()
    with app.test_request_context("/auth/setup/token-1"):
        from flask import render_template

        html = render_template(
            "auth_setup.html",
            error=False,
            qr_data="data:image/png;base64,abc",
            secret="SECRETKEY",
            email="user@example.com",
            token="token-1",
        )

    assert "Complete portal access setup" in html
    assert "Invitation-based setup" in html
    assert "Complete Setup" in html


def test_admin_users_template_renders_portal_table():
    app = _make_app()
    with app.test_request_context("/admin/users"):
        from flask import render_template, session

        session["user_email"] = "admin@example.com"
        html = render_template(
            "admin_users.html",
            users=[
                {
                    "email": "admin@example.com",
                    "affiliations": ["admin"],
                    "has_totp": True,
                },
                {
                    "email": "user@example.com",
                    "affiliations": ["dev"],
                    "has_totp": False,
                },
            ],
            invitation_url=None,
        )

    assert "Manage access, affiliations, and TOTP onboarding" in html
    assert "Review current user access" in html
    assert "Registered" in html
    assert "Pending" in html
