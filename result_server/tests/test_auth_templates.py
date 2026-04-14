import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)


def test_auth_login_template_renders_portal_shell():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    with app.test_request_context("/auth/login"):
        from flask import render_template

        html = render_template("auth_login.html", step="email")

    assert "Sign in with your email address and TOTP code" in html
    assert "Step 2 of 2" not in html
    assert "Continue" in html


def test_auth_setup_template_renders_portal_shell():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
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
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
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
