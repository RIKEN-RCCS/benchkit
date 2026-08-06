"""Admin routes for user management and invitation handling."""

from functools import wraps

from datetime import UTC, datetime
import json
import logging
import os
import sqlite3

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from utils.admin_policy import is_valid_email, parse_affiliations
from utils.audit_logging import audit_event
from utils.execution_profiles import (
    ExecutionProfileStore,
    load_execution_profiles,
    normalize_profile,
    normalize_trigger_definition,
)
from utils.gitlab_pipeline import (
    build_pipeline_plan,
    configured_gitlab_target,
    configured_gitlab_targets,
    configured_gitlab_trigger_token,
    submit_pipeline_plan,
)
from utils.rate_limit import rate_limited
from utils.user_store import get_user_store

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _add_no_store_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _render_users_page(invitation_url=None):
    store = get_user_store()
    all_users = store.list_users()
    for user in all_users:
        user["has_totp"] = store.has_totp_secret(user["email"])
    return render_template("admin_users.html", users=all_users, invitation_url=invitation_url)


def _admin_rate_key(_request):
    """Return the session-scoped admin rate-limit key."""
    return f"admin:{session.get('user_email', 'anon')}"


def _allowed_affiliations():
    """Return the configured affiliation allowlist, if one is enforced."""
    return current_app.config.get("ALLOWED_AFFILIATIONS")


def _parse_requested_affiliations():
    """Parse submitted affiliations and flash an error for invalid values."""
    affiliations_raw = request.form.get("affiliations", "").strip()
    affiliations, invalid = parse_affiliations(affiliations_raw, _allowed_affiliations())
    if invalid:
        audit_event(
            "admin_affiliation_rejected",
            actor=session.get("user_email"),
            result="failure",
            level=logging.WARNING,
            details={"invalid_affiliation_count": len(invalid)},
        )
        flash(f"Invalid affiliations: {', '.join(sorted(invalid))}.")
        return None
    return affiliations


def _split_form_list(value):
    """Parse a comma/newline separated form value into a list of strings."""
    items = []
    for chunk in value.replace("\n", ",").split(","):
        text = chunk.strip()
        if text:
            items.append(text)
    return items


def _parse_execution_profile_form():
    """Return a raw execution profile object from the submitted admin form."""
    errors = []
    metadata = {}
    code = _split_form_list(request.form.get("code", ""))
    system = _split_form_list(request.form.get("system", ""))
    allocation_project_id = request.form.get("allocation_project_id", "").strip()
    if allocation_project_id and len(system) != 1:
        errors.append("allocation_project_id requires exactly one system")
    if request.form.get("status", "").strip() == "approved" and not allocation_project_id:
        errors.append("approved profiles require allocation_project_id")

    actor = session.get("user_email", "")
    raw_profile = {
        "id": request.form.get("id", "").strip(),
        "display_name": request.form.get("id", "").strip(),
        "enabled": True,
        "status": request.form.get("status", "").strip(),
        "owner": "",
        "purpose": "",
        "activity": request.form.get("activity", "").strip(),
        "code": code,
        "system": system,
        "exp": _split_form_list(request.form.get("exp", "")),
        "allocation_project_id": allocation_project_id,
        "scheduler_extra_args": "",
        "visibility": "",
        "valid_from": request.form.get("valid_from", "").strip(),
        "valid_until": request.form.get("valid_until", "").strip(),
        "created_by": request.form.get("created_by", "").strip() or actor,
        "metadata_json": metadata,
    }
    return raw_profile, errors


def _parse_trigger_definition_form():
    """Return a raw trigger definition object from the submitted admin form."""
    actor = session.get("user_email", "")
    return {
        "id": request.form.get("id", "").strip(),
        "name": request.form.get("id", "").strip(),
        "trigger_type": request.form.get("trigger_type", "").strip(),
        "profile_id": request.form.get("profile_id", "").strip(),
        "enabled": request.form.get("enabled", "on") == "on",
        "gitlab_target": request.form.get("gitlab_target", "").strip(),
        "target_ref": "",
        "cron_expr": request.form.get("cron_expr", "").strip(),
        "timezone": request.form.get("timezone", "").strip(),
        "watch_kind": request.form.get("watch_kind", "").strip(),
        "watch_targets": _split_form_list(request.form.get("watch_targets", "")),
        "match_mode": request.form.get("match_mode", "").strip(),
        "created_by": actor,
    }


def _parse_bool_form(name):
    return request.form.get(name) == "on"


def _profile_scope_csv(profile, key):
    if not profile:
        return ""
    values = profile.get(key) or []
    return ",".join(str(value).strip() for value in values if str(value).strip())


def _default_trigger_ref():
    path = request.path or ""
    return "develop" if path.startswith(("/dev/", "/dev2/")) else "main"


def _portal_result_server_url():
    configured = os.environ.get("RESULT_SERVER_PUBLIC_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    path = request.path or ""
    prefix = path.split("/admin/", 1)[0] if "/admin/" in path else ""
    if prefix == "/admin":
        prefix = ""
    return f"{request.url_root.rstrip('/')}{prefix}"


def _profile_filter_options():
    return [
        ("all", "All"),
        ("approved", "Approved"),
        ("draft", "Draft"),
        ("paused", "Paused"),
        ("retired", "Retired"),
        ("inactive", "Inactive"),
        ("expired", "Expired"),
    ]


def _profile_is_expired(profile):
    valid_until = profile.get("valid_until", "")
    return bool(valid_until and valid_until < datetime.now(UTC).date().isoformat())


def _profile_matches_filter(profile, selected_filter):
    if selected_filter == "all":
        return True
    if selected_filter == "inactive":
        return (
            not profile.get("enabled", True)
            or profile.get("status") in {"paused", "retired"}
        )
    if selected_filter == "expired":
        return _profile_is_expired(profile)
    return profile.get("status") == selected_filter


def _list_trigger_definitions(db_path):
    try:
        return ExecutionProfileStore(db_path).list_trigger_definitions()
    except sqlite3.Error as exc:
        flash(f"Trigger definitions could not be loaded: {exc}")
        return []


def _find_trigger_definition(triggers, trigger_id):
    if not trigger_id:
        return None
    return next(
        (trigger for trigger in triggers if trigger.get("id") == trigger_id),
        None,
    )


def _build_execution_pipeline_plan(store):
    """Resolve the submitted target and build a GitLab pipeline plan."""
    target_ref = request.form.get("target_ref", "").strip() or _default_trigger_ref()
    profile_id = request.form.get("profile_id", "").strip()
    gitlab_target_id = request.form.get("gitlab_target", "").strip()
    code = request.form.get("code", "").strip()
    system = request.form.get("system", "").strip()
    exp = request.form.get("exp", "").strip()

    resolve_result = store.resolve_profile(
        profile_id=profile_id,
        code=code,
        system=system,
        exp=exp,
    )
    profile = resolve_result.profile
    effective_code = code or _profile_scope_csv(profile, "code")
    effective_system = system or _profile_scope_csv(profile, "system")
    effective_exp = exp or _profile_scope_csv(profile, "exp")
    gitlab_target, target_errors = configured_gitlab_target(gitlab_target_id)
    plan = build_pipeline_plan(
        gitlab_repo=gitlab_target.repo if gitlab_target else "",
        target_ref=target_ref,
        code=effective_code,
        system=effective_system,
        app="",
        benchpark=False,
        park_only=False,
        park_send=False,
        allocation_project_id=resolve_result.allocation_project_id,
        scheduler_extra_args="",
        result_server_url=_portal_result_server_url(),
        target_id=gitlab_target.id if gitlab_target else gitlab_target_id,
    )
    request_errors = []
    if not profile_id:
        request_errors.append("profile_id is required")
    if profile and not resolve_result.allocation_project_id:
        request_errors.append("profile allocation_project_id is required")
    if effective_exp:
        plan.warnings.append(
            "Profile Exp is used for Portal profile matching and is not sent to GitLab CI."
        )
    return {
        "target_ref": target_ref,
        "profile_id": profile_id,
        "gitlab_target": gitlab_target,
        "gitlab_target_id": gitlab_target.id if gitlab_target else gitlab_target_id,
        "code": effective_code,
        "system": effective_system,
        "exp": effective_exp,
        "profile": profile,
        "plan": plan,
        "errors": request_errors + target_errors + resolve_result.errors + plan.errors,
    }


def _user_affiliations(store, email):
    """Return the affiliations for a user, handling missing records uniformly."""
    if hasattr(store, "get_user"):
        user = store.get_user(email)
    else:
        user = next(
            (item for item in store.list_users() if item.get("email") == email),
            None,
        )
    if not user:
        return None
    return list(user.get("affiliations", []))


def _admin_user_count(store):
    """Return the number of stored users with the admin affiliation."""
    return sum(1 for user in store.list_users() if "admin" in user.get("affiliations", []))


def admin_required(f):
    """Allow access only to authenticated users with the admin affiliation."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return _add_no_store_headers(make_response(redirect(url_for("auth.login"))))
        affiliations = session.get("user_affiliations", [])
        if "admin" not in affiliations:
            abort(403)
        return _add_no_store_headers(make_response(f(*args, **kwargs)))

    return decorated


@admin_bp.route("/users", methods=["GET"])
@admin_required
def users():
    """Render the user administration page."""
    return _render_users_page()


@admin_bp.route("/execution-profiles", methods=["GET"])
@admin_required
def execution_profiles():
    """Render site-local execution profiles for admin review."""
    db_path = current_app.config.get("EXECUTION_PROFILE_DB_PATH")
    profile_result = load_execution_profiles(db_path)
    registered_profiles = profile_result.profiles
    trigger_definitions = _list_trigger_definitions(db_path)
    edit_profile_id = request.args.get("edit", "").strip()
    edit_trigger_id = request.args.get("edit_trigger", "").strip()
    edit_profile = None
    if edit_profile_id:
        edit_profile = next(
            (
                profile
                for profile in profile_result.profiles
                if profile.get("id") == edit_profile_id
            ),
            None,
        )
    edit_trigger = _find_trigger_definition(trigger_definitions, edit_trigger_id)
    return render_template(
        "admin_execution_profiles.html",
        profile_result=profile_result,
        registered_profiles=registered_profiles,
        trigger_definitions=trigger_definitions,
        profile_filter="all",
        profile_filter_options=_profile_filter_options(),
        today=datetime.now(UTC).date().isoformat(),
        edit_profile=edit_profile,
        edit_trigger=edit_trigger,
        default_target_ref=_default_trigger_ref(),
        dry_run_result=None,
        submit_result=None,
        gitlab_targets=configured_gitlab_targets()[0],
    )


@admin_bp.route("/execution-profiles/triggers/upsert", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def upsert_execution_profile_trigger():
    """Create or update a site-local trigger definition."""
    raw_trigger = _parse_trigger_definition_form()
    trigger, errors = normalize_trigger_definition(raw_trigger)

    if errors or trigger is None:
        audit_event(
            "admin_execution_profile_trigger_rejected",
            actor=session.get("user_email"),
            target=raw_trigger.get("id", "")[:128],
            result="failure",
            level=logging.WARNING,
            details={"errors": errors},
        )
        flash("Trigger definition was not saved: " + "; ".join(errors))
        return redirect(url_for("admin.execution_profiles"))

    try:
        store = ExecutionProfileStore(current_app.config.get("EXECUTION_PROFILE_DB_PATH"))
        store.upsert_trigger_definition(trigger, actor=session.get("user_email", ""))
    except sqlite3.Error as exc:
        audit_event(
            "admin_execution_profile_trigger_save_failed",
            actor=session.get("user_email"),
            target=trigger["id"],
            result="failure",
            level=logging.ERROR,
            details={"error": str(exc)},
        )
        flash(f"Trigger definition was not saved: {exc}")
        return redirect(url_for("admin.execution_profiles"))

    audit_event(
        "admin_execution_profile_trigger_saved",
        actor=session.get("user_email"),
        target=trigger["id"],
        result="success",
        details={
            "trigger_type": trigger["trigger_type"],
            "profile_id": trigger["profile_id"],
            "enabled": trigger["enabled"],
        },
    )
    flash(f"Trigger definition {trigger['id']} saved.")
    return redirect(url_for("admin.execution_profiles"))


@admin_bp.route("/execution-profiles/triggers/<trigger_id>/pause", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def pause_execution_profile_trigger(trigger_id):
    """Pause a site-local trigger definition."""
    store = ExecutionProfileStore(current_app.config.get("EXECUTION_PROFILE_DB_PATH"))
    if not store.set_trigger_definition_enabled(
        trigger_id,
        False,
        actor=session.get("user_email", ""),
    ):
        flash(f"Trigger definition {trigger_id} was not found.")
    else:
        audit_event(
            "admin_execution_profile_trigger_paused",
            actor=session.get("user_email"),
            target=trigger_id,
            result="success",
        )
        flash(f"Trigger definition {trigger_id} paused.")
    return redirect(url_for("admin.execution_profiles"))


@admin_bp.route("/execution-profiles/triggers/<trigger_id>/resume", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def resume_execution_profile_trigger(trigger_id):
    """Resume a site-local trigger definition."""
    store = ExecutionProfileStore(current_app.config.get("EXECUTION_PROFILE_DB_PATH"))
    if not store.set_trigger_definition_enabled(
        trigger_id,
        True,
        actor=session.get("user_email", ""),
    ):
        flash(f"Trigger definition {trigger_id} was not found.")
    else:
        audit_event(
            "admin_execution_profile_trigger_resumed",
            actor=session.get("user_email"),
            target=trigger_id,
            result="success",
        )
        flash(f"Trigger definition {trigger_id} resumed.")
    return redirect(url_for("admin.execution_profiles"))


@admin_bp.route("/execution-profiles/triggers/<trigger_id>/delete", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def delete_execution_profile_trigger(trigger_id):
    """Delete a site-local trigger definition."""
    store = ExecutionProfileStore(current_app.config.get("EXECUTION_PROFILE_DB_PATH"))
    if not store.delete_trigger_definition(trigger_id, actor=session.get("user_email", "")):
        flash(f"Trigger definition {trigger_id} was not found.")
    else:
        audit_event(
            "admin_execution_profile_trigger_deleted",
            actor=session.get("user_email"),
            target=trigger_id,
            result="success",
        )
        flash(f"Trigger definition {trigger_id} deleted.")
    return redirect(url_for("admin.execution_profiles"))


@admin_bp.route("/execution-profiles/upsert", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def upsert_execution_profile():
    """Create or update a site-local execution profile."""
    raw_profile, errors = _parse_execution_profile_form()
    profile = None
    if not errors:
        profile, errors = normalize_profile(raw_profile)

    if errors or profile is None:
        audit_event(
            "admin_execution_profile_rejected",
            actor=session.get("user_email"),
            target=raw_profile.get("id", "")[:128],
            result="failure",
            level=logging.WARNING,
            details={"errors": errors},
        )
        flash("Execution profile was not saved: " + "; ".join(errors))
        return redirect(url_for("admin.execution_profiles"))

    try:
        store = ExecutionProfileStore(current_app.config.get("EXECUTION_PROFILE_DB_PATH"))
        store.upsert_profile(profile, actor=session.get("user_email", ""))
    except sqlite3.Error as exc:
        audit_event(
            "admin_execution_profile_save_failed",
            actor=session.get("user_email"),
            target=profile["id"],
            result="failure",
            level=logging.ERROR,
            details={"error": str(exc)},
        )
        flash(f"Execution profile was not saved: {exc}")
        return redirect(url_for("admin.execution_profiles"))

    audit_event(
        "admin_execution_profile_saved",
        actor=session.get("user_email"),
        target=profile["id"],
        result="success",
        details={
            "enabled": profile["enabled"],
            "status": profile["status"],
            "code": profile["code"],
            "system": profile["system"],
            "exp": profile["exp"],
        },
    )
    flash(f"Execution profile {profile['id']} saved.")
    return redirect(url_for("admin.execution_profiles"))


@admin_bp.route("/execution-profiles/<profile_id>/delete", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def delete_execution_profile(profile_id):
    """Delete a site-local execution profile."""
    store = ExecutionProfileStore(current_app.config.get("EXECUTION_PROFILE_DB_PATH"))
    if not store.delete_profile(profile_id, actor=session.get("user_email", "")):
        flash(f"Execution profile {profile_id} was not found.")
    else:
        audit_event(
            "admin_execution_profile_deleted",
            actor=session.get("user_email"),
            target=profile_id,
            result="success",
        )
        flash(f"Execution profile {profile_id} deleted.")
    return redirect(url_for("admin.execution_profiles"))


@admin_bp.route("/execution-profiles/dry-run-submit", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def dry_run_execution_profile_submit():
    """Resolve an execution profile and render a GitLab trigger dry run."""
    db_path = current_app.config.get("EXECUTION_PROFILE_DB_PATH")
    store = ExecutionProfileStore(db_path)
    submit_plan = _build_execution_pipeline_plan(store)
    target_ref = submit_plan["target_ref"]
    profile_id = submit_plan["profile_id"]
    gitlab_target_id = submit_plan["gitlab_target_id"]
    code = submit_plan["code"]
    system = submit_plan["system"]
    exp = submit_plan["exp"]
    profile = submit_plan["profile"]
    plan = submit_plan["plan"]
    errors = submit_plan["errors"]
    status = "dry_run_ready" if not errors else "dry_run_blocked"
    request_id = store.create_execution_request(
        request_type="gitlab_pipeline",
        status=status,
        dry_run=True,
        profile_id=profile["id"] if profile else profile_id,
        target_ref=target_ref,
        code=code,
        system=system,
        exp=exp,
        payload={
            "api_url": plan.api_url,
            "gitlab_target": gitlab_target_id,
            "gitlab_project": submit_plan["gitlab_target"].repo
            if submit_plan["gitlab_target"]
            else "",
            "payload": plan.payload,
        },
        errors=errors,
        actor=session.get("user_email", ""),
    )

    audit_event(
        "admin_execution_profile_submit_dry_run",
        actor=session.get("user_email"),
        target=profile["id"] if profile else profile_id,
        result="success" if not errors else "failure",
        details={
            "request_id": request_id,
            "target_ref": target_ref,
            "gitlab_target": gitlab_target_id,
            "code": code,
            "system": system,
            "exp": exp,
            "errors": errors,
        },
    )

    profile_result = load_execution_profiles(db_path)
    return render_template(
        "admin_execution_profiles.html",
        profile_result=profile_result,
        registered_profiles=profile_result.profiles,
        trigger_definitions=_list_trigger_definitions(db_path),
        profile_filter="all",
        profile_filter_options=_profile_filter_options(),
        today=datetime.now(UTC).date().isoformat(),
        edit_profile=None,
        edit_trigger=None,
        default_target_ref=_default_trigger_ref(),
        dry_run_result={
            "request_id": request_id,
            "status": status,
            "profile": profile,
            "api_url": plan.api_url,
            "gitlab_target": gitlab_target_id,
            "gitlab_project": submit_plan["gitlab_target"].repo
            if submit_plan["gitlab_target"]
            else "",
            "payload_json": json.dumps(plan.payload, indent=2, sort_keys=True),
            "errors": errors,
            "warnings": plan.warnings,
        },
        submit_result=None,
        gitlab_targets=configured_gitlab_targets()[0],
    )


@admin_bp.route("/execution-profiles/submit", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=5, key_fn=_admin_rate_key, scope="admin_write")
def submit_execution_profile_pipeline():
    """Resolve an execution profile and submit a GitLab pipeline."""
    db_path = current_app.config.get("EXECUTION_PROFILE_DB_PATH")
    store = ExecutionProfileStore(db_path)
    submit_plan = _build_execution_pipeline_plan(store)
    target_ref = submit_plan["target_ref"]
    profile_id = submit_plan["profile_id"]
    gitlab_target = submit_plan["gitlab_target"]
    gitlab_target_id = submit_plan["gitlab_target_id"]
    code = submit_plan["code"]
    system = submit_plan["system"]
    exp = submit_plan["exp"]
    profile = submit_plan["profile"]
    plan = submit_plan["plan"]
    errors = list(submit_plan["errors"])
    submit_result = None

    if request.form.get("confirm_submit") != "on":
        errors.append("confirm_submit is required")

    if not errors:
        submit_result = submit_pipeline_plan(
            plan,
            token=configured_gitlab_trigger_token(gitlab_target),
        )
        errors.extend(submit_result.errors)

    if submit_result and submit_result.ok:
        status = "submitted"
    elif submit_result:
        status = "submit_failed"
    else:
        status = "submit_blocked"
    payload = {"api_url": plan.api_url, "payload": plan.payload}
    if gitlab_target_id:
        payload["gitlab_target"] = gitlab_target_id
    if gitlab_target:
        payload["gitlab_project"] = gitlab_target.repo
    if submit_result is not None:
        payload["submit"] = {
            "status_code": submit_result.status_code,
            "response": submit_result.response,
        }
    request_id = store.create_execution_request(
        request_type="gitlab_pipeline",
        status=status,
        dry_run=False,
        profile_id=profile["id"] if profile else profile_id,
        target_ref=target_ref,
        code=code,
        system=system,
        exp=exp,
        payload=payload,
        errors=errors,
        actor=session.get("user_email", ""),
    )

    audit_event(
        "admin_execution_profile_submit",
        actor=session.get("user_email"),
        target=profile["id"] if profile else profile_id,
        result="success" if status == "submitted" else "failure",
        details={
            "request_id": request_id,
            "target_ref": target_ref,
            "gitlab_target": gitlab_target_id,
            "code": code,
            "system": system,
            "exp": exp,
            "status": status,
            "http_status": submit_result.status_code if submit_result else 0,
            "errors": errors,
        },
    )

    profile_result = load_execution_profiles(db_path)
    return render_template(
        "admin_execution_profiles.html",
        profile_result=profile_result,
        registered_profiles=profile_result.profiles,
        trigger_definitions=_list_trigger_definitions(db_path),
        profile_filter="all",
        profile_filter_options=_profile_filter_options(),
        today=datetime.now(UTC).date().isoformat(),
        edit_profile=None,
        edit_trigger=None,
        default_target_ref=_default_trigger_ref(),
        dry_run_result=None,
        submit_result={
            "request_id": request_id,
            "status": status,
            "profile": profile,
            "api_url": plan.api_url,
            "gitlab_target": gitlab_target_id,
            "gitlab_project": gitlab_target.repo if gitlab_target else "",
            "payload_json": json.dumps(plan.payload, indent=2, sort_keys=True),
            "errors": errors,
            "warnings": plan.warnings,
            "response": submit_result.response if submit_result else {},
            "status_code": submit_result.status_code if submit_result else 0,
        },
        gitlab_targets=configured_gitlab_targets()[0],
    )


@admin_bp.route("/users/add", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def add_user():
    """Create a user invitation and show the generated invitation URL."""
    store = get_user_store()
    email = request.form.get("email", "").strip()
    affiliations = _parse_requested_affiliations()
    if affiliations is None:
        return redirect(url_for("admin.users"))

    if not email:
        flash("Email is required.")
        return redirect(url_for("admin.users"))
    if not is_valid_email(email):
        audit_event(
            "admin_user_invite_rejected",
            actor=session.get("user_email"),
            target=email[:64],
            result="failure",
            level=logging.WARNING,
            details={"reason": "invalid_email_format"},
        )
        flash("Invalid email address.")
        return redirect(url_for("admin.users"))

    if store.user_exists(email):
        flash(f"User {email} is already registered. Use 'Reinvite' to reset their TOTP.")
        return redirect(url_for("admin.users"))

    token = store.create_invitation(email, affiliations)
    invitation_url = url_for("auth.setup", token=token, _external=True)

    audit_event(
        "admin_user_invited",
        actor=session.get("user_email"),
        target=email,
        result="success",
        details={"affiliations": affiliations},
    )
    flash(f"Invitation created for {email}.")
    return _render_users_page(invitation_url)


@admin_bp.route("/users/<email>/delete", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def delete_user(email):
    """Delete a user unless the current admin targets their own account."""
    if email == session.get("user_email"):
        audit_event(
            "admin_user_delete_blocked",
            actor=session.get("user_email"),
            target=email,
            result="failure",
            level=logging.WARNING,
            details={"reason": "self_delete"},
        )
        flash("You cannot delete your own account.")
        return redirect(url_for("admin.users"))
    store = get_user_store()
    affiliations = _user_affiliations(store, email)
    if affiliations is None:
        flash(f"User {email} not found.")
        return redirect(url_for("admin.users"))
    if "admin" in affiliations and _admin_user_count(store) <= 1:
        audit_event(
            "admin_user_delete_blocked",
            actor=session.get("user_email"),
            target=email,
            result="failure",
            level=logging.WARNING,
            details={"reason": "only_admin"},
        )
        flash("You cannot delete the only admin user.")
        return redirect(url_for("admin.users"))
    store.delete_user(email)
    audit_event(
        "admin_user_deleted",
        actor=session.get("user_email"),
        target=email,
        result="success",
    )
    flash(f"User {email} has been deleted.")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<email>/affiliations", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def update_affiliations(email):
    """Update the affiliations stored for a user."""
    store = get_user_store()
    current_affiliations = _user_affiliations(store, email)
    if current_affiliations is None:
        flash(f"User {email} not found.")
        return redirect(url_for("admin.users"))
    affiliations = _parse_requested_affiliations()
    if affiliations is None:
        return redirect(url_for("admin.users"))
    if (
        "admin" in current_affiliations
        and "admin" not in affiliations
        and _admin_user_count(store) <= 1
    ):
        audit_event(
            "admin_affiliation_change_blocked",
            actor=session.get("user_email"),
            target=email,
            result="failure",
            level=logging.WARNING,
            details={"reason": "only_admin"},
        )
        flash("You cannot remove admin from the only admin user.")
        return redirect(url_for("admin.users"))
    store.update_affiliations(email, affiliations)
    audit_event(
        "admin_affiliation_changed",
        actor=session.get("user_email"),
        target=email,
        result="success",
        details={
            "old_affiliations": current_affiliations,
            "new_affiliations": affiliations,
        },
    )
    flash(f"Affiliations updated for {email}.")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<email>/reinvite", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def reinvite_user(email):
    """Generate a new invitation link after clearing the current TOTP secret."""
    store = get_user_store()

    if not store.user_exists(email):
        flash(f"User {email} not found.")
        return redirect(url_for("admin.users"))

    # Invalidate the current secret before issuing a new invitation.
    store.clear_totp_secret(email)
    affiliations = store.get_affiliations(email)
    token = store.create_invitation(email, affiliations)
    invitation_url = url_for("auth.setup", token=token, _external=True)

    audit_event(
        "admin_user_reinvited",
        actor=session.get("user_email"),
        target=email,
        result="success",
        details={"affiliations": affiliations},
    )
    flash(f"Reinvitation created for {email}.")
    return _render_users_page(invitation_url)
