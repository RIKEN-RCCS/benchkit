"""Authentication routes for login, TOTP setup, and logout."""

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from utils.totp_manager import (
    check_code_reuse,
    check_rate_limit,
    clear_failed_attempts,
    generate_qr_base64,
    generate_secret,
    record_failed_attempt,
    verify_code,
)
from utils.user_store import get_user_store

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _render_login_totp_step(email):
    return render_template("auth_login.html", step="totp", email=email)


def _render_setup_page(email, token, secret):
    issuer = current_app.config.get("TOTP_ISSUER", "CX Portal")
    qr_data = generate_qr_base64(secret, email, issuer=issuer)
    return render_template(
        "auth_setup.html",
        error=False,
        qr_data=qr_data,
        secret=secret,
        email=email,
        token=token,
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render the login flow and validate submitted TOTP codes."""
    if request.method == "GET":
        return render_template("auth_login.html", step="email")

    email = request.form.get("email", "").strip()
    totp_code = request.form.get("totp_code", "").strip()

    # Step 1: email submitted -> show the TOTP entry form.
    if email and not totp_code:
        # Keep the response uniform regardless of whether the user exists.
        session["_login_email"] = email
        return _render_login_totp_step(email)

    # Step 2: validate the submitted TOTP code.
    if totp_code:
        email = email or session.pop("_login_email", "")
        if not email:
            return redirect(url_for("auth.login"))

        # Enforce rate limiting when Redis-backed tracking is available.
        redis_conn = current_app.config.get("REDIS_CONN")
        prefix = current_app.config.get("REDIS_PREFIX", "")
        if redis_conn:
            is_locked, remaining = check_rate_limit(redis_conn, prefix, email)
            if is_locked:
                flash(f"Too many failed attempts. Please try again in {remaining} seconds.")
                return _render_login_totp_step(email)

        store = get_user_store()
        user = store.get_user(email)

        if user and user["totp_secret"] and verify_code(user["totp_secret"], totp_code):
            # Reject already-consumed codes to prevent replay attacks.
            if redis_conn and check_code_reuse(redis_conn, prefix, email, totp_code):
                flash("This code has already been used. Please wait for a new code.")
                return _render_login_totp_step(email)

            # Successful authentication.
            if redis_conn:
                clear_failed_attempts(redis_conn, prefix, email)
            session.clear()
            session["authenticated"] = True
            session["user_email"] = email
            session["user_affiliations"] = user["affiliations"]
            flash("Authentication successful.")
            return redirect(url_for("results.results"))

        # Failed authentication: record or report the attempt.
        if redis_conn:
            attempts = record_failed_attempt(redis_conn, prefix, email)
            from utils.totp_manager import MAX_LOGIN_ATTEMPTS

            remaining_attempts = MAX_LOGIN_ATTEMPTS - attempts
            if remaining_attempts > 0:
                flash(f"Authentication failed. {remaining_attempts} attempts remaining.")
            else:
                flash("Too many failed attempts. Your account is temporarily locked.")
                return _render_login_totp_step(email)
        else:
            flash("Authentication failed. Please check your code.")
        return _render_login_totp_step(email)

    return redirect(url_for("auth.login"))


@auth_bp.route("/setup/<token>", methods=["GET", "POST"])
def setup(token):
    """Render invitation-based TOTP setup and persist verified secrets."""
    store = get_user_store()
    invitation = store.get_invitation(token)

    if not invitation:
        flash("This invitation link is invalid or has expired.")
        return render_template("auth_setup.html", error=True)

    email = invitation["email"]
    affiliations = invitation["affiliations"]

    if request.method == "GET":
        secret = generate_secret()
        session["_setup_secret"] = secret
        return _render_setup_page(email, token, secret)

    # POST: validate the confirmation TOTP code.
    totp_code = request.form.get("totp_code", "").strip()
    secret = session.get("_setup_secret", "")

    if not secret:
        flash("Session expired. Please use the invitation link again.")
        return redirect(url_for("auth.setup", token=token))

    if verify_code(secret, totp_code):
        store.create_user(email, secret, affiliations)
        store.delete_invitation(token)
        session.pop("_setup_secret", None)
        flash("TOTP registration complete. You can now log in.")
        return redirect(url_for("auth.login"))

    flash("Invalid code. Please try again.")
    return _render_setup_page(email, token, secret)


@auth_bp.route("/logout")
def logout():
    """Clear the session and return to the public results page."""
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("results.results"))
