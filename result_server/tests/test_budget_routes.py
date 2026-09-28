"""Budget management isolation, live authorization, CSRF and review contracts."""

import html
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

import pytest

pytest.importorskip("sqlcipher3")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_support import build_portal_route_app, install_portal_test_stubs  # noqa: E402

install_portal_test_stubs()

from routes.budget_registry import register_budget_registry  # noqa: E402
from utils.csrf import init_csrf  # noqa: E402
from utils.portal_access import register_public_portal_guard, classify_endpoint  # noqa: E402
from test_budget_registry import registry, configured_target, seed, ADMIN, MANAGER, APPLICANT  # noqa: E402, F401


class Users:
    def __init__(self):
        self.users = {ADMIN.principal: ["admin"], MANAGER.principal: [], APPLICANT.principal: []}

    def user_exists(self, email):
        return email in self.users

    def get_affiliations(self, email):
        return self.users[email]


@pytest.fixture
def portal(registry, tmp_path, monkeypatch):
    monkeypatch.delenv("RESULT_SERVER_BUDGET_DB_PATH", raising=False)
    monkeypatch.delenv("RESULT_SERVER_BUDGET_DB_KEY_FILE", raising=False)
    users = Users()
    app = build_portal_route_app(
        templates_dir=str(Path(__file__).resolve().parents[1] / "templates"),
        received_dir=str(tmp_path / "received"), estimated_dir=str(tmp_path / "estimated"), user_store=users,
    )
    register_budget_registry(app)
    app.config.update(BUDGET_REGISTRY_DB_PATH=str(registry.storage.path),
                      BUDGET_REGISTRY_KEY_FILE=str(registry.storage.key_file))
    init_csrf(app)
    register_public_portal_guard(app)
    return app, users


def login(client, principal=ADMIN.principal):
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["user_email"] = principal
        # Deliberately stale: these affiliations must never grant write access.
        session["user_affiliations"] = ["admin"]


def hidden(response, name):
    match = re.search(r'name="' + name + r'" value="([^"]*)"', response.get_data(as_text=True))
    assert match, response.status_code
    return html.unescape(match.group(1))


@pytest.mark.parametrize('principal,query', [
    (ADMIN.principal, ''),
    (ADMIN.principal, '?edit=research'),
    (MANAGER.principal, '?edit=research'),
    (ADMIN.principal, '?section=execution_accounts'),
    (ADMIN.principal, '?section=connections'),
    (ADMIN.principal, '?section=destinations'),
    (ADMIN.principal, '?section=budget_managers'),
])
def test_editable_fields_have_accessible_contextual_help(portal, registry, principal, query):
    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.nodes = []

        def handle_starttag(self, tag, attrs):
            self.nodes.append((tag, dict(attrs)))

    seed(registry)
    app, _ = portal
    client = app.test_client()
    login(client, principal)
    page = client.get('/budgets/' + query)
    assert page.status_code == 200
    parser = Elements()
    parser.feed(page.get_data(as_text=True))
    ids = [attrs['id'] for _, attrs in parser.nodes if 'id' in attrs]
    assert len(ids) == len(set(ids))
    labels = {attrs.get('for') for tag, attrs in parser.nodes if tag == 'label'}
    descriptions = {attrs.get('id') for tag, attrs in parser.nodes if tag == 'dl'}
    controls = [attrs for tag, attrs in parser.nodes
                if tag in ('input', 'select') and attrs.get('id', '').startswith('budget-field-')]
    assert controls
    for control in controls:
        assert control['id'] in labels
        assert control['aria-describedby'] in descriptions
    assert any(tag == 'summary' and attrs.get('aria-label') for tag, attrs in parser.nodes)


def review(client, values, kind="budgets"):
    page = client.get("/budgets/?section=budgets")
    if 'name="csrf_token"' not in page.get_data(as_text=True):
        page = client.get("/budgets/?edit=research")
    if kind == "budgets":
        values = {"system": "ExampleSystem", **values}
    return client.post("/budgets/review", data={**values, "kind": kind,
                       "revision": hidden(page, "revision"), "csrf_token": hidden(page, "csrf_token")})


def apply(client, response, **overrides):
    return client.post("/budgets/apply", data={"ticket": hidden(response, "ticket"),
                       "csrf_token": hidden(response, "csrf_token"), "confirm_shared_change": "on", **overrides})


def test_review_apply_and_replay(portal, registry):
    app, _users = portal
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "research", "label": "Research budget", "enabled": "on"})
    assert proposed.status_code == 200
    assert registry.check() == 0
    assert registry.catalog(ADMIN)["budgets"] == []
    assert "shared registry" in proposed.get_data(as_text=True)
    assert apply(client, proposed).status_code == 302
    assert registry.check() == 1
    assert registry.catalog(ADMIN)["budgets"][0]["label"] == "Research budget"
    assert apply(client, proposed).status_code == 409


def test_confirm_and_signed_proposal_are_required(portal, registry):
    app, _ = portal
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "research", "label": "Research"})
    assert apply(client, proposed, confirm_shared_change="").status_code == 400
    assert apply(client, proposed, ticket=hidden(proposed, "ticket") + "x").status_code == 400
    assert registry.check() == 0


def test_apply_uses_reviewed_values_not_resubmitted_fields(portal, registry):
    app, _ = portal
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "research", "label": "Reviewed"})
    assert apply(client, proposed, label="Unreviewed", is_admin="true", preview="true").status_code == 302
    assert registry.catalog(ADMIN)["budgets"][0]["label"] == "Reviewed"


def test_review_cannot_be_shared_between_actors(portal, registry):
    app, users = portal
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "research", "label": "Reviewed"})
    other = app.test_client()
    users.users["second@example.org"] = ["admin"]
    login(other, "second@example.org")
    page = other.get("/budgets/")
    assert apply(other, proposed, csrf_token=hidden(page, "csrf_token")).status_code == 403
    assert registry.check() == 0


def test_expired_review_is_rejected(portal, registry, monkeypatch):
    from itsdangerous import TimestampSigner
    from routes.budget_registry import _signer
    app, _ = portal
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "research", "label": "Reviewed"})
    with app.app_context():
        signer = _signer()
        payload = signer.loads(hidden(proposed, "ticket"))
        original = TimestampSigner.get_timestamp
        with monkeypatch.context() as patch:
            patch.setattr(TimestampSigner, "get_timestamp", lambda self: original(self) - 601)
            expired = signer.dumps(payload)
    assert apply(client, proposed, ticket=expired).status_code == 400
    assert registry.check() == 0


def test_stale_review_does_not_overwrite(portal, registry):
    app, _ = portal
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "research", "label": "Research"})
    registry.save_budget(ADMIN, 0, id="separate", label="Other", system="ExampleSystem")
    assert apply(client, proposed).status_code == 409
    assert [row["id"] for row in registry.catalog(ADMIN)["budgets"]] == ["separate"]


def test_fresh_authorization_not_stale_session(portal, registry):
    app, users = portal
    seed(registry)
    client = app.test_client()
    login(client, MANAGER.principal)
    assert client.get("/budgets/").status_code == 200
    assert client.get("/budgets/?section=connections").status_code == 403
    assert client.get("/budgets/?section=destinations").status_code == 403
    users.users.pop(MANAGER.principal)
    assert client.get("/budgets/").status_code == 403


def test_revoked_admin_cannot_apply_old_review(portal, registry):
    app, users = portal
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "research", "label": "Research"})
    users.users[ADMIN.principal] = []
    assert apply(client, proposed).status_code == 403
    assert registry.check() == 0


def test_manager_scope_and_revocation(portal, registry):
    app, _ = portal
    revision = seed(registry)
    revision = registry.save_budget(ADMIN, revision, id="other", label="Hidden other budget", system="ExampleSystem")
    client = app.test_client()
    login(client, MANAGER.principal)
    page = client.get("/budgets/")
    body = page.get_data(as_text=True)
    assert "Hidden other budget" not in body
    assert "example-user" not in body and "example-run" not in body
    assert client.get("/budgets/?edit=other").status_code == 403
    assert review(client, {"id": "other", "label": "Not allowed"}).status_code == 403
    proposed = review(client, {"id": "research", "label": "Updated", "enabled": "on"})
    registry.set_manager(ADMIN, revision, budget_id="research", principal=MANAGER.principal, assigned=False)
    assert apply(client, proposed).status_code == 403


def test_csrf_and_anonymous_access(portal, registry):
    app, _ = portal
    client = app.test_client()
    response = client.get("/budgets/")
    assert response.status_code == 302
    assert response.headers["Cache-Control"] == "no-store"
    login(client)
    assert client.post("/budgets/review", data={"id": "research"}).status_code == 400
    assert client.post("/budgets/apply", data={"confirm_shared_change": "on"}).status_code == 400
    assert registry.check() == 0


def test_public_portal_denies_budget_routes(portal):
    app, _ = portal
    app.config["PUBLIC_PORTAL_MODE"] = True
    client = app.test_client()
    login(client)
    assert client.get("/budgets/").status_code == 404
    assert client.post("/budgets/review").status_code in (400, 404)
    assert classify_endpoint("budget_registry.index") == "authenticated_console"


def test_missing_config_or_key_never_creates_database(portal, tmp_path):
    app, _ = portal
    client = app.test_client()
    login(client)
    app.config["BUDGET_REGISTRY_DB_PATH"] = ""
    assert client.get("/budgets/").status_code == 503
    missing = tmp_path / "db" / "missing.db"
    app.config["BUDGET_REGISTRY_DB_PATH"] = str(missing)
    assert client.get("/budgets/").status_code == 503
    assert not missing.exists()


def test_invalid_values_are_rejected_at_review(portal, registry):
    app, _ = portal
    client = app.test_client()
    login(client)
    assert review(client, {"id": "research", "label": "Research", "valid_from": "invalid"}).status_code == 400
    assert registry.check() == 0


def test_infrastructure_flow_and_impact(portal, registry):
    app, _ = portal
    seed(registry)
    client = app.test_client()
    login(client)
    proposed = review(client, {"id": "compute", "label": "Updated connection", "server_url": "https://gitlab.example.org",
                              "project_path": "group/project", "token_env": "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_COMPUTE"}, "connections")
    assert proposed.status_code == 200
    assert "Research budget @ ExampleSystem" in proposed.get_data(as_text=True)
    assert apply(client, proposed).status_code == 302
    assert registry.catalog(ADMIN)["connections"][0]["project_path"] == "group/project"


def test_manager_budget_edit_and_xss_escaping(portal, registry):
    app, _ = portal
    seed(registry)
    client = app.test_client()
    login(client, MANAGER.principal)
    proposed = review(client, {"id": "research", "label": "<script>alert(1)</script>"})
    assert proposed.status_code == 200
    assert "<script>alert(1)</script>" not in proposed.get_data(as_text=True)
    assert "&lt;script&gt;" in proposed.get_data(as_text=True)


def test_registration_only_configures_paths(monkeypatch, tmp_path):
    from flask import Flask
    path = tmp_path / "missing.db"
    monkeypatch.setenv("RESULT_SERVER_BUDGET_DB_PATH", str(path))
    monkeypatch.setenv("RESULT_SERVER_BUDGET_DB_KEY_FILE", str(tmp_path / "missing.key"))
    app = Flask(__name__)
    register_budget_registry(app, "/example")
    assert app.config["BUDGET_REGISTRY_DB_PATH"] == str(path)
    assert not path.exists()
    assert "/example/budgets/" in {rule.rule for rule in app.url_map.iter_rules()}


def test_budget_system_registration_uses_generated_ids_and_returns_to_managers(portal, registry):
    app, _ = portal
    seed(registry)
    client = app.test_client()
    login(client)
    before = registry.management_catalog(ADMIN)
    proposed = review(client, {"label": "Another budget", "enabled": "on",
                              "system": "ExampleSystem", "account_id": "research-account",
                              "allocation_project_id": "another-allocation"}, "budget_system")
    assert proposed.status_code == 200
    assert registry.management_catalog(ADMIN) == before
    response = apply(client, proposed)
    assert response.status_code == 302
    catalog = registry.catalog(ADMIN)
    budget = next(row for row in catalog["budgets"] if row["label"] == "Another budget")
    destination = next(row for row in catalog["destinations"] if row["budget_id"] == budget["id"])
    assert budget["id"] and destination["id"]
    body = client.get(response.location).get_data(as_text=True)
    assert "Another budget @ ExampleSystem" in body
    assert 'id="budget-managers"' in body
    assert hidden(client.get(response.location), "budget_id") == budget["id"]
    assert apply(client, proposed).status_code == 409


def test_budget_system_rejects_invalid_pairs_and_manager_writes(portal, registry):
    app, _ = portal
    seed(registry)
    client = app.test_client()
    login(client)
    before = registry.management_catalog(ADMIN)
    values = {"budget_id": "research", "destination_id": "research-system", "label": "Changed",
              "system": "OtherSystem", "account_id": "research-account", "allocation_project_id": "example"}
    assert review(client, values, "budget_system").status_code == 400
    assert registry.management_catalog(ADMIN) == before
    login(client, MANAGER.principal)
    assert review(client, values, "budget_system").status_code == 403
    page = client.get("/budgets/?edit=research&destination=research-system")
    assert page.status_code == 200
    assert 'id="budget-managers"' in page.get_data(as_text=True)
    assert 'id="manager-editor"' not in page.get_data(as_text=True)
    assert "example-run" not in page.get_data(as_text=True)
    assert "gitlab.example.org" not in page.get_data(as_text=True)
    assert 'name="account_id"' not in page.get_data(as_text=True)
    assert client.get("/budgets/?edit=research&destination=unrelated").status_code == 403


def test_budget_update_does_not_affect_another_system_budget(portal, registry):
    app, _ = portal
    revision = seed(registry)
    revision = registry.save_account(ADMIN, revision, id="other-account", label="Other route", system="OtherSystem",
                                     connection_id="compute", build_tag="", run_tag="other-run")
    revision = registry.save_budget(ADMIN, revision, id="other-budget", label="Other budget", system="OtherSystem", enabled=True)
    registry.save_destination(ADMIN, revision, id="other-destination", budget_id="other-budget", system="OtherSystem",
                              account_id="other-account", allocation_project_id="other-allocation")
    client = app.test_client()
    login(client)
    proposed = review(client, {"budget_id": "research", "destination_id": "research-system", "label": "Renamed budget",
                              "system": "ExampleSystem", "account_id": "research-account",
                              "allocation_project_id": "example"}, "budget_system")
    assert proposed.status_code == 200
    assert "OtherSystem" not in proposed.get_data(as_text=True)
    assert "Renamed budget @ ExampleSystem" in proposed.get_data(as_text=True)
    assert apply(client, proposed).status_code == 302
    assert registry.resolve(ADMIN, "other-destination")["system"] == "OtherSystem"
    from utils.budget_registry import RegistryError
    with pytest.raises(RegistryError):
        registry.resolve(ADMIN, "research-system")


def test_budget_cannot_be_shared_across_systems(portal, registry):
    app, _ = portal
    revision = seed(registry)
    registry.save_account(ADMIN, revision, id="other-account", label="Other route", system="OtherSystem",
                          connection_id="compute", build_tag="", run_tag="other-run")
    client = app.test_client()
    login(client)
    settings = client.get("/budgets/?edit=research")
    assert hidden(settings, "kind") == "budget_setup"
    assert re.search(r'name="system"[^>]*readonly', settings.get_data(as_text=True))
    assert 'Add system' not in settings.get_data(as_text=True)
    assert 'Budget enabled' not in settings.get_data(as_text=True)
    assert 'Destination enabled' not in settings.get_data(as_text=True)
    assert 'name="role"' not in settings.get_data(as_text=True)
    before = registry.management_catalog(ADMIN)
    proposed = review(client, {"budget_id": "research", "label": "Research budget",
                              "system": "OtherSystem", "account_id": "other-account",
                              "allocation_project_id": "other-allocation", "enabled": "on"}, "budget_system")
    assert proposed.status_code == 400
    assert registry.management_catalog(ADMIN) == before


def test_cx_admin_assigns_managers_not_applicants(portal, registry):
    app, users = portal
    seed(registry)
    client = app.test_client()
    login(client)
    before = registry.check()
    assert client.get("/budgets/?section=budget_members").status_code == 403
    assert review(client, {"budget_id": "research", "principal": "unknown@example.org", "assigned": "on"},
                  "budget_managers").status_code == 400
    assert registry.check() == before
    proposed = review(client, {"budget_id": "research", "principal": APPLICANT.principal, "assigned": "on"},
                      "budget_managers")
    assert proposed.status_code == 200
    users.users.pop(APPLICANT.principal)
    assert apply(client, proposed).status_code == 400
    assert registry.check() == before
    proposed = review(client, {"budget_id": "research", "principal": MANAGER.principal}, "budget_managers")
    assert apply(client, proposed).status_code == 302
    assert registry.catalog(ADMIN)["budget_managers"] == []
    proposed = review(client, {"budget_id": "research", "principal": MANAGER.principal, "assigned": "on"},
                      "budget_managers")
    assert apply(client, proposed).status_code == 302
    login(client, MANAGER.principal)
    assert review(client, {"budget_id": "research", "principal": MANAGER.principal}, "budget_managers").status_code == 403
    assert review(client, {"id": "research", "label": "Manager update", "enabled": "on"}).status_code == 200


def test_applicant_is_not_a_budget_identity(portal, registry):
    app, _ = portal
    seed(registry)
    client = app.test_client()
    login(client, APPLICANT.principal)
    assert client.get("/budgets/").status_code == 403
    assert registry.list_destinations(APPLICANT)["destinations"] == []


def setup_form_values():
    return {"label": "New budget", "enabled": "on", "system": "ExampleSystem",
            "allocation_project_id": "example-allocation",
            "build_tag": "example-build", "run_tag": "example-run", "connection_id": "gitlab:example"}


def test_empty_registry_can_be_configured_on_one_page(portal, registry, configured_target):
    app, _ = portal
    client = app.test_client()
    login(client)
    page = client.get("/budgets/")
    assert hidden(page, "kind") == "budget_setup"
    assert 'name="account_name"' not in page.get_data(as_text=True)
    for name in ("server_url", "project_path", "token_env", "id_token_audience", "connection_label"):
        assert name not in page.get_data(as_text=True)
    for name in ("build_tag", "run_tag", "connection_id"):
        assert f'name="{name}"' in page.get_data(as_text=True)
    proposed = review(client, setup_form_values(), "budget_setup")
    assert proposed.status_code == 200
    assert registry.check() == 0
    response = apply(client, proposed)
    assert response.status_code == 302
    catalog = registry.catalog(ADMIN)
    assert len(catalog["budgets"]) == len(catalog["destinations"]) == len(catalog["connections"]) == len(catalog["execution_accounts"]) == 1
    resolved = registry.resolve(ADMIN, catalog["destinations"][0]["id"])
    assert resolved["target"]["project_path"] == "group/project"
    assert resolved["route"]["build_tag"] == "example-build"
    assert apply(client, proposed).status_code == 409


def test_retired_account_input_is_not_saved(portal, registry, configured_target):
    app, _ = portal
    client = app.test_client()
    login(client)
    for query in ("", "?section=execution_accounts"):
        assert 'name="account_name"' not in client.get('/budgets/' + query).get_data(as_text=True)
    proposed = review(client, {**setup_form_values(), "account_name": "unexpected-user"}, "budget_setup")
    assert proposed.status_code == 200
    assert "unexpected-user" not in proposed.get_data(as_text=True)
    assert apply(client, proposed).status_code == 302
    with registry.storage.connect(readonly=True) as conn:
        assert conn.execute("SELECT account_name FROM execution_accounts").fetchone()[0] == ""
    budget = registry.catalog(ADMIN)["budgets"][0]
    assert budget["valid_from"] == budget["valid_until"] == ""


@pytest.mark.parametrize("salt", ["budget-registry-review-v2", "budget-registry-review-v3"])
def test_review_from_retired_form_is_rejected(portal, registry, configured_target, salt):
    from itsdangerous import URLSafeTimedSerializer
    from routes.budget_registry import _signer
    app, _ = portal
    client = app.test_client()
    login(client)
    proposed = review(client, setup_form_values(), "budget_setup")
    with app.app_context():
        payload = _signer().loads(hidden(proposed, "ticket"))
    payload["values"]["account_name"] = "legacy-user"
    old_ticket = URLSafeTimedSerializer(app.secret_key, salt=salt).dumps(payload)
    assert apply(client, proposed, ticket=old_ticket).status_code == 400
    assert registry.check() == 0


@pytest.mark.parametrize("new_target,status", [("example=other.example.org/group/changed", 409), ("", 400)])
def test_target_change_after_review_requires_reconfirmation(portal, registry, configured_target, monkeypatch, new_target, status):
    app, _ = portal
    client = app.test_client()
    login(client)
    proposed = review(client, setup_form_values(), "budget_setup")
    assert proposed.status_code == 200
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", new_target)
    assert apply(client, proposed).status_code == status
    assert registry.check() == 0


def test_configured_connection_is_not_editable_or_copied_from_post(portal, registry, configured_target):
    app, _ = portal
    client = app.test_client()
    login(client)
    assert client.get('/budgets/?section=connections&edit=' + configured_target).status_code == 400
    proposed = review(client, {"id": configured_target, "label": "Overwrite", "server_url": "https://other.example.org",
                              "project_path": "group/other", "token_env": "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_OTHER"}, "connections")
    assert proposed.status_code == 400
    proposed = review(client, {**setup_form_values(), "server_url": "https://other.example.org",
                              "project_path": "group/other", "token_env": "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_OTHER",
                              "id_token_audience": "https://other.example.org"}, "budget_setup")
    assert proposed.status_code == 200
    assert apply(client, proposed).status_code == 302
    catalog = registry.catalog(ADMIN)
    snapshot = registry.resolve(ADMIN, catalog["destinations"][0]["id"])
    assert snapshot["target"]["server_url"] == "https://gitlab.example.org"
    assert snapshot["route"]["id_token_audience"] == "https://gitlab.example.org"


def test_missing_connection_is_an_actionable_empty_state(portal, registry):
    app, _ = portal
    client = app.test_client()
    login(client)
    page = client.get('/budgets/').get_data(as_text=True)
    assert 'No GitLab connections' in page
    assert 'section=connections' in page
    assert review(client, setup_form_values(), "budget_setup").status_code == 400
    assert registry.check() == 0


def existing_setup_values():
    return {**setup_form_values(), "budget_id": "research", "destination_id": "research-system",
            "account_id": "research-account", "loaded_account_id": "research-account",
            "connection_id": "compute"}


@pytest.mark.parametrize("changed", ["none", "run_tag", "ignored_connection_fields"])
def test_inline_review_lists_budgets_affected_by_shared_settings(portal, registry, changed):
    app, _ = portal
    revision = seed(registry)
    revision = registry.save_budget(ADMIN, revision, id="second", label="Second budget", system="ExampleSystem")
    revision = registry.save_destination(ADMIN, revision, id="second-destination", budget_id="second", system="ExampleSystem",
                                          account_id="research-account", allocation_project_id="second-allocation")
    revision = registry.save_account(ADMIN, revision, id="third-account", label="Third account", system="OtherSystem",
                                     connection_id="compute", build_tag="", run_tag="third-run")
    revision = registry.save_budget(ADMIN, revision, id="third", label="Third budget", system="OtherSystem")
    registry.save_destination(ADMIN, revision, id="third-destination", budget_id="third", system="OtherSystem",
                              account_id="third-account", allocation_project_id="third-allocation")
    client = app.test_client()
    login(client)
    values = existing_setup_values()
    if changed == "run_tag":
        values[changed] = "changed-run"
    if changed == "ignored_connection_fields":
        values.update(project_path="group/changed", server_url="https://unreviewed.example.org",
                      token_env="RESULT_SERVER_GITLAB_TRIGGER_TOKEN_OTHER", id_token_audience="https://other.example.org")
    before = registry.management_catalog(ADMIN)
    proposed = review(client, values, "budget_setup")
    assert proposed.status_code == 200
    body = proposed.get_data(as_text=True)
    assert ("Second budget @ ExampleSystem" in body) == (changed == "run_tag")
    assert "Third budget @ OtherSystem" not in body
    assert registry.management_catalog(ADMIN) == before
    assert apply(client, proposed, run_tag="unreviewed-tag").status_code == 302
    after = registry.catalog(ADMIN)
    assert len(after["connections"]) == len(before["connections"])
    assert after["connections"] == before["connections"]
    assert len(after["execution_accounts"]) == len(before["execution_accounts"])
    assert registry.resolve(ADMIN, "research-system")["route"]["run_tag"] == values["run_tag"]


def test_inline_setup_rechecks_scope_revision_and_loaded_selection(portal, registry):
    app, users = portal
    revision = seed(registry)
    client = app.test_client()
    login(client)
    values = existing_setup_values()
    assert review(client, {**values, "loaded_account_id": "stale"}, "budget_setup").status_code == 400
    assert review(client, {**values, "connection_id": "missing"}, "budget_setup").status_code == 400
    assert registry.check() == revision
    proposed = review(client, values, "budget_setup")
    registry.save_budget(ADMIN, revision, id="other", label="Other", system="ExampleSystem")
    assert apply(client, proposed).status_code == 409
    proposed = review(client, values, "budget_setup")
    users.users[ADMIN.principal] = []
    assert apply(client, proposed).status_code == 403
    login(client, MANAGER.principal)
    assert review(client, values, "budget_setup").status_code == 403
    body = client.get("/budgets/?edit=research").get_data(as_text=True)
    assert 'id="budget-execution-data"' not in body
    assert 'name="run_tag"' not in body


def test_execution_catalog_is_script_safe(portal, registry):
    app, _ = portal
    revision = seed(registry)
    registry.save_account(ADMIN, revision, id="research-account", label="</script><script>alert(1)</script>",
                          system="ExampleSystem", connection_id="compute", build_tag="", run_tag="example-run")
    client = app.test_client()
    login(client)
    body = client.get("/budgets/?edit=research").get_data(as_text=True)
    assert "</script><script>alert(1)</script>" not in body
    assert "\\u003c/script\\u003e" in body


def test_duplicate_system_review_is_a_validation_error(portal, registry):
    app, _ = portal
    seed(registry)
    client = app.test_client()
    login(client)
    before = registry.management_catalog(ADMIN)
    proposed = review(client, {"budget_id": "research", "label": "Do not change",
                              "system": "ExampleSystem", "account_id": "research-account",
                              "allocation_project_id": "another"}, "budget_system")
    assert proposed.status_code == 400
    assert registry.management_catalog(ADMIN) == before


@pytest.mark.parametrize("kind,values", [
    ("budgets", {"label": "Generated budget"}),
    ("connections", {"label": "Generated connection", "server_url": "https://gitlab.example.org",
                     "project_path": "group/project", "token_env": "RESULT_SERVER_GITLAB_TRIGGER_TOKEN"}),
    ("execution_accounts", {"label": "Generated route", "system": "ExampleSystem",
                            "connection_id": "compute", "build_tag": "", "run_tag": "example"}),
])
def test_internal_ids_are_automatic_and_preserved_on_edit(portal, registry, kind, values):
    app, _ = portal
    seed(registry)
    client = app.test_client()
    login(client)
    page = client.get(f"/budgets/?section={kind}")
    assert hidden(page, "id") == ""
    assert not re.search(r'<input type="text" name="id"', page.get_data(as_text=True))
    proposed = review(client, values, kind)
    assert proposed.status_code == 200
    assert apply(client, proposed).status_code == 302
    row = next(row for row in registry.catalog(ADMIN)[kind] if row["label"] == values["label"])
    page = client.get(f"/budgets/?section={kind}&edit={row['id']}")
    assert hidden(page, "id") == row["id"]
    proposed = review(client, {**values, "id": row["id"], "label": "Updated name"}, kind)
    assert apply(client, proposed).status_code == 302
    assert any(item["id"] == row["id"] and item["label"] == "Updated name" for item in registry.catalog(ADMIN)[kind])
