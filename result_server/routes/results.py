from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
)

from routes.admin import admin_required
from utils.node_hours import get_fiscal_year
from utils.result_compare_view import load_result_compare_context
from utils.result_detail_view import build_result_detail_context
from utils.result_file import (
    load_permitted_result_json,
    serve_permitted_result_file,
)
from utils.result_records import summarize_result_quality
from utils.results_loader import DEFAULT_PER_PAGE, get_filter_options, load_results_table
from utils.session_user_context import get_session_user_context
from utils.system_info import get_all_systems_info
from utils.table_page_utils import (
    build_table_page_context,
    build_table_page_redirect,
    render_no_store_template,
)
from utils.table_query_params import parse_table_query_params
from utils.usage_report_view import build_usage_report_context

results_bp = Blueprint("results", __name__)


def _render_confidential_auth_required():
    systems_info = get_all_systems_info()
    auth_required_context = build_table_page_context(
        rows=[],
        columns=[],
        pagination={"page": 1, "per_page": DEFAULT_PER_PAGE, "total": 0, "total_pages": 1},
        filter_options={"systems": [], "codes": [], "exps": []},
        current_system=None,
        current_code=None,
        current_exp=None,
        current_per_page=DEFAULT_PER_PAGE,
        systems_info=systems_info,
        authenticated=False,
    )
    return render_no_store_template("results_confidential.html", **auth_required_context)


def serve_confidential_file(filename, dir_path):
    return serve_permitted_result_file(filename, dir_path)


def _render_results_list(public_only, template_name, redirect_endpoint):
    params = parse_table_query_params(request.args)
    page = params["page"]
    per_page = params["per_page"]
    filter_system = params["filter_system"]
    filter_code = params["filter_code"]
    filter_exp = params["filter_exp"]

    received_dir = current_app.config["RECEIVED_DIR"]
    received_padata_dir = current_app.config.get("RECEIVED_PADATA_DIR", received_dir)

    load_kwargs = dict(
        public_only=public_only,
        page=page,
        per_page=per_page,
        filter_system=filter_system,
        filter_code=filter_code,
        filter_exp=filter_exp,
        padata_directory=received_padata_dir,
    )
    filter_kwargs = dict(public_only=public_only)
    template_extra = {}

    if not public_only:
        user_context = get_session_user_context()
        if not user_context["authenticated"]:
            return _render_confidential_auth_required()
        load_kwargs.update(
            session_email=user_context["email"],
            authenticated=user_context["authenticated"],
            affiliations=user_context["affiliations"],
        )
        filter_kwargs.update(
            authenticated=user_context["authenticated"],
            affiliations=user_context["affiliations"],
        )
        template_extra["authenticated"] = user_context["authenticated"]

    rows, columns, pagination_info = load_results_table(received_dir, **load_kwargs)

    if page != pagination_info["page"]:
        return build_table_page_redirect(
            redirect_endpoint,
            pagination_info["page"],
            per_page,
            filter_system,
            filter_code,
            filter_exp,
        )

    filter_options = get_filter_options(received_dir, filter_code=filter_code, **filter_kwargs)
    render_context = build_table_page_context(
        rows=rows,
        columns=columns,
        pagination=pagination_info,
        filter_options=filter_options,
        current_system=filter_system,
        current_code=filter_code,
        current_exp=filter_exp,
        current_per_page=per_page,
        systems_info=get_all_systems_info(),
        **template_extra,
    )
    if not public_only:
        return render_no_store_template(template_name, **render_context)
    return render_template(template_name, **render_context)


@results_bp.route("/", strict_slashes=False)
def results():
    return _render_results_list(
        public_only=True,
        template_name="results.html",
        redirect_endpoint="results.results",
    )


@results_bp.route("/confidential", methods=["GET"], strict_slashes=False)
def results_confidential():
    return _render_results_list(
        public_only=False,
        template_name="results_confidential.html",
        redirect_endpoint="results.results_confidential",
    )


@results_bp.route("/compare", methods=["GET"])
def result_compare():
    files_param = request.args.get("files", "")
    filenames = [name.strip() for name in files_param.split(",") if name.strip()]

    if len(filenames) < 2:
        abort(400, "Select 2 or more results to compare")

    compare_context = load_result_compare_context(filenames, current_app.config["RECEIVED_DIR"])
    return render_template("result_compare.html", **compare_context)


@results_bp.route("/detail/<filename>")
def result_detail(filename):
    result = load_permitted_result_json(
        filename,
        current_app.config["RECEIVED_DIR"],
        not_found_message="Result file not found",
    )
    quality = summarize_result_quality(result)
    detail_context = build_result_detail_context(result, quality, filename)
    return render_template("result_detail.html", result=result, quality=quality, **detail_context)


@results_bp.route("/usage", methods=["GET"])
@admin_required
def usage_report():
    usage_context = build_usage_report_context(
        current_app.config["RECEIVED_DIR"],
        request.args,
        get_fiscal_year(datetime.now()),
    )
    return render_template("usage_report.html", **usage_context)


@results_bp.route("/<filename>")
def show_result(filename):
    if filename.endswith(".tgz"):
        return serve_permitted_result_file(
            filename,
            current_app.config["RECEIVED_DIR"],
            current_app.config["RECEIVED_PADATA_DIR"],
        )
    return serve_confidential_file(filename, current_app.config["RECEIVED_DIR"])
