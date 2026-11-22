from flask import abort, current_app, make_response, render_template, request, url_for

from utils.session_user_context import get_session_user_context
from utils.system_info import get_all_systems_info
from utils.table_pagination import ALLOWED_PER_PAGE, DEFAULT_PER_PAGE
from utils.result_file import require_authenticated_session
from utils.estimate_version_list import build_version_check_list
from utils.table_page_utils import (
    build_table_page_context_from_params,
    render_auth_required_table_page,
    render_table_page_response,
)
from utils.table_query_params import parse_table_query_params
from utils.estimated_list_page import load_estimated_page
from utils.result_catalog import CatalogUnavailable
from utils.encrypted_sqlite import EncryptedDatabaseError


ESTIMATION_LINKS = {
    "perftools": "https://github.com/masaaki-kondo/PerfTools",
}


def register_estimated_list_routes(estimated_bp):
    @estimated_bp.route("/version-checks", methods=["GET"])
    def version_checks():
        if current_app.config.get("PUBLIC_PORTAL_MODE"):
            abort(404)
        require_authenticated_session("Authentication required to view version checks")
        status = request.args.get("status", "different")
        if status not in ("different", "unknown", "same", "all"):
            abort(400, "Invalid version check status")
        try:
            page = int(request.args.get("page", "1"))
            per_page = int(request.args.get("per_page", "50"))
        except ValueError:
            abort(400, "Invalid pagination")
        if page < 1 or per_page not in ALLOWED_PER_PAGE:
            abort(400, "Invalid pagination")
        code = request.args.get("code", "")
        context = build_version_check_list(current_app.config.get("ESTIMATED_DIR"),
                                           current_app.config, status=status, code=code,
                                           page=page, per_page=per_page)
        def page_url(number):
            return url_for("estimated.version_checks", status=status, code=code,
                           page=number, per_page=per_page)
        context["previous_url"] = page_url(context["pagination"]["page"] - 1)
        context["next_url"] = page_url(context["pagination"]["page"] + 1)
        response = make_response(render_template("estimate_version_checks.html", **context))
        response.headers["Cache-Control"] = "no-store"
        return response

    @estimated_bp.route("/", methods=["GET"], strict_slashes=False)
    def estimated_results():
        user_context = get_session_user_context()
        if not user_context["authenticated"]:
            return render_auth_required_table_page(
                "estimated_results.html",
                per_page=DEFAULT_PER_PAGE,
                authenticated=False,
                systems_info=get_all_systems_info(),
                estimation_links=ESTIMATION_LINKS,
            )

        params = parse_table_query_params(request.args)
        estimated_dir = current_app.config["ESTIMATED_DIR"]
        try:
            rows, columns, pagination_info, filter_options = load_estimated_page(
                estimated_dir, affiliations=user_context["affiliations"],
                page=params["page"], per_page=params["per_page"],
                filter_system=params["filter_system"], filter_code=params["filter_code"],
                filter_exp=params["filter_exp"],
            )
        except (CatalogUnavailable, EncryptedDatabaseError):
            abort(503, description='Estimate list unavailable; index verification may be required')
        page_context = build_table_page_context_from_params(
            rows=rows,
            columns=columns,
            pagination=pagination_info,
            filter_options=filter_options,
            params=params,
            authenticated=True,
            systems_info=get_all_systems_info(),
            estimation_links=ESTIMATION_LINKS,
        )

        return render_table_page_response(
            "estimated_results.html",
            page_context=page_context,
            no_store=True,
            redirect_endpoint="estimated.estimated_results",
            params=params,
        )
