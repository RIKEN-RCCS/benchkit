from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from routes.admin import admin_required
from utils.app_support_matrix import load_app_system_support_matrix
from utils.node_hours import aggregate_node_hours, get_fiscal_year
from utils.result_detail_view import build_result_detail_context
from utils.result_file import check_file_permission, load_result_file
from utils.result_quality_rollup import build_result_quality_rollup
from utils.result_records import load_result_json, load_result_json_batch, summarize_result_quality
from utils.results_loader import DEFAULT_PER_PAGE, get_filter_options, load_results_table
from utils.site_diagnostics import build_site_diagnostics
from utils.system_info import get_all_systems_info
from utils.table_page_utils import build_filtered_redirect_args, render_no_store_template
from utils.table_query_params import parse_table_query_params
from utils.user_store import get_user_store
from utils.usage_query_params import parse_usage_query_params, select_usage_periods

results_bp = Blueprint("results", __name__)


def _render_confidential_auth_required():
    systems_info = get_all_systems_info()
    return render_no_store_template(
        "results_confidential.html",
        rows=[],
        columns=[],
        systems_info=systems_info,
        pagination={"page": 1, "per_page": DEFAULT_PER_PAGE, "total": 0, "total_pages": 1},
        filter_options={"systems": [], "codes": [], "exps": []},
        current_system=None,
        current_code=None,
        current_exp=None,
        current_per_page=DEFAULT_PER_PAGE,
        authenticated=False,
    )


def serve_confidential_file(filename, dir_path):
    check_file_permission(filename, dir_path)
    return load_result_file(filename, dir_path)


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
        authenticated = session.get("authenticated", False)
        if not authenticated:
            return _render_confidential_auth_required()
        email = session.get("user_email")
        store = get_user_store()
        affiliations = store.get_affiliations(email) if email else []
        load_kwargs.update(session_email=email, authenticated=authenticated, affiliations=affiliations)
        filter_kwargs.update(authenticated=authenticated, affiliations=affiliations)
        template_extra["authenticated"] = authenticated

    rows, columns, pagination_info = load_results_table(received_dir, **load_kwargs)

    if page != pagination_info["page"]:
        redirect_args = build_filtered_redirect_args(
            pagination_info["page"],
            per_page,
            filter_system,
            filter_code,
            filter_exp,
        )
        return redirect(url_for(redirect_endpoint, **redirect_args))

    filter_options = get_filter_options(received_dir, filter_code=filter_code, **filter_kwargs)
    systems_info = get_all_systems_info()
    render_context = dict(
        rows=rows,
        columns=columns,
        systems_info=systems_info,
        pagination=pagination_info,
        filter_options=filter_options,
        current_system=filter_system,
        current_code=filter_code,
        current_exp=filter_exp,
        current_per_page=per_page,
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

    for filename in filenames:
        check_file_permission(filename, current_app.config["RECEIVED_DIR"])

    results = load_result_json_batch(filenames, current_app.config["RECEIVED_DIR"])

    mixed = False
    if results:
        first_system = results[0]["data"].get("system")
        first_code = results[0]["data"].get("code")
        for row in results[1:]:
            if row["data"].get("system") != first_system or row["data"].get("code") != first_code:
                mixed = True
                break

    return render_template("result_compare.html", results=results, mixed=mixed)


@results_bp.route("/detail/<filename>")
def result_detail(filename):
    check_file_permission(filename, current_app.config["RECEIVED_DIR"])
    result = load_result_json(filename, current_app.config["RECEIVED_DIR"])
    if result is None:
        abort(404, "Result file not found")
    quality = summarize_result_quality(result)
    detail_context = build_result_detail_context(result, quality, filename)
    return render_template("result_detail.html", result=result, quality=quality, **detail_context)


@results_bp.route("/usage", methods=["GET"])
@admin_required
def usage_report():
    current_fy = get_fiscal_year(datetime.now())
    params = parse_usage_query_params(request.args, current_fy)
    period_type = params["period_type"]
    fiscal_year = params["fiscal_year"]
    period_filter = params["period_filter"]

    result = aggregate_node_hours(current_app.config["RECEIVED_DIR"], fiscal_year, period_type)
    period_filter, filtered_periods = select_usage_periods(result["periods"], period_filter)

    systems_info = get_all_systems_info()
    coverage_systems, app_support_rows = load_app_system_support_matrix()
    coverage_headers = [
        {"system": system, "name": systems_info.get(system, {}).get("name", system)}
        for system in coverage_systems
    ]
    site_diagnostics = build_site_diagnostics()
    result_quality_rollup = build_result_quality_rollup(current_app.config["RECEIVED_DIR"])

    return render_template(
        "usage_report.html",
        result=result,
        period_type=period_type,
        fiscal_year=fiscal_year,
        period_filter=period_filter,
        filtered_periods=filtered_periods,
        coverage_systems=coverage_headers,
        app_support_rows=app_support_rows,
        site_diagnostics=site_diagnostics,
        result_quality_rollup=result_quality_rollup,
    )


@results_bp.route("/<filename>")
def show_result(filename):
    if filename.endswith(".tgz"):
        check_file_permission(filename, current_app.config["RECEIVED_DIR"])
        return load_result_file(filename, current_app.config["RECEIVED_PADATA_DIR"])
    return serve_confidential_file(filename, current_app.config["RECEIVED_DIR"])
