"""Admin routes for user management and invitation handling."""

from functools import wraps

import logging

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

from utils.admin_policy import parse_affiliations
from utils.audit_logging import audit_event
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
