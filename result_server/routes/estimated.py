from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, abort, current_app, make_response
)
from utils.result_records import load_result_json
from utils.results_loader import load_estimated_results_table, get_filter_options, ESTIMATED_FIELD_MAP
from routes.results import extract_query_params
from utils.user_store import get_user_store
from utils.result_file import load_result_file, check_file_permission
from utils.system_info import get_all_systems_info

estimated_bp = Blueprint("estimated", __name__)


def _render_estimated_auth_required():
    systems_info = get_all_systems_info()
    response = make_response(render_template(
        "estimated_results.html",
        rows=[], columns=[],
        authenticated=False, systems_info=systems_info,
        pagination={"page": 1, "per_page": 100, "total": 0, "total_pages": 1},
        filter_options={"systems": [], "codes": [], "exps": []},
        current_system=None, current_code=None,
        current_exp=None, current_per_page=100,
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


# GET /estimated/
@estimated_bp.route("/", methods=["GET"], strict_slashes=False)
def estimated_results():
    authenticated = session.get("authenticated", False)
    if not authenticated:
        return _render_estimated_auth_required()

    email = session.get("user_email")

    store = get_user_store()
    affs = store.get_affiliations(email) if email else []

    # クエリパラメータ取得
    params = extract_query_params()
    page = params["page"]
    per_page = params["per_page"]
    filter_system = params["filter_system"]
    filter_code = params["filter_code"]
    filter_exp = params["filter_exp"]

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

    filter_options = get_filter_options(
        estimated_dir,
        public_only=(not authenticated),
        authenticated=authenticated, affiliations=affs,
        field_map=ESTIMATED_FIELD_MAP,
    )
    systems_info = get_all_systems_info()
    response = make_response(render_template(
        "estimated_results.html",
        rows=rows, columns=columns,
        authenticated=authenticated, systems_info=systems_info,
        pagination=pagination_info, filter_options=filter_options,
        current_system=filter_system, current_code=filter_code,
        current_exp=filter_exp, current_per_page=per_page,
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


# GET /estimated/<filename>
@estimated_bp.route("/<filename>")
def show_estimated_result(filename):
    if not session.get("authenticated", False):
        abort(403, "Authentication required to view estimated data")
    estimated_dir = current_app.config["ESTIMATED_DIR"]
    check_file_permission(filename, estimated_dir)
    return load_result_file(filename, estimated_dir)


@estimated_bp.route("/detail/<filename>")
def estimated_detail(filename):
    if not session.get("authenticated", False):
        abort(403, "Authentication required to view estimated data")
    estimated_dir = current_app.config["ESTIMATED_DIR"]
    check_file_permission(filename, estimated_dir)
    result = load_result_json(filename, estimated_dir)
    if result is None:
        abort(404, "Estimated result file not found")
    return render_template("estimated_detail.html", result=result, filename=filename)
