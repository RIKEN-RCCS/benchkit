"""Grouped Budget review and apply retain the existing security boundaries."""

import pytest
from html.parser import HTMLParser

pytest.importorskip("sqlcipher3")

from test_budget_routes import (  # noqa: E402,F401
    registry, configured_target, portal, batch_portal, login, hidden, apply, ADMIN, MANAGER, seed,
)
from test_budget_groups import version_three  # noqa: E402


def input_value(response, name):
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'input' and 'name' in attrs:
                self.values[attrs['name']] = attrs.get('value', '')

    parser = Inputs()
    parser.feed(response.get_data(as_text=True))
    return parser.values[name]


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
    assert result.status_code == 302 and result.location.startswith("/budgets/#budget-")
    assert apply(client, proposed).status_code == 409
    catalog = registry.catalog(ADMIN)
    budget = catalog["budgets"][0]
    common = catalog["budget_defaults"][0]
    page = client.get('/budgets/group?edit=' + budget['id'])
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
    page = client.get("/budgets/")
    assert page.status_code == 200
    assert b'data-budget-setup' in page.data
    assert b'href="/budgets/batch"' not in page.data
    redirected = client.get("/budgets/batch")
    assert redirected.status_code == 302
    assert redirected.location == "/budgets/#budget-editor"
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
    catalog = registry.catalog(ADMIN)
    assert response.location.startswith('/budgets/#budget-')
    page = client.get('/budgets/group?edit=' + catalog['budgets'][0]['id'])
    assert catalog["revision"] > revision
    assert hidden(page, "loaded_account_id") == catalog["budget_defaults"][0]["account_id"]
    assert hidden(page, "loaded_account_id") != "override"
    assert b"example-run" in page.data


@pytest.mark.parametrize("targets", [["Example_A"], ["Example_A", "Example_B"]])
def test_save_returns_to_list_with_one_time_success(batch_portal, registry, configured_target, targets):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    response = group_review(client, action="save", targets=targets)
    assert response.status_code == 302
    catalog = registry.catalog(ADMIN)
    assert len(catalog['budgets']) == 1
    assert {row['system'] for row in catalog['destinations']} == set(targets)
    page = client.get(response.location)
    assert b'role="status">Budget saved.' in page.data
    assert b'class="budget-saved"' in page.data
    assert b'data-budget-setup' not in page.data
    again = client.get(response.location)
    assert b'Budget saved.' not in again.data
    assert b'class="budget-saved"' not in again.data
    assert registry.catalog(ADMIN) == catalog


@pytest.mark.parametrize("defaults_only", [False, True])
def test_shared_settings_save_requires_review_and_confirmation(batch_portal, registry, configured_target, defaults_only):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    assert group_review(client, action="save", budget_id="first", label="First").status_code == 302
    catalog = registry.catalog(ADMIN)
    account = catalog['budget_defaults'][0]['account_id']
    options = dict(action="save", account_id=account, loaded_account_id=account, targets=['Example_A'])
    if defaults_only:
        registry.save_account(ADMIN, registry.check(), id="override", label="Override", system="Example Center",
                              connection_id="gitlab:example", build_tag="", run_tag="override-run")
        options['target_account:Example_A'] = 'override'
    assert group_review(client, **options, budget_id="second", label="Second").status_code == 302
    # Merely reusing shared settings does not require confirmation.
    assert group_review(client, action="save", budget_id="first", label="Renamed",
                        account_id=account, loaded_account_id=account).status_code == 302
    before = registry.catalog(ADMIN)
    proposed = group_review(client, action="save", budget_id="first", label="Renamed",
                            account_id=account, loaded_account_id=account, run_tag="changed-run")
    assert proposed.status_code == 200
    assert b'Other affected Budgets' in proposed.data and b'Second' in proposed.data
    assert b'name="confirm_shared_change"' in proposed.data
    assert registry.catalog(ADMIN) == before
    assert apply(client, proposed, confirm_shared_change='').status_code == 400
    assert registry.catalog(ADMIN) == before
    assert apply(client, proposed, run_tag='unreviewed').status_code == 302
    assert next(row for row in registry.catalog(ADMIN)['execution_accounts'] if row['id'] == account)['run_tag'] == 'changed-run'
    assert apply(client, proposed).status_code == 409


def test_direct_save_keeps_validation_auth_csrf_and_revision_checks(batch_portal, registry, configured_target):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    assert group_review(client, action='save', targets=['Missing']).status_code == 400
    assert group_review(client, action='save', csrf_token='invalid').status_code == 400
    assert registry.check() == 0
    old_revision = registry.check()
    seed(registry)
    before = registry.catalog(ADMIN)
    assert group_review(client, action='save', revision=old_revision).status_code == 409
    csrf = hidden(client.get('/budgets/group'), 'csrf_token')
    login(client, MANAGER.principal)
    assert client.post('/budgets/group/review', data={'action': 'save', 'csrf_token': csrf}).status_code == 403
    assert registry.catalog(ADMIN) == before


def test_target_settings_only_offer_matching_scope_and_preserve_override(batch_portal, registry, configured_target):
    class TargetOptions(HTMLParser):
        def __init__(self, body):
            super().__init__()
            self.active = None
            self.options = {}
            self.selected = {}
            self.feed(body)

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'select' and attrs.get('name', '').startswith('target_account:'):
                self.active = attrs['name']
                self.options[self.active] = []
            if tag == 'option' and self.active:
                self.options[self.active].append(attrs['value'])
                if 'selected' in attrs:
                    self.selected[self.active] = attrs['value']

        def handle_endtag(self, tag):
            if tag == 'select':
                self.active = None

    app, _ = batch_portal
    revision = registry.save_account(ADMIN, 0, id='foreign', label='Other scope', system='Other Center',
                                     connection_id='gitlab:example', build_tag='', run_tag='foreign-run')
    registry.save_account(ADMIN, revision, id='override', label='Alternative', system='Example Center',
                          connection_id='gitlab:example', build_tag='alternate-build', run_tag='alternate-run')
    client = app.test_client()
    login(client)
    response = group_review(client, action='save', **{'target_account:Example_A': 'override'})
    assert response.status_code == 302
    catalog = registry.catalog(ADMIN)
    budget = catalog['budgets'][0]
    body = client.get('/budgets/group?edit=' + budget['id']).get_data(as_text=True)
    options = TargetOptions(body)
    assert options.options['target_account:Example_A'] == ['', 'override']
    assert options.selected['target_account:Example_A'] == 'override'
    assert 'data-target-run>alternate-run</dd>' in body
    assert 'data-target-run>example-run</dd>' in body
    for destination in catalog['destinations']:
        expected = 'alternate-run' if destination['system'] == 'Example_A' else 'example-run'
        assert registry.resolve(ADMIN, destination['id'])['route']['run_tag'] == expected
    assert group_review(client, action='save', **{'target_account:Example_A': 'foreign'}).status_code == 400
    assert registry.catalog(ADMIN) == catalog


def test_invalid_dates_retain_group_inputs_and_targets(batch_portal, registry, configured_target):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    response = group_review(client, action='save', label='<script>bad()</script>',
                            valid_from='2030-02-02', valid_until='2030-02-01',
                            build_tag='custom-build', run_tag='custom-run', targets=['Example_B'])
    assert response.status_code == 400
    assert input_value(response, 'label') == '<script>bad()</script>'
    assert b'<script>bad()</script>' not in response.data
    assert input_value(response, 'build_tag') == 'custom-build'
    assert input_value(response, 'run_tag') == 'custom-run'
    assert input_value(response, 'valid_from') == '2030-02-02'
    assert b'id="budget-error-valid_until"' in response.data
    assert b'aria-invalid="true"' in response.data
    assert b'value="Example_B" aria-label="Use Example_B" checked' in response.data
    assert b'value="Example_A" aria-label="Use Example_A" checked' not in response.data
    assert registry.check() == 0


def test_conflict_retains_entries_and_requires_explicit_review(batch_portal, registry, configured_target):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    seed(registry)
    before = registry.catalog(ADMIN)
    response = group_review(client, action='save', revision=0, label='Retained proposal')
    assert response.status_code == 409
    assert input_value(response, 'label') == 'Retained proposal'
    assert hidden(response, 'revision') == str(before['revision'])
    assert b'value="review">Review latest changes' in response.data
    assert b'value="save">Save budget' not in response.data
    assert registry.catalog(ADMIN) == before
    proposal = group_review(client, action='review', revision=hidden(response, 'revision'), label='Retained proposal')
    assert proposal.status_code == 200 and b'name="ticket"' in proposal.data
    assert registry.catalog(ADMIN) == before
    assert apply(client, proposal).status_code == 302


def test_apply_conflict_restores_signed_proposal_not_untrusted_fields(batch_portal, registry, configured_target):
    app, _ = batch_portal
    client = app.test_client()
    login(client)
    proposal = group_review(client, label='Reviewed label', run_tag='reviewed-run')
    seed(registry)
    before = registry.catalog(ADMIN)
    response = apply(client, proposal, label='Forged label', run_tag='forged-run')
    assert response.status_code == 409
    assert input_value(response, 'label') == 'Reviewed label'
    assert input_value(response, 'run_tag') == 'reviewed-run'
    assert hidden(response, 'loaded_account_id') == ''
    assert b'value="review">Review latest changes' in response.data
    assert registry.catalog(ADMIN) == before


def test_failed_recovery_never_exposes_another_managers_budget(portal, registry):
    app, _ = portal
    seed(registry)
    registry.save_budget(ADMIN, registry.check(), id='private', label='Private budget', system='Private system')
    client = app.test_client()
    login(client, MANAGER.principal)
    csrf = hidden(client.get('/budgets/?edit=research'), 'csrf_token')
    response = client.post('/budgets/review', data=dict(kind='budgets', revision=0, id='private',
                           label='Attempt', system='Private system', csrf_token=csrf))
    assert response.status_code == 409
    assert b'Private budget' not in response.data
    assert b'name="label"' not in response.data
