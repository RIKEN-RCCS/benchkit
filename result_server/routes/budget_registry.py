"""Authenticated, review-before-apply management of the shared budget registry."""

from functools import wraps
from collections import Counter
import csv
import os
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, make_response, redirect, render_template, request, send_file, session, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from utils.budget_registry import BudgetRegistry, RegistryActor, RegistryConflict, RegistryError, RegistryPermissionError
from utils.budget_runner_choices import runner_choices
from utils.encrypted_sqlite import EncryptedDatabaseError
from utils.rate_limit import rate_limited
from utils.runner_observations import RunnerObservations
from utils.user_store import get_user_store


budget_registry_bp = Blueprint("budget_registry", __name__)


@budget_registry_bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response

# All editable fields are explicitly allowlisted. Infrastructure changes are
# reserved for CX administrators, independent of budget manager assignments.
SPECS = {
    "budget_group": ("Budget / Managed system", "save_budget_group", [
        ("budget_id", "Budget ID", "hidden"),
        ("label", "Budget name", "text"), ("enabled", "Enabled", "checkbox"),
        ("system", "Managed system", "text"), ("allocation_project_id", "Scheduler allocation ID", "text"),
        ("valid_from", "Valid from", "date"), ("valid_until", "Valid until", "date"),
        ("account_id", "Common execution settings", "execution_accounts"),
        ("build_tag", "Build tag", "text"), ("run_tag", "Run tag", "text"),
        ("connection_id", "GitLab connection", "connections")]),
    "budget_batch": ("Budget batch", "create_budget_batch", []),
    "budget_setup": ("Budget @ System", "save_budget_setup", [
        ("budget_id", "Budget ID", "hidden"), ("destination_id", "Destination ID", "hidden"),
        ("label", "Budget name", "text"), ("enabled", "Enabled", "checkbox"),
        ("system", "System", "text"), ("allocation_project_id", "Scheduler allocation ID", "text"),
        ("valid_from", "Valid from", "date"), ("valid_until", "Valid until", "date"),
        ("account_id", "Saved execution settings", "execution_accounts"),
        ("build_tag", "Build tag", "text"),
        ("run_tag", "Run tag", "text"),
        ("connection_id", "GitLab connection", "connections")]),
    "budget_system": ("Budget @ System", "save_budget_system", [
        ("budget_id", "Budget ID", "hidden"), ("destination_id", "Destination ID", "hidden"),
        ("label", "Budget name", "text"), ("enabled", "Enabled", "checkbox"),
        ("valid_from", "Valid from", "date"), ("valid_until", "Valid until", "date"),
        ("system", "System", "systems"), ("account_id", "Execution settings", "execution_accounts"),
        ("allocation_project_id", "Scheduler allocation ID", "text")]),
    "budgets": ("Budgets", "save_budget", [
        ("id", "ID", "text"), ("label", "Budget", "text"), ("enabled", "Enabled", "checkbox"),
        ("system", "System", "text"),
        ("valid_from", "Valid from", "date"), ("valid_until", "Valid until", "date")]),
    "destinations": ("Execution destinations", "save_destination", [
        ("id", "ID", "text"), ("budget_id", "Budget", "budgets"), ("system", "System", "text"),
        ("account_id", "Execution settings", "execution_accounts"),
        ("allocation_project_id", "Scheduler allocation ID", "text")]),
    "budget_managers": ("Budget managers", "set_manager", [
        ("budget_id", "Budget", "budgets"), ("principal", "Manager email", "email"),
        ("assigned", "Assigned", "checkbox")]),
    "execution_accounts": ("Execution settings", "save_account", [
        ("id", "ID", "text"), ("label", "Name", "text"), ("system", "System", "text"),
        ("connection_id", "Connection", "connections"),
        ("build_tag", "Build tag", "text"), ("run_tag", "Run tag", "text"),
        ("id_token_audience", "ID token audience", "text")]),
    "connections": ("Connections", "save_connection", [
        ("id", "ID", "text"), ("label", "Name", "text"), ("server_url", "GitLab URL", "url"),
        ("project_path", "Project path", "text"), ("token_env", "Credential reference", "text")]),
}


def register_budget_registry(app, prefix=""):
    """Configure paths only; never open, create, or migrate a database at startup."""
    app.config["BUDGET_REGISTRY_DB_PATH"] = os.environ.get("RESULT_SERVER_BUDGET_DB_PATH", "")
    app.config["BUDGET_REGISTRY_KEY_FILE"] = os.environ.get("RESULT_SERVER_BUDGET_DB_KEY_FILE", "")
    app.register_blueprint(budget_registry_bp, url_prefix=f"{prefix}/budgets")


def _restricted(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_app.config.get("PUBLIC_PORTAL_MODE"):
            response = make_response("Not found", 404)
        elif not session.get("authenticated"):
            response = redirect(url_for("auth.login"))
        else:
            try:
                response = make_response(view(*args, **kwargs))
            except RegistryPermissionError:
                response = make_response("Budget access is not permitted", 403)
            except RegistryConflict:
                response = make_response("Registry changed. Reload before saving.", 409)
            except RegistryError as exc:
                response = make_response(render_template("budget_registry_error.html", message=str(exc)), 400)
            except EncryptedDatabaseError:
                response = make_response("Budget registry is unavailable", 503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response
    return wrapped


def _context():
    principal = session.get("user_email", "")
    try:
        users = get_user_store()
        exists = bool(principal) and users.user_exists(principal)
        affiliations = users.get_affiliations(principal) if exists else []
    except Exception:
        # An unavailable identity backend must not reuse session privileges or
        # expose connection details in an error page.
        raise EncryptedDatabaseError("Identity service is unavailable") from None
    if not exists:
        raise RegistryPermissionError("Authenticated identity is required")
    actor = RegistryActor(principal, "admin" in affiliations)
    path = current_app.config.get("BUDGET_REGISTRY_DB_PATH")
    key_file = current_app.config.get("BUDGET_REGISTRY_KEY_FILE")
    if not path or not key_file:
        raise EncryptedDatabaseError("Budget registry is not configured")
    store = BudgetRegistry(path, key_file)
    catalog = store.management_catalog(actor)
    connections = {row["id"]: row for row in catalog["connections"]}
    for account in catalog["execution_accounts"]:
        connection = connections.get(account["connection_id"], {})
        name = connection.get("label", "Unavailable connection")
        if connection and not connection["available"]:
            name += " (Unavailable)"
        account["display_label"] = (f"{name} / Build: {account['build_tag'] or '-'} / "
                                    f"Run: {account['run_tag']} @ {account['system']}")
    counts = Counter(row["display_label"] for row in catalog["execution_accounts"])
    for account in catalog["execution_accounts"]:
        if counts[account["display_label"]] > 1:
            account["display_label"] += f" [ID: {account['id']}]"
    return store, actor, catalog


def _kinds(actor):
    return list(SPECS) if actor.is_admin else ["budgets"]


def _kind(value, actor):
    if value not in _kinds(actor):
        raise RegistryPermissionError("Registry section is not permitted")
    return value


def _signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="budget-registry-review-v4")


def _values(kind, catalog):
    values = {}
    for name, _label, input_type in SPECS[kind][2]:
        value = request.form.get(name, "").strip()
        if len(value) > 512:
            raise RegistryError("Registry input is too long")
        if input_type == "checkbox":
            if value not in ("", "on"):
                raise RegistryError("Invalid enabled state")
            value = value == "on"
        values[name] = value
    if "," in values.get("system", ""):
        raise RegistryError("Enter one system name, without commas. For multiple systems, open Budget Management and choose Add multiple systems.")
    ids = ("budget_id", "destination_id") if kind in ("budget_setup", "budget_system") else ("id",)
    for name in ids:
        if name in values and not values[name]:
            values[name] = uuid4().hex
    if kind == "budget_setup":
        if values["account_id"] != request.form.get("loaded_account_id", ""):
            raise RegistryError("Load the selected execution settings before reviewing")
        values["new_account"] = not values["account_id"]
        if not values["account_id"]:
            values["account_id"] = uuid4().hex
    if kind in ("budget_setup", "execution_accounts"):
        connection = next((row for row in catalog["connections"] if row["id"] == values["connection_id"]), None)
        if not connection or not connection["available"]:
            raise RegistryError("Select an available GitLab connection")
        values["expected_connection"] = connection
    return values


def _current(catalog, kind, values):
    if kind in ("budget_setup", "budget_system"):
        budget = next((row for row in catalog["budgets"] if row["id"] == values.get("budget_id")), {})
        destination = next((row for row in catalog["destinations"] if row["id"] == values.get("destination_id")), {})
        return {**budget, **destination,
                "budget_id": budget.get("id"), "destination_id": destination.get("id")}
    keys = ("budget_id", "principal") if kind == "budget_managers" else ("id",)
    row = next((row for row in catalog[kind] if all(row[key] == values.get(key) for key in keys)), {})
    if kind == "budget_managers":
        return {"budget_id": values.get("budget_id"), "principal": values.get("principal"), "assigned": bool(row)}
    return row


def _impact(catalog, kind, values):
    destinations = catalog["destinations"]
    if kind == "budget_setup":
        impact = {values["destination_id"]: dict(values, id=values["destination_id"])}
        account = next((row for row in catalog["execution_accounts"] if row["id"] == values["account_id"]), {})
        if account and any(account[name] != values[name] for name in ("build_tag", "run_tag", "connection_id")):
            impact.update({row["id"]: row for row in destinations if row["account_id"] == account["id"]})
        impact[values["destination_id"]] = dict(values, id=values["destination_id"])
        return list(impact.values())
    if kind == "budget_system":
        affected = [row for row in destinations if row["budget_id"] == values["budget_id"]
                    and row["id"] != values["destination_id"]]
        return affected + [dict(values, id=values["destination_id"])]
    if kind in ("budgets", "budget_managers"):
        budget = values.get("id") if kind == "budgets" else values.get("budget_id")
        return [row for row in destinations if row["budget_id"] == budget]
    if kind == "destinations":
        return [values]
    account_ids = {values["id"]}
    if kind == "connections":
        account_ids = {row["id"] for row in catalog["execution_accounts"] if row["connection_id"] == values["id"]}
    return [row for row in destinations if row["account_id"] in account_ids]


def _runner_choices(actor, catalog):
    if not actor.is_admin:
        return {}
    path = current_app.config.get("RUNNER_MONITOR_DB_PATH")
    key = current_app.config.get("RUNNER_MONITOR_KEY_FILE")
    if not path or not key:
        return {}
    try:
        snapshot = RunnerObservations(path, key).read()
    except EncryptedDatabaseError:
        return {row["id"]: {"state": "unavailable", "runners": []} for row in catalog["connections"]}
    return runner_choices(catalog["connections"], snapshot)


@budget_registry_bp.route("/editor.js", methods=["GET"])
@_restricted
def editor_script():
    _store, actor, _catalog = _context()
    if not actor.is_admin:
        raise RegistryPermissionError("Budget access is not permitted")
    return send_file(Path(__file__).resolve().parents[1] / "static" / "js" / "budget_registry.js",
                     mimetype="text/javascript")


def _batch_systems(catalog):
    path = current_app.config.get("BUDGET_SYSTEM_CSV") or Path(__file__).resolve().parents[2] / "config" / "system.csv"
    registered = {row["system"] for row in catalog["destinations"]}
    registered.update(row["system"] for row in catalog["budgets"])
    rows, seen = [], set()
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                system = row["system"].strip()
                if not system or system in seen:
                    raise ValueError
                seen.add(system)
                rows.append(dict(system=system, build_tag=row["tag_build"].strip(),
                                 run_tag=row["tag_run"].strip(), registered=system in registered))
    except (OSError, UnicodeError, KeyError, ValueError, AttributeError, csv.Error):
        raise RegistryError("System configuration is unavailable or invalid") from None
    return rows


def _group_targets(values, catalog):
    available = {row["system"] for row in _batch_systems(catalog)}
    if any(row["system"] not in available for row in values["targets"]):
        raise RegistryError("Select execution targets present in the system configuration")


@budget_registry_bp.route("/group", methods=["GET"])
@_restricted
def group():
    _store, actor, catalog = _context()
    _kind("budget_group", actor)
    if catalog["schema_version"] < 4:
        raise RegistryError("Execution groups require an explicit database migration")
    editing = request.args.get("edit", "")
    budget = next((row for row in catalog["budgets"] if row["id"] == editing), {})
    if editing and not budget:
        raise RegistryPermissionError("Registry entry is not permitted")
    targets = [row for row in catalog["destinations"] if row["budget_id"] == editing]
    defaults = next((row for row in catalog["budget_defaults"] if row["id"] == editing), {})
    account_id = defaults.get("account_id", targets[0]["account_id"] if targets else "")
    account = next((row for row in catalog["execution_accounts"] if row["id"] == account_id), {})
    selected = {**budget, "budget_id": editing, "account_id": account_id,
                "allocation_project_id": defaults.get("allocation_project_id", targets[0]["allocation_project_id"] if targets else "")}
    selected.update({name: account.get(name, "") for name in ("connection_id", "build_tag", "run_tag")})
    systems = _batch_systems(catalog)
    known = {row["system"] for row in systems}
    systems.extend(dict(system=row["system"], build_tag="", run_tag="", unavailable=True)
                   for row in targets if row["system"] not in known)
    allocations = {row["allocation_project_id"] for row in targets}
    return render_template("budget_registry_group.html", actor=actor, catalog=catalog, specs=SPECS,
                           kind="budget_group", budget=budget, selected=selected, systems=systems,
                           targets={row["system"]: row for row in targets}, allocation_conflict=len(allocations) > 1,
                           runner_choices=_runner_choices(actor, catalog),
                           execution_choices=catalog["execution_accounts"])


@budget_registry_bp.route("/group/review", methods=["POST"])
@_restricted
@rate_limited(max_per_minute=20, key_fn=lambda _: session.get("user_email", ""), scope="budget_review")
def group_review():
    store, actor, catalog = _context()
    _kind("budget_group", actor)
    try:
        revision = int(request.form.get("revision", ""))
    except ValueError:
        raise RegistryError("A registry revision is required") from None
    if revision != catalog["revision"]:
        raise RegistryConflict("Registry changed")
    values = {}
    for name, _label, input_type in SPECS["budget_group"][2]:
        value = request.form.get(name, "").strip()
        if len(value) > 512:
            raise RegistryError("Registry input is too long")
        if input_type == "checkbox":
            if value not in ("", "on"):
                raise RegistryError("Invalid enabled state")
            value = value == "on"
        values[name] = value
    values["budget_id"] = values["budget_id"] or uuid4().hex
    if values["account_id"] != request.form.get("loaded_account_id", ""):
        raise RegistryError("Load the selected execution settings before reviewing")
    values["new_account"] = not values["account_id"]
    values["account_id"] = values["account_id"] or uuid4().hex
    connection = next((row for row in catalog["connections"] if row["id"] == values["connection_id"] and row["available"]), None)
    if not connection:
        raise RegistryError("Select an available GitLab connection")
    values["expected_connection"] = connection
    previous = {row["system"]: row for row in catalog["destinations"] if row["budget_id"] == values["budget_id"]}
    selected = request.form.getlist("targets")
    if not 1 <= len(selected) <= 64 or len(set(selected)) != len(selected):
        raise RegistryError("Select between 1 and 64 distinct execution targets")
    values["targets"] = [dict(id=previous.get(system, {}).get("id", uuid4().hex), system=system,
                              account_id=request.form.get("target_account:" + system, "").strip())
                         for system in selected]
    _group_targets(values, catalog)
    accounts = {row["id"]: row for row in catalog["execution_accounts"]}
    values["expected_target_connections"] = {}
    for target in values["targets"]:
        if not target["account_id"]:
            continue
        account = accounts.get(target["account_id"])
        target_connection = next((row for row in catalog["connections"]
                                  if account and row["id"] == account["connection_id"] and row["available"]), None)
        if not target_connection:
            raise RegistryError("Select available execution settings for every target")
        values["expected_target_connections"][target_connection["id"]] = target_connection
    store.save_budget_group(actor, revision, **values, preview=True)
    ticket = _signer().dumps(dict(actor=actor.principal, revision=revision, kind="budget_group", values=values))
    if len(ticket) > 16384:
        raise RegistryError("Review is too large; select fewer execution targets")
    before = next((row for row in catalog["budgets"] if row["id"] == values["budget_id"]), {})
    defaults = next((row for row in catalog["budget_defaults"] if row["id"] == values["budget_id"]), {})
    account = accounts.get(values["account_id"], {})
    old_targets = list(previous.values())
    current_allocation = old_targets[0]["allocation_project_id"] if old_targets else ""
    before = {**before, "allocation_project_id": defaults.get("allocation_project_id", current_allocation)}
    affected = {row["id"]: row for row in old_targets}
    if account and any(account[name] != values[name] for name in ("connection_id", "build_tag", "run_tag")):
        affected.update({row["id"]: row for row in catalog["destinations"] if row["account_id"] == account["id"]})
    affected.update({row["id"]: dict(row, budget_id=values["budget_id"]) for row in values["targets"]})
    return render_template("budget_registry_review.html", ticket=ticket, kind="budget_group", specs=SPECS,
                           revision=revision, before=before, values=values, catalog=catalog,
                           groups=[("Budget", SPECS["budget_group"][2][:7], before),
                                   ("Common execution settings", SPECS["budget_group"][2][7:],
                                    {**account, "account_id": account.get("id", "")})],
                           old_targets=old_targets, impact=list(affected.values()),
                           back_url=url_for("budget_registry.group", edit=values["budget_id"] if before.get("id") else ""))


@budget_registry_bp.route("/batch", methods=["GET"])
@_restricted
def batch():
    _store, actor, catalog = _context()
    _kind("budget_batch", actor)
    return render_template("budget_registry_batch.html", actor=actor, catalog=catalog,
                           specs=SPECS, kind="budget_batch", selected={}, systems=_batch_systems(catalog),
                           runner_choices=_runner_choices(actor, catalog))


@budget_registry_bp.route("/batch/review", methods=["POST"])
@_restricted
@rate_limited(max_per_minute=20, key_fn=lambda _: session.get("user_email", ""), scope="budget_review")
def batch_review():
    store, actor, catalog = _context()
    _kind("budget_batch", actor)
    try:
        revision = int(request.form.get("revision", ""))
    except ValueError:
        raise RegistryError("A registry revision is required") from None
    if revision != catalog["revision"]:
        raise RegistryConflict("Registry changed")
    selected = request.form.getlist("systems")
    available = {row["system"] for row in _batch_systems(catalog) if not row["registered"]}
    if not 1 <= len(selected) <= 64 or len(set(selected)) != len(selected) or not set(selected) <= available:
        raise RegistryError("Select unregistered systems from the list")
    connection = next((row for row in catalog["connections"]
                       if row["id"] == request.form.get("connection_id") and row["available"]), None)
    if not connection:
        raise RegistryError("Select an available GitLab connection")
    enabled = request.form.get("enabled", "")
    if enabled not in ("", "on"):
        raise RegistryError("Invalid enabled state")
    entries = [dict(budget_id=uuid4().hex, destination_id=uuid4().hex, account_id=uuid4().hex,
                    system=system, label=request.form.get("label:" + system, "").strip()) for system in selected]
    values = dict(entries=entries, connection_id=connection["id"], expected_connection=connection,
                  enabled=enabled == "on",
                  **{name: request.form.get(name, "").strip()
                     for name in ("build_tag", "run_tag", "allocation_project_id")})
    store.create_budget_batch(actor, revision, **values, preview=True)
    ticket = _signer().dumps(dict(actor=actor.principal, revision=revision, kind="budget_batch", values=values))
    if len(ticket) > 16384:
        raise RegistryError("Batch review is too large; select fewer systems")
    return render_template("budget_registry_batch_review.html", ticket=ticket, values=values,
                           connection=connection, revision=revision, back_url=url_for("budget_registry.batch"))


@budget_registry_bp.route("/", methods=["GET"])
@_restricted
def index():
    _store, actor, catalog = _context()
    section = request.args.get("section", "overview")
    if section == "overview":
        editing = request.args.get("edit", "")
        budget = next((row for row in catalog["budgets"] if row["id"] == editing), {})
        if editing and not budget:
            raise RegistryPermissionError("Registry entry is not permitted")
        destination = next((row for row in catalog["destinations"] if row["budget_id"] == editing), {})
        if request.args.get("destination") and request.args["destination"] != destination.get("id"):
            raise RegistryPermissionError("Registry entry is not permitted")
        selected = {**budget, **destination, "budget_id": editing, "destination_id": destination.get("id", "")}
        if actor.is_admin:
            account = next((row for row in catalog["execution_accounts"] if row["id"] == destination.get("account_id")), {})
            selected.update({name: account.get(name, "") for name in ("build_tag", "run_tag", "connection_id")})
        managers = [row for row in catalog["budget_managers"] if row["budget_id"] == editing]
        return render_template("budget_registry_overview.html", actor=actor, catalog=catalog,
                               specs=SPECS, kind="overview", budget=budget, selected=selected,
                               grouped_budget=bool(budget) and (any(row["id"] == editing for row in catalog["budget_defaults"]) or any(row["system"] != budget["system"] for row in catalog["destinations"] if row["budget_id"] == editing)),
                               managers=managers,
                               runner_choices=_runner_choices(actor, catalog),
                               execution_choices=[{key: row[key] for key in ("id", "label", "system", "build_tag", "run_tag", "connection_id")}
                                                  for row in catalog["execution_accounts"]],
                               systems=sorted({row["system"] for row in catalog["execution_accounts"]}))
    kind = _kind(section, actor)
    if kind in ("budget_setup", "budget_system"):
        return redirect(url_for("budget_registry.index"))
    if kind == "budget_batch":
        return redirect(url_for("budget_registry.batch"))
    if kind == "budget_group":
        return redirect(url_for("budget_registry.group"))
    editing = request.args.get("edit", "")
    values = {"id": editing, "budget_id": request.args.get("budget_id"), "principal": editing}
    selected = _current(catalog, kind, values) if editing else {}
    if editing and not selected:
        raise RegistryPermissionError("Registry entry is not permitted")
    if kind == "connections" and selected.get("target_id"):
        raise RegistryError("Configured GitLab targets are managed in server configuration")
    return render_template("budget_registry.html", actor=actor, catalog=catalog, specs=SPECS,
                           kinds=_kinds(actor), kind=kind, selected=selected)


@budget_registry_bp.route("/review", methods=["POST"])
@_restricted
@rate_limited(max_per_minute=20, key_fn=lambda _: session.get("user_email", ""), scope="budget_review")
def review():
    store, actor, catalog = _context()
    kind = _kind(request.form.get("kind"), actor)
    if kind in ("budget_batch", "budget_group"):
        raise RegistryError("Use the dedicated review form")
    try:
        revision = int(request.form.get("revision", ""))
    except ValueError:
        raise RegistryError("A registry revision is required") from None
    if revision != catalog["revision"]:
        raise RegistryConflict("Registry changed")
    values = _values(kind, catalog)
    _validate_manager(kind, values)
    getattr(store, SPECS[kind][1])(actor, revision, **values, preview=True)
    ticket = _signer().dumps({"actor": actor.principal, "revision": revision, "kind": kind, "values": values})
    groups = None
    if kind == "budget_setup":
        account = next((row for row in catalog["execution_accounts"] if row["id"] == values["account_id"]), {})
        groups = [
            ("Budget", SPECS[kind][2][:8], _current(catalog, kind, values)),
            ("Execution settings", SPECS[kind][2][8:], {**account, "account_id": account.get("id", "")}),
        ]
    return render_template("budget_registry_review.html", ticket=ticket, kind=kind, specs=SPECS,
                           revision=revision, before=_current(catalog, kind, values), values=values,
                           impact=_impact(catalog, kind, values), catalog=catalog,
                           groups=groups,
                           back_url=url_for("budget_registry.index"))


def _return_url(kind, values):
    if kind == "budget_group":
        return url_for("budget_registry.group", edit=values["budget_id"])
    if kind == "budget_batch":
        return url_for("budget_registry.index")
    if kind in ("budget_setup", "budget_system"):
        return url_for("budget_registry.index", edit=values["budget_id"], destination=values["destination_id"])
    if kind in ("budgets", "budget_managers"):
        return url_for("budget_registry.index", edit=values.get("budget_id", values.get("id")))
    return url_for("budget_registry.index", section=kind)


def _validate_manager(kind, values):
    if kind != "budget_managers" or not values.get("assigned"):
        return
    try:
        exists = get_user_store().user_exists(values["principal"])
    except Exception:
        raise EncryptedDatabaseError("Identity service is unavailable") from None
    if not exists:
        raise RegistryError("Select an existing Portal account as budget manager")


@budget_registry_bp.route("/apply", methods=["POST"])
@_restricted
@rate_limited(max_per_minute=10, key_fn=lambda _: session.get("user_email", ""), scope="budget_apply")
def apply():
    store, actor, _catalog = _context()
    if request.form.get("confirm_shared_change") != "on":
        raise RegistryError("Shared change confirmation is required")
    if len(request.form.get("ticket", "")) > 16384:
        raise RegistryError("Invalid review")
    try:
        proposal = _signer().loads(request.form.get("ticket", ""), max_age=600)
    except BadSignature:
        raise RegistryError("Review expired or changed; review the change again") from None
    if proposal.get("actor") != actor.principal:
        raise RegistryPermissionError("Review belongs to another identity")
    kind = _kind(proposal.get("kind"), actor)
    _validate_manager(kind, proposal["values"])
    if kind == "budget_group":
        _group_targets(proposal["values"], _catalog)
    getattr(store, SPECS[kind][1])(actor, proposal["revision"], **proposal["values"])
    return redirect(_return_url(kind, proposal["values"]))
