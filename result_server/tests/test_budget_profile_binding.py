"""Profile selection persistence, HTTP authorization and both trigger paths."""

from datetime import UTC, datetime
import json
import re

import pytest

pytest.importorskip("sqlcipher3")

from test_budget_pipeline import selection, registry, configured_target  # noqa: F401
from test_budget_routes import portal, login, hidden  # noqa: F401
from test_budget_registry import ADMIN, MANAGER
from utils import budget_profile_binding as bindings
from utils.budget_registry import RegistryError
from utils.execution_profiles import ExecutionProfileStore, normalize_trigger_definition
from utils.gitlab_pipeline import GitLabPipelineSubmitResult
import trigger_runner


@pytest.fixture
def editor(selection, portal, tmp_path, monkeypatch):
    app, users = portal
    path = tmp_path / "profiles.sqlite3"
    app.config["EXECUTION_PROFILE_DB_PATH"] = str(path)
    profile = selection["profile"]
    profile["system"] = ["Fugaku"]
    store = ExecutionProfileStore(str(path))
    store.upsert_profile(profile, actor=ADMIN.principal)
    monkeypatch.setenv("RESULT_SERVER_BUDGET_DB_PATH", str(selection["registry"].storage.path))
    monkeypatch.setenv("RESULT_SERVER_BUDGET_DB_KEY_FILE", str(selection["registry"].storage.key_file))
    monkeypatch.setenv("RESULT_SERVER_BUDGET_PIPELINE_TARGET_REFS", '{"example":["develop"]}')
    original = bindings.current_actor
    monkeypatch.setattr(bindings, "current_actor", lambda principal, source=None: original(principal, source or users))
    return app, users, store


def save_selection(client):
    page = client.get("/admin/execution-profiles?edit=profile")
    values = {name: hidden(page, name) for name in ("csrf_token", "registry_revision", "profile_fingerprint")}
    values["destination_id"] = "selected"
    return client.post("/admin/execution-profiles/profile/budget", data=values, follow_redirects=True)


def test_admin_selects_and_saves_without_duplicate_gitlab_input(editor, monkeypatch):
    app, _, store = editor
    client = app.test_client()
    login(client)
    page = save_selection(client)
    assert page.status_code == 200
    assert "Budget selection saved" in page.get_data(as_text=True)
    row = re.search(r'<tr data-profile-row.*?</tr>', page.get_data(as_text=True), re.S).group()
    assert 'name="gitlab_target"' not in row
    assert bindings.has_budget_binding(store.list_profiles()[0])
    submitted = []
    def submit(plan, *, token):
        submitted.append(plan)
        return GitLabPipelineSubmitResult(201, {"id": 1}, [])
    monkeypatch.setattr("routes.admin.submit_pipeline_plan", submit)
    response = client.post("/admin/execution-profiles/submit", data={
        "csrf_token": hidden(page, "csrf_token"), "profile_id": "profile", "confirm_submit": "on",
        "gitlab_target": "unrelated", "target_ref": "develop"})
    assert response.status_code == 200
    assert len(submitted) == 1
    assert "BK_EXECUTION_ROUTE_SNAPSHOT" in submitted[0].payload["variables"]
    assert "group%2Fproject" in submitted[0].api_url


def test_csrf_and_live_identity_protect_binding(editor):
    app, users, store = editor
    client = app.test_client()
    login(client)
    assert client.post("/admin/execution-profiles/profile/budget", data={"destination_id": "selected"}).status_code == 400
    page = client.get("/admin/execution-profiles?edit=profile")
    values = {name: hidden(page, name) for name in ("csrf_token", "registry_revision", "profile_fingerprint")}
    values["destination_id"] = "selected"
    users.users[ADMIN.principal] = []
    assert client.post("/admin/execution-profiles/profile/budget", data=values).status_code == 403
    assert not bindings.has_budget_binding(store.list_profiles()[0])


def test_binding_survives_profile_updates_and_scope_changes_require_review(editor, selection):
    app, users, store = editor
    client = app.test_client()
    login(client)
    save_selection(client)
    profile = store.list_profiles()[0]
    binding = profile["metadata_json"]["budget_binding"]
    profile["metadata_json"] = {}
    profile["activity"] = "Updated Activity"
    store.upsert_profile(profile, actor=ADMIN.principal)
    updated = store.list_profiles()[0]
    assert updated["metadata_json"]["budget_binding"] == binding
    with pytest.raises(RegistryError):
        bindings.build_bound_profile_plan(updated, target_ref="develop", result_server_url="",
                                           registry=selection["registry"], users=users)


def test_binding_cannot_be_injected_through_generic_profile_upsert(editor):
    _, _, store = editor
    profile = store.list_profiles()[0]
    profile["metadata_json"]["budget_binding"] = {"selected_by": ADMIN.principal}
    store.upsert_profile(profile, actor=MANAGER.principal)
    assert not bindings.has_budget_binding(store.list_profiles()[0])


def test_concurrent_binding_edit_requires_reload(editor):
    app, _, store = editor
    client = app.test_client()
    login(client)
    profile = store.list_profiles()[0]
    previous = bindings.selection_fingerprint(profile)
    save_selection(client)
    binding = store.list_profiles()[0]["metadata_json"]["budget_binding"]
    with pytest.raises(ValueError):
        store.set_budget_binding("profile", binding, expected_fingerprint=previous, actor=ADMIN.principal)


def test_unrelated_registry_revision_does_not_stop_bound_profile(editor, selection):
    app, users, store = editor
    client = app.test_client()
    login(client)
    save_selection(client)
    registry = selection["registry"]
    revision = registry.save_budget(ADMIN, registry.check(), id="other", label="Other", system="Other", enabled=True)
    result = bindings.build_bound_profile_plan(store.list_profiles()[0], target_ref="develop", result_server_url="",
                                               registry=registry, users=users)
    assert result.snapshot["registry_revision"] == revision


@pytest.mark.parametrize("kind", ["scheduled", "watch_event"])
def test_trigger_uses_bound_target_and_records_snapshot(editor, monkeypatch, kind):
    app, _, store = editor
    client = app.test_client()
    login(client)
    save_selection(client)
    trigger, errors = normalize_trigger_definition(dict(id="trigger", profile_id="profile", enabled=True,
                                                        trigger_type=kind, cron_expr="* * * * *", timezone="UTC",
                                                        watch_kind="repo_ref", watch_targets=["https://example.org/source.git@main"],
                                                        gitlab_target="unrelated", target_ref="develop"))
    assert not errors
    store.upsert_trigger_definition(trigger, actor=ADMIN.principal)
    store.upsert_trigger_observation("trigger", "https://example.org/source.git@main", "old")
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TRIGGER_TOKEN_EXAMPLE", "synthetic-token")
    submitted = []
    def submit(plan, *, token):
        submitted.append((plan, token))
        return GitLabPipelineSubmitResult(201, {"id": 123}, [])
    evaluations = trigger_runner.run_triggers(db_path=store.db_path, dry_run=False, submit=True,
                                               result_server_url="https://results.example.org",
                                               now=datetime(2026, 10, 5, 0, 0, tzinfo=UTC),
                                               ls_remote=lambda *args: "new", submit_pipeline=submit)
    assert len(submitted) == 1
    assert submitted[0][1] == "synthetic-token"
    assert evaluations[0].status == "submitted"
    run = store.list_trigger_runs("trigger")[0]
    assert "budget_snapshot" in run["payload_json"]
    assert "synthetic-token" not in json.dumps(run)


def test_authority_revoked_between_evaluation_and_submit_blocks_network(editor, monkeypatch):
    app, users, store = editor
    client = app.test_client()
    login(client)
    save_selection(client)
    trigger, errors = normalize_trigger_definition(dict(id="trigger", profile_id="profile", trigger_type="scheduled",
                                                        cron_expr="* * * * *", timezone="UTC", target_ref="develop"))
    assert not errors
    store.upsert_trigger_definition(trigger, actor=ADMIN.principal)
    evaluate = trigger_runner.evaluate_trigger
    def revoke(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        users.users[ADMIN.principal] = []
        return result
    monkeypatch.setattr(trigger_runner, "evaluate_trigger", revoke)
    evaluations = trigger_runner.run_triggers(db_path=store.db_path, dry_run=False, submit=True,
                                               now=datetime(2026, 10, 5, 0, 0, tzinfo=UTC),
                                               submit_pipeline=lambda *args, **kwargs: pytest.fail("Must not submit"))
    assert evaluations[0].errors
    assert evaluations[0].status != "submitted"


def test_submission_requires_explicit_ci_capability(editor, monkeypatch):
    app, _, _ = editor
    client = app.test_client()
    login(client)
    page = save_selection(client)
    monkeypatch.delenv("RESULT_SERVER_BUDGET_PIPELINE_TARGET_REFS")
    monkeypatch.setattr("routes.admin.submit_pipeline_plan", lambda *a, **kw: pytest.fail("Must not submit"))
    response = client.post("/admin/execution-profiles/submit", data={
        "csrf_token": hidden(page, "csrf_token"), "profile_id": "profile", "confirm_submit": "on", "target_ref": "develop"})
    assert "Budget submission is not enabled" in response.get_data(as_text=True)


def test_public_portal_cannot_access_binding_editor(editor):
    app, _, _ = editor
    client = app.test_client()
    login(client)
    app.config["PUBLIC_PORTAL_MODE"] = True
    assert client.get("/admin/execution-profiles?edit=profile").status_code == 404


@pytest.mark.parametrize("capabilities", ['[]', '{"example":"develop"}', '{"example":["other"]}',
                                         '{"":["develop"]}', '{"example":["develop"],"other":false}'])
def test_capability_configuration_fails_closed(selection, monkeypatch, capabilities):
    from utils.budget_pipeline import build_budget_pipeline_plan
    target = build_budget_pipeline_plan(**selection).target
    monkeypatch.setenv("RESULT_SERVER_BUDGET_PIPELINE_TARGET_REFS", capabilities)
    with pytest.raises(RegistryError):
        bindings.require_budget_pipeline_capability(target, "develop")


@pytest.mark.parametrize("metadata", [{"budget_binding": {"snapshot": None}},
                                      {"_invalid_metadata_json": "{"}, ["unexpected"]])
def test_malformed_binding_metadata_never_selects_legacy(editor, metadata):
    _, _, store = editor
    profile = store.list_profiles()[0]
    profile["metadata_json"] = metadata
    assert bindings.has_budget_binding(profile)
    with pytest.raises(RegistryError):
        bindings.build_bound_profile_plan(profile, target_ref="develop", result_server_url="")
