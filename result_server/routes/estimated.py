import os
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort, current_app
)
from utils.results_loader import load_estimated_results_table, get_estimated_filter_options
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

    # クエリパラメータ取得
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)
    filter_system = request.args.get("system", None)
    filter_code = request.args.get("code", None)
    filter_exp = request.args.get("exp", None)

    # per_page バリデーション
    if per_page not in (50, 100, 200):
        per_page = 100

    estimated_dir = current_app.config["ESTIMATED_DIR"]

    rows, columns, pagination_info = load_estimated_results_table(
        estimated_dir,
        public_only=(not authenticated),
        session_email=email,
        authenticated=authenticated,
        affiliations=affs,
        page=page, per_page=per_page,
        filter_system=filter_system, filter_code=filter_code, filter_exp=filter_exp,
    )

    # ページ範囲外の場合はリダイレクト
    if page != pagination_info["page"]:
        redirect_args = {"page": pagination_info["page"], "per_page": per_page}
        if filter_system is not None:
            redirect_args["system"] = filter_system
        if filter_code is not None:
            redirect_args["code"] = filter_code
        if filter_exp is not None:
            redirect_args["exp"] = filter_exp
        return redirect(url_for("estimated.estimated_results", **redirect_args))

    filter_options = get_estimated_filter_options(
        estimated_dir,
        public_only=(not authenticated),
        authenticated=authenticated, affiliations=affs,
    )
    systems_info = get_all_systems_info()
    return render_template(
        "estimated_results.html",
        rows=rows, columns=columns,
        authenticated=authenticated, systems_info=systems_info,
        pagination=pagination_info, filter_options=filter_options,
        current_system=filter_system, current_code=filter_code,
        current_exp=filter_exp, current_per_page=per_page,
    )


# GET /estimated/<filename>
@estimated_bp.route("/<filename>")
def show_estimated_result(filename):
    estimated_dir = current_app.config["ESTIMATED_DIR"]
    _check_file_permission(filename, estimated_dir)
    return load_result_file(filename, estimated_dir)
