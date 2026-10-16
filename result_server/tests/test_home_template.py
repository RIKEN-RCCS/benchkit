import os
import sys
from html.parser import HTMLParser

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, install_portal_test_stubs

install_portal_test_stubs(include_otp=False)

from routes.home import register_home_routes


class _HomeLinks(HTMLParser):
    """Inspect the landing page cards without depending on their wording."""

    def __init__(self, html):
        super().__init__()
        self.links = []
        self.access_notes = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "home-link-card" in attrs.get("class", "").split():
            self.links.append(attrs)
        if tag == "span" and "home-access-note" in attrs.get("class", "").split():
            self.access_notes += 1


def _home_app(prefix=""):
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        include_home_route=False,
        prefix=prefix,
    )
    register_home_routes(app, prefix=prefix)
    return app


@pytest.mark.parametrize("prefix", ["", "/dev2"])
@pytest.mark.parametrize("public,role", [
    (False, None), (False, "dev"), (False, "admin"),
    (True, None), (True, "dev"), (True, "admin"),
])
def test_home_entry_points_follow_access_mode(monkeypatch, prefix, public, role):
    monkeypatch.delenv("CX_DISCORD_INVITE_URL", raising=False)
    app = _home_app(prefix)
    app.config["PUBLIC_PORTAL_MODE"] = public
    with app.test_client() as client:
        if role:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["user_affiliations"] = [role]
                sess["user_email"] = "user@example.invalid"
        response = client.get(f"{prefix}/")
    assert response.status_code == 200
    page = _HomeLinks(response.get_data(as_text=True))
    cards = page.links
    assert page.access_notes == int(not public and role is None)
    hrefs = [card["href"] for card in cards]
    with app.test_request_context():
        from flask import url_for

        expected = [url_for("results.results"), url_for("systemlist")]
        restricted = [url_for("estimated.estimated_results"),
                      url_for("results.usage_report"), url_for("admin.users")]
        if not public:
            expected.append(url_for("estimated.estimated_results") if role else url_for("auth.login"))
            if role == "admin":
                expected.extend(restricted[1:])
        assert {href for href in hrefs if href.startswith("/")} == set(expected)

    guide_urls = {
        "https://github.com/RIKEN-RCCS/benchkit/blob/main/docs/guides/add-app.md",
        "https://github.com/RIKEN-RCCS/benchpark/blob/FN_apps/User_Guide.md",
        "https://github.com/llnl/benchpark",
    }
    assert {href for href in hrefs if href.startswith("https://")} == guide_urls
    for card in cards:
        if card["href"] in guide_urls:
            assert card.get("target") == "_blank"
            assert {"noopener", "noreferrer"} <= set(card.get("rel", "").split())


def test_home_page_renders_discord_link_when_configured(monkeypatch):
    invite = "https://discord.gg/example"
    monkeypatch.setenv("CX_DISCORD_INVITE_URL", invite)
    app = _home_app()
    with app.test_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    cards = _HomeLinks(response.get_data(as_text=True)).links
    invite_cards = [card for card in cards if card["href"] == invite]
    assert len(invite_cards) == 1
    assert invite_cards[0].get("target") == "_blank"
    assert {"noopener", "noreferrer"} <= set(invite_cards[0].get("rel", "").split())


def test_changes_page_renders_release_notes(monkeypatch):
    from routes import home

    releases = [
        {"version": "v2099.01", "date": "2099-01-02", "title": "Example update",
         "summary": "Example summary", "changes": ["First example change", "Second example change"]},
        {"version": "v2098.12", "date": "", "title": "Earlier update",
         "summary": "Earlier summary", "changes": ["Earlier example change"]},
    ]
    monkeypatch.setattr(home, "portal_release_notes", lambda: releases)
    app = _home_app()
    with app.test_client() as client:
        response = client.get("/changes")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for release in releases:
        for key in ("version", "title", "date", "summary"):
            if release[key]:
                assert release[key] in html
        for change in release["changes"]:
            assert change in html
    assert html.index(releases[0]["version"]) < html.index(releases[1]["version"])
