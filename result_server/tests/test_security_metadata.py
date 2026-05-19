"""Tests for security metadata routes."""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.security_metadata import register_security_metadata_routes


def test_security_txt_route():
    app = Flask(__name__)
    register_security_metadata_routes(app)

    resp = app.test_client().get("/.well-known/security.txt")

    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    text = resp.get_data(as_text=True)
    assert "Contact: https://github.com/RIKEN-RCCS/benchkit/security/advisories/new" in text
    assert "mailto:" not in text
    assert "Expires: 2027-05-19T00:00:00Z" in text
    assert "Policy: https://github.com/RIKEN-RCCS/benchkit/blob/main/SECURITY.md" in text


def test_robots_txt_route():
    app = Flask(__name__)
    register_security_metadata_routes(app)

    resp = app.test_client().get("/robots.txt")

    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Disallow: /admin/" in text
    assert "Disallow: /auth/" in text


def test_security_metadata_routes_allow_prefix():
    app = Flask(__name__)
    register_security_metadata_routes(app, prefix="/dev")

    resp = app.test_client().get("/dev/.well-known/security.txt")

    assert resp.status_code == 200
