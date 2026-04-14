from flask import current_app, request

from utils.results_loader import (
    DEFAULT_PER_PAGE,
    ESTIMATED_FIELD_MAP,
    get_filter_options,
    load_estimated_results_table,
)
from utils.session_user_context import get_session_user_context
from utils.system_info import get_all_systems_info
from utils.table_page_utils import (
    build_table_page_context,
    build_table_page_redirect,
    render_no_store_template,
)
from utils.table_query_params import parse_table_query_params


def _render_estimated_results_page(**context):
    return render_no_store_template("estimated_results.html", **context)


def _render_estimated_auth_required():
    auth_required_context = build_table_page_context(
        rows=[],
        columns=[],
        pagination={"page": 1, "per_page": DEFAULT_PER_PAGE, "total": 0, "total_pages": 1},
        filter_options={"systems": [], "codes": [], "exps": []},
        current_system=None,
        current_code=None,
        current_exp=None,
        current_per_page=DEFAULT_PER_PAGE,
        authenticated=False,
        systems_info=get_all_systems_info(),
    )
    return _render_estimated_results_page(**auth_required_context)


def _build_estimated_results_context(
    estimated_dir,
    email,
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
        session_email=email,
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

    return build_table_page_context(
        rows=rows,
        columns=columns,
        pagination=pagination_info,
        filter_options=filter_options,
        current_system=filter_system,
        current_code=filter_code,
        current_exp=filter_exp,
        current_per_page=per_page,
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
        page = params["page"]
        per_page = params["per_page"]
        filter_system = params["filter_system"]
        filter_code = params["filter_code"]
        filter_exp = params["filter_exp"]

        estimated_dir = current_app.config["ESTIMATED_DIR"]
        page_context = _build_estimated_results_context(
            estimated_dir=estimated_dir,
            email=user_context["email"],
            authenticated=user_context["authenticated"],
            affiliations=user_context["affiliations"],
            page=page,
            per_page=per_page,
            filter_system=filter_system,
            filter_code=filter_code,
            filter_exp=filter_exp,
        )

        pagination_info = page_context["pagination"]
        if page != pagination_info["page"]:
            return build_table_page_redirect(
                "estimated.estimated_results",
                pagination_info["page"],
                per_page,
                filter_system,
                filter_code,
                filter_exp,
            )

        return _render_estimated_results_page(**page_context)
