import os
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort, current_app
)
from utils.results_loader import load_estimated_results_table
from utils.user_store import get_user_store
from utils.result_file import load_result_file, get_file_confidential_tags
from utils.system_info import get_all_systems_info

estimated_bp = Blueprint("estimated", __name__)


def _check_file_permission(filename, dir_path):
    tags = get_file_confidential_tags(filename, dir_path)
    if not tags:
        return
    authenticated = session.get("authenticated", False)
    email = session.get("user_email")
    store = get_user_store()
    affs = store.get_affiliations(email) if email else []
    if not authenticated or not (set(tags) & set(affs)):
        abort(403, "You do not have permission to access this file")


# GET /estimated/
@estimated_bp.route("/", methods=["GET"], strict_slashes=False)
def estimated_results():
    authenticated = session.get("authenticated", False)
    email = session.get("user_email")

    store = get_user_store()
    affs = store.get_affiliations(email) if email else []

    rows, columns = load_estimated_results_table(
        current_app.config["ESTIMATED_DIR"],
        public_only=False,
        session_email=email,
        authenticated=authenticated,
        affiliations=affs
    )
    systems_info = get_all_systems_info()
    return render_template(
        "estimated_results.html",
        rows=rows, columns=columns,
        authenticated=authenticated,
        systems_info=systems_info
    )


# GET /estimated/<filename>
@estimated_bp.route("/<filename>")
def show_estimated_result(filename):
    estimated_dir = current_app.config["ESTIMATED_DIR"]
    _check_file_permission(filename, estimated_dir)
    return load_result_file(filename, estimated_dir)
