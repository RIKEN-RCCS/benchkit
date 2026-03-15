import os
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort, current_app
)
from utils.results_loader import load_estimated_results_table
from utils.otp_redis_manager import send_otp, verify_otp, invalidate_otp, is_allowed, get_affiliations
from utils.result_file import load_result_file, get_file_confidential_tags
from utils.system_info import get_all_systems_info

estimated_bp = Blueprint("estimated", __name__)


def _check_file_permission(filename, session_key_authenticated, session_key_email, dir_path):
    tags = get_file_confidential_tags(filename, dir_path)
    if not tags:
        return
    authenticated = session.get(session_key_authenticated, False)
    email = session.get(session_key_email)
    affs = get_affiliations(email) if email else []
    if not authenticated or not (set(tags) & set(affs)):
        abort(403, "You do not have permission to access this file")


def _handle_otp_post(session_key_authenticated, session_key_email, route_name):
    email = request.form.get("email")
    otp = request.form.get("otp")

    if email and not otp:
        success, msg = send_otp(email)
        flash(msg)
        if success and is_allowed(email):
            session.clear()
            session[session_key_email] = email
            session["otp_stage"] = "otp"
        else:
            session.clear()
            session["otp_stage"] = "email"
        return redirect(url_for(route_name))

    elif otp:
        otp_email = session.get(session_key_email)
        if otp_email and verify_otp(otp_email, otp):
            session.clear()
            session[session_key_authenticated] = True
            flash("Authentication successful")
        else:
            session.clear()
            flash("Authentication failed")
        return redirect(url_for(route_name))


# GET/POST /estimated_results/
@estimated_bp.route("/", methods=["GET", "POST"], strict_slashes=False)
def estimated_results():
    if request.method == "POST":
        return _handle_otp_post("authenticated_estimated", "otp_email_estimated", "estimated.estimated_results")

    authenticated = session.get("authenticated_estimated", False)
    otp_email = session.get("otp_email_estimated")

    if authenticated:
        otp_stage = None
    elif otp_email:
        otp_stage = "otp"
    else:
        otp_stage = "email"

    rows, columns = load_estimated_results_table(
        current_app.config["ESTIMATED_DIR"],
        public_only=False,
        session_email=otp_email,
        authenticated=authenticated
    )
    systems_info = get_all_systems_info()
    return render_template(
        "estimated_results.html",
        rows=rows, columns=columns,
        authenticated=authenticated,
        otp_stage=otp_stage,
        systems_info=systems_info
    )


# GET /estimated_results/<filename>
@estimated_bp.route("/<filename>")
def show_estimated_result(filename):
    estimated_dir = current_app.config["ESTIMATED_DIR"]
    _check_file_permission(filename, "authenticated_estimated", "otp_email_estimated", estimated_dir)
    return load_result_file(filename, estimated_dir)
