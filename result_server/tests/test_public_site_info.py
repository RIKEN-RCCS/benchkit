"""Deployment-owned public copy, using synthetic settings and no live services."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_support import build_portal_shell_app
from routes.home import register_home_routes
from utils.portal_access import register_public_portal_guard
from utils.public_site_info import SETTING, configure_public_site_info, parse_public_site_info


INFO = {
    "title": "About these measurements",
    "operator": "Example Research Group",
    "paragraphs": ["Measurements depend on the stated execution conditions."],
    "contact": {"label": "Questions and corrections", "url": "https://support.example.org/questions"},
    "terms": {"label": "Data terms", "url": "https://support.example.org/terms"},
    "acknowledgements": ["Support applies only to the identified measurements."],
}


def make_app(prefix="", info=None, public=True):
    app = build_portal_shell_app(
        templates_dir=str(Path(__file__).resolve().parents[1] / "templates"),
        include_home_route=False, prefix=prefix,
    )
    configure_public_site_info(app, {} if info is None else {SETTING: json.dumps(info)})
    app.config["PUBLIC_PORTAL_MODE"] = public
    app.config["PRIVATE_TEST_VALUE"] = "private-fixture-not-for-publication"
    register_home_routes(app, prefix=prefix)
    register_public_portal_guard(app)
    return app


@pytest.mark.parametrize("raw", [None, "", "  ", "{}", '{"title":"Unused"}'])
def test_unconfigured_is_disabled(raw):
    assert parse_public_site_info(raw) is None


@pytest.mark.parametrize("prefix", ["", "/dev", "/dev2", "/dev2/console"])
@pytest.mark.parametrize("public", [True, False])
def test_opt_in_routes_and_footer(prefix, public):
    app = make_app(prefix, INFO, public)
    client = app.test_client()
    home = client.get(prefix + "/").get_data(as_text=True)
    response = client.get(prefix + "/about")
    assert response.status_code == 200
    detail = response.get_data(as_text=True)
    assert f'href="{prefix}/about"' in home
    for page in (home, detail):
        assert INFO["operator"] in page
        assert INFO["contact"]["url"] in page
        assert "private-fixture-not-for-publication" not in page
    for value in (INFO["paragraphs"][0], INFO["terms"]["url"], INFO["acknowledgements"][0]):
        assert value in detail
    assert client.get(prefix + "/about/").status_code == 200


@pytest.mark.parametrize("public", [True, False])
def test_disabled_adds_no_footer_or_empty_page(public):
    client = make_app(public=public).test_client()
    assert client.get("/about").status_code == 404
    assert 'href="/about"' not in client.get("/").get_data(as_text=True)


def test_public_page_does_not_broaden_private_routes():
    client = make_app(info=INFO).test_client()
    assert client.get("/about").status_code == 200
    for path in ("/admin/users", "/estimated/", "/results/confidential", "/execution-profile-requests/"):
        assert client.get(path).status_code == 404


def test_text_is_escaped_and_links_are_not_embedded():
    text = '<script>alert("example")</script>'
    info = {**INFO, "title": text, "operator": text, "paragraphs": [text],
            "acknowledgements": [text],
            "contact": {"label": text, "url": "https://support.example.org/?a=1&b=2"}}
    page = make_app(info=info).test_client().get("/about").get_data(as_text=True)
    assert text not in page
    assert "&lt;script&gt;" in page
    assert 'href="https://support.example.org/?a=1&amp;b=2"' in page
    assert "<iframe" not in page


def test_partial_config_and_per_app_isolation():
    first = make_app(info={"operator": "First operator"})
    second = make_app(info={"contact": INFO["contact"]})
    first_page = first.test_client().get("/about").get_data(as_text=True)
    second_page = second.test_client().get("/about").get_data(as_text=True)
    assert "First operator" in first_page and "First operator" not in second_page
    assert INFO["contact"]["url"] not in first_page
    assert INFO["contact"]["url"] in second_page
    assert "<h2>Acknowledgements</h2>" not in second_page


@pytest.mark.parametrize("url", [
    "http://support.example.org", "javascript:alert(1)", "data:text/html,example",
    "/relative", "//support.example.org", "https://", "https://user:pass@example.org",
    "https://example.org/ bad", "https://example.org\\@elsewhere.example.org",
    "https://example.org:bad", "https://example.org:0", "https://example.org:65536",
    "https://%65xample.org", "https://example.org/\nheader",
])
@pytest.mark.parametrize("field", ["contact", "terms"])
def test_unsafe_links_rejected(url, field):
    with pytest.raises(ValueError, match=SETTING):
        parse_public_site_info(json.dumps({field: {"label": "Contact", "url": url}}))


@pytest.mark.parametrize("raw", [
    "not-json-private-value", "[]", "null", '{"operator":"one","operator":"two"}',
    '{"contact":{"label":"one","label":"two","url":"https://example.org"}}',
    '{"unknown":"private-value"}', '{"operator":1}', '{"title":""}',
    '{"paragraphs":"text"}', '{"paragraphs":[null]}', '{"paragraphs":[""]}',
    '{"acknowledgements":[false]}', '{"contact":{}}', '{"terms":null}',
    json.dumps({"operator": "x" * 257}), json.dumps({"paragraphs": ["x"] * 33}),
    json.dumps({"operator": "private-value\u0001"}), " " * 65537,
    "[" * 2000 + "]" * 2000,
])
def test_invalid_settings_fail_without_echoing_content(raw):
    with pytest.raises(ValueError) as error:
        parse_public_site_info(raw)
    assert str(error.value) == f"{SETTING} must contain valid public text and HTTPS links"


def test_contact_setting_does_not_inherit_legacy_invite(monkeypatch):
    monkeypatch.setenv("CX_DISCORD_INVITE_URL", "https://legacy.example.org/invite")
    app = make_app(info={"operator": "Example operator"})
    page = app.test_client().get("/about").get_data(as_text=True)
    assert "https://legacy.example.org/invite" not in page
    assert app.config["PUBLIC_SITE_INFO"]["contact"] is None
