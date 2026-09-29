"""Grouped Budget review and apply retain the existing security boundaries."""

import pytest

pytest.importorskip("sqlcipher3")

from test_budget_routes import (  # noqa: E402,F401
    registry, configured_target, portal, batch_portal, login, hidden, apply, ADMIN, MANAGER, seed,
)
from test_budget_groups import version_three  # noqa: E402


def group_review(client, **overrides):
    page = client.get("/budgets/group")
    values = dict(budget_id="", label="Research", system="Example Center", enabled="on",
                  valid_from="", valid_until="", allocation_project_id="", account_id="", loaded_account_id="",
                  connection_id="gitlab:example", build_tag="", run_tag="example-run",
                  targets=["Example_A", "Example_B"], revision=hidden(page, "revision"),
                  csrf_token=hidden(page, "csrf_token"))
    values.update(overrides)
    return client.post("/budgets/group/review", data=values)


def test_group_review_apply_edit_and_target_removal(batch_portal, registry, configured_target):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    before = registry.catalog(ADMIN)
    proposed = group_review(client)
    assert proposed.status_code == 200
    assert b"Example Center" in proposed.data and b"Example_A" in proposed.data and b"Example_B" in proposed.data
    assert registry.catalog(ADMIN) == before
    result = apply(client, proposed)
    assert result.status_code == 302 and "/budgets/group?edit=" in result.location
    assert apply(client, proposed).status_code == 409
    catalog = registry.catalog(ADMIN)
    budget = catalog["budgets"][0]
    common = catalog["budget_defaults"][0]
    page = client.get(result.location)
    assert hidden(page, "budget_id") == budget["id"]
    assert hidden(page, "loaded_account_id") == common["account_id"]
    proposed = group_review(client, budget_id=budget["id"], account_id=common["account_id"],
                            loaded_account_id=common["account_id"], targets=["Example_B"])
    assert b"Removed" in proposed.data and b"Retained" in proposed.data
    assert apply(client, proposed).status_code == 302
    remaining = registry.catalog(ADMIN)["destinations"]
    old_b = next(row for row in catalog["destinations"] if row["system"] == "Example_B")
    assert remaining == [old_b]
    overview = client.get("/budgets/")
    assert b"Budget @ Managed system" in overview.data
    assert b"Execution targets" in overview.data


@pytest.mark.parametrize("targets", [[], ["Missing"], ["Example_A", "Example_A"], ["Example_A,Example_B"]])
def test_invalid_target_selection_does_not_write(batch_portal, registry, configured_target, targets):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    assert group_review(client, targets=targets).status_code == 400
    assert registry.check() == 0


def test_group_apply_revalidates_canonical_system_catalog(batch_portal, registry, configured_target, tmp_path):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    proposed = group_review(client)
    path = tmp_path / "changed-systems.csv"
    path.write_text("system,tag_build,tag_run\nExample_A,,example-run\n")
    app.config["BUDGET_SYSTEM_CSV"] = str(path)
    assert apply(client, proposed).status_code == 400
    assert registry.check() == 0


def test_group_auth_csrf_identity_and_public_boundary(batch_portal, registry, configured_target):
    app, users = batch_portal
    client = app.test_client()
    assert client.get("/budgets/group").status_code == 302
    seed(registry)
    login(client, MANAGER.principal)
    assert client.get("/budgets/group").status_code == 403
    login(client)
    assert client.post("/budgets/group/review", data={}).status_code == 400
    proposed = group_review(client)
    before = registry.catalog(ADMIN)
    users.users[ADMIN.principal] = []
    assert apply(client, proposed).status_code == 403
    assert registry.catalog(ADMIN) == before
    app.config["PUBLIC_PORTAL_MODE"] = True
    assert client.get("/budgets/group").status_code == 404
    assert client.post("/budgets/group/review", data={"csrf_token": hidden(proposed, "csrf_token")}).status_code == 404


def test_common_and_override_connections_are_revalidated(batch_portal, registry, configured_target, monkeypatch):
    app, _ = batch_portal
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS",
                       "example=gitlab.example.org/group/project,other=other.example.org/group/project")
    registry.save_account(ADMIN, 0, id="override", label="Other target", system="Example Center",
                          connection_id="gitlab:other", build_tag="", run_tag="other-run")
    client = app.test_client()
    login(client)
    proposed = group_review(client, **{"target_account:Example_A": "override"})
    assert proposed.status_code == 200
    before = registry.catalog(ADMIN)
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS",
                       "example=gitlab.example.org/group/project,other=changed.example.org/group/project")
    assert apply(client, proposed).status_code == 409
    assert registry.check() == before["revision"]


def test_legacy_schema_is_not_auto_migrated_by_group_page(batch_portal, registry):
    app, _ = batch_portal
    seed(registry)
    version_three(registry)
    client = app.test_client()
    login(client)
    assert client.get("/budgets/").status_code == 200
    assert client.get("/budgets/group").status_code == 400
    assert registry.catalog(ADMIN)["schema_version"] == 3


def test_common_settings_survive_first_target_override(batch_portal, registry, configured_target):
    app, _ = batch_portal
    revision = registry.save_account(ADMIN, 0, id="override", label="Alternate target", system="Example Center",
                                     connection_id="gitlab:example", build_tag="", run_tag="other-run")
    client = app.test_client()
    login(client)
    proposed = group_review(client, **{"target_account:Example_A": "override"})
    response = apply(client, proposed)
    page = client.get(response.location)
    catalog = registry.catalog(ADMIN)
    assert catalog["revision"] > revision
    assert hidden(page, "loaded_account_id") == catalog["budget_defaults"][0]["account_id"]
    assert hidden(page, "loaded_account_id") != "override"
    assert b"example-run" in page.data
