from flask import current_app, request

from utils.results_loader import (
    ESTIMATED_FIELD_MAP,
    load_estimated_results_table,
)
from utils.session_user_context import get_session_user_context
from utils.system_info import get_all_systems_info
from utils.table_filters import get_filter_options
from utils.table_pagination import DEFAULT_PER_PAGE
from utils.table_page_utils import (
    build_table_page_context_from_params,
    render_auth_required_table_page,
    render_table_page_response,
)
from utils.table_query_params import parse_table_query_params


def _render_estimated_auth_required():
    return render_auth_required_table_page(
        "estimated_results.html",
        per_page=DEFAULT_PER_PAGE,
        authenticated=False,
        systems_info=get_all_systems_info(),
    )


def _build_estimated_results_context(
    estimated_dir,
    authenticated,
    affiliations,
    page,
    per_page,
    filter_system,
    filter_code,
    filter_exp,
):
    rows, columns, pagination_info = load_estimated_results_table(
        estimated_dir,
        public_only=(not authenticated),
        authenticated=authenticated,
        affiliations=affiliations,
        page=page,
        per_page=per_page,
        filter_system=filter_system,
        filter_code=filter_code,
        filter_exp=filter_exp,
    )

    filter_options = get_filter_options(
        estimated_dir,
        public_only=(not authenticated),
        authenticated=authenticated,
        affiliations=affiliations,
        field_map=ESTIMATED_FIELD_MAP,
    )

    return build_table_page_context_from_params(
        rows=rows,
        columns=columns,
        pagination=pagination_info,
        filter_options=filter_options,
        params={
            "filter_system": filter_system,
            "filter_code": filter_code,
            "filter_exp": filter_exp,
            "per_page": per_page,
        },
        authenticated=authenticated,
        systems_info=get_all_systems_info(),
    )


def register_estimated_list_routes(estimated_bp):
    @estimated_bp.route("/", methods=["GET"], strict_slashes=False)
    def estimated_results():
        user_context = get_session_user_context()
        if not user_context["authenticated"]:
            return _render_estimated_auth_required()

        params = parse_table_query_params(request.args)
        estimated_dir = current_app.config["ESTIMATED_DIR"]
        page_context = _build_estimated_results_context(
            estimated_dir=estimated_dir,
            authenticated=user_context["authenticated"],
            affiliations=user_context["affiliations"],
            page=params["page"],
            per_page=params["per_page"],
            filter_system=params["filter_system"],
            filter_code=params["filter_code"],
            filter_exp=params["filter_exp"],
        )

        return render_table_page_response(
            "estimated_results.html",
            page_context=page_context,
            no_store=True,
            redirect_endpoint="estimated.estimated_results",
            params=params,
        )
