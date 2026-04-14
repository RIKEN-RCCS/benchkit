"""Admin routes for user management and invitation handling."""

from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from utils.user_store import get_user_store

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _add_no_store_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _get_users_with_totp_status():
    """Return the user list with an additional has_totp flag per user."""
    store = get_user_store()
    users = store.list_users()
    for user in users:
        user["has_totp"] = store.has_totp_secret(user["email"])
    return store, users


def _render_users_page(invitation_url=None):
    _, all_users = _get_users_with_totp_status()
    return render_template("admin_users.html", users=all_users, invitation_url=invitation_url)


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
def add_user():
    """Create a user invitation and show the generated invitation URL."""
    store = get_user_store()
    email = request.form.get("email", "").strip()
    affiliations_raw = request.form.get("affiliations", "").strip()
    affiliations = [item.strip() for item in affiliations_raw.split(",") if item.strip()]

    if not email:
        flash("Email is required.")
        return redirect(url_for("admin.users"))

    if store.user_exists(email):
        flash(f"User {email} is already registered. Use 'Reinvite' to reset their TOTP.")
        return redirect(url_for("admin.users"))

    token = store.create_invitation(email, affiliations)
    invitation_url = url_for("auth.setup", token=token, _external=True)

    flash(f"Invitation created for {email}.")
    return _render_users_page(invitation_url)


@admin_bp.route("/users/<path:email>/delete", methods=["POST"])
@admin_required
def delete_user(email):
    """Delete a user unless the current admin targets their own account."""
    if email == session.get("user_email"):
        flash("You cannot delete your own account.")
        return redirect(url_for("admin.users"))
    store = get_user_store()
    store.delete_user(email)
    flash(f"User {email} has been deleted.")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<path:email>/affiliations", methods=["POST"])
@admin_required
def update_affiliations(email):
    """Update the affiliations stored for a user."""
    store = get_user_store()
    affiliations_raw = request.form.get("affiliations", "").strip()
    affiliations = [item.strip() for item in affiliations_raw.split(",") if item.strip()]
    store.update_affiliations(email, affiliations)
    flash(f"Affiliations updated for {email}.")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<path:email>/reinvite", methods=["POST"])
@admin_required
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

    flash(f"Reinvitation created for {email}.")
    return _render_users_page(invitation_url)
