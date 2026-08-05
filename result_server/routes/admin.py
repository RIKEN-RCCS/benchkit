"""Admin routes for user management and invitation handling."""

from functools import wraps

import json
import logging
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
)
from utils.gitlab_pipeline import (
    build_pipeline_plan,
    configured_gitlab_repo,
    configured_gitlab_token,
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
    metadata_raw = request.form.get("metadata_json", "").strip()
    metadata = {}
    if metadata_raw:
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError as exc:
            errors.append(f"metadata_json must be valid JSON: {exc.msg}")
        else:
            if not isinstance(metadata, dict):
                errors.append("metadata_json must be a JSON object")
                metadata = {}

    actor = session.get("user_email", "")
    raw_profile = {
        "id": request.form.get("id", "").strip(),
        "display_name": request.form.get("display_name", "").strip(),
        "enabled": request.form.get("enabled") == "on",
        "status": request.form.get("status", "").strip(),
        "owner": request.form.get("owner", "").strip(),
        "purpose": request.form.get("purpose", "").strip(),
        "activity": request.form.get("activity", "").strip(),
        "code": _split_form_list(request.form.get("code", "")),
        "system": _split_form_list(request.form.get("system", "")),
        "exp": _split_form_list(request.form.get("exp", "")),
        "scheduler_extra_args": request.form.get("scheduler_extra_args", "").strip(),
        "visibility": request.form.get("visibility", "").strip(),
        "valid_from": request.form.get("valid_from", "").strip(),
        "valid_until": request.form.get("valid_until", "").strip(),
        "created_by": request.form.get("created_by", "").strip() or actor,
        "approved_by": request.form.get("approved_by", "").strip(),
        "approved_at": request.form.get("approved_at", "").strip(),
        "metadata_json": metadata,
    }
    return raw_profile, errors


def _parse_bool_form(name):
    return request.form.get(name) == "on"


def _build_execution_pipeline_plan(store):
    """Resolve the submitted target and build a GitLab pipeline plan."""
    target_ref = request.form.get("target_ref", "").strip() or "develop"
    profile_id = request.form.get("profile_id", "").strip()
    code = request.form.get("code", "").strip()
    system = request.form.get("system", "").strip()
    exp = request.form.get("exp", "").strip()
    app = request.form.get("app", "").strip()
    benchpark = _parse_bool_form("benchpark")
    park_only = _parse_bool_form("park_only")
    park_send = _parse_bool_form("park_send")

    resolve_result = store.resolve_profile(
        profile_id=profile_id,
        code=code,
        system=system,
        exp=exp,
    )
    profile = resolve_result.profile
    plan = build_pipeline_plan(
        gitlab_repo=configured_gitlab_repo(),
        target_ref=target_ref,
        code=code,
        system=system,
        app=app,
        benchpark=benchpark,
        park_only=park_only,
        park_send=park_send,
        scheduler_extra_args=resolve_result.scheduler_extra_args,
    )
    return {
        "target_ref": target_ref,
        "profile_id": profile_id,
        "code": code,
        "system": system,
        "exp": exp,
        "profile": profile,
        "plan": plan,
        "errors": resolve_result.errors + plan.errors,
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
    profile_result = load_execution_profiles(
        current_app.config.get("EXECUTION_PROFILE_DB_PATH")
    )
    return render_template(
        "admin_execution_profiles.html",
        profile_result=profile_result,
        dry_run_result=None,
    )


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


@admin_bp.route("/execution-profiles/dry-run-submit", methods=["POST"])
@admin_required
@rate_limited(max_per_minute=20, key_fn=_admin_rate_key, scope="admin_write")
def dry_run_execution_profile_submit():
    """Resolve an execution profile and render a GitLab Pipeline API dry run."""
    db_path = current_app.config.get("EXECUTION_PROFILE_DB_PATH")
    store = ExecutionProfileStore(db_path)
    submit_plan = _build_execution_pipeline_plan(store)
    target_ref = submit_plan["target_ref"]
    profile_id = submit_plan["profile_id"]
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
        payload={"api_url": plan.api_url, "payload": plan.payload},
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
        dry_run_result={
            "request_id": request_id,
            "status": status,
            "profile": profile,
            "api_url": plan.api_url,
            "payload_json": json.dumps(plan.payload, indent=2, sort_keys=True),
            "errors": errors,
            "warnings": plan.warnings,
        },
        submit_result=None,
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
            token=configured_gitlab_token(),
        )
        errors.extend(submit_result.errors)

    if submit_result and submit_result.ok:
        status = "submitted"
    elif submit_result:
        status = "submit_failed"
    else:
        status = "submit_blocked"
    payload = {"api_url": plan.api_url, "payload": plan.payload}
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
        dry_run_result=None,
        submit_result={
            "request_id": request_id,
            "status": status,
            "profile": profile,
            "api_url": plan.api_url,
            "payload_json": json.dumps(plan.payload, indent=2, sort_keys=True),
            "errors": errors,
            "warnings": plan.warnings,
            "response": submit_result.response if submit_result else {},
            "status_code": submit_result.status_code if submit_result else 0,
        },
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
