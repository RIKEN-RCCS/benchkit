from flask import current_app, render_template, request

from utils.results_loader import DEFAULT_PER_PAGE, get_filter_options, load_results_table
from utils.session_user_context import get_session_user_context
from utils.system_info import get_all_systems_info
from utils.table_page_utils import (
    build_auth_required_table_page_context,
    build_table_page_context_from_params,
    build_table_page_redirect_from_params,
    render_no_store_template,
)
from utils.table_query_params import parse_table_query_params


def _render_confidential_auth_required():
    auth_required_context = build_auth_required_table_page_context(
        per_page=DEFAULT_PER_PAGE,
        systems_info=get_all_systems_info(),
        authenticated=False,
    )
    return render_no_store_template("results_confidential.html", **auth_required_context)


def _render_results_list(public_only, template_name, redirect_endpoint):
    params = parse_table_query_params(request.args)

    received_dir = current_app.config["RECEIVED_DIR"]
    received_padata_dir = current_app.config.get("RECEIVED_PADATA_DIR", received_dir)

    load_kwargs = dict(
        public_only=public_only,
        page=params["page"],
        per_page=params["per_page"],
        filter_system=params["filter_system"],
        filter_code=params["filter_code"],
        filter_exp=params["filter_exp"],
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

    if params["page"] != pagination_info["page"]:
        return build_table_page_redirect_from_params(
            redirect_endpoint,
            pagination_info["page"],
            params,
        )

    filter_options = get_filter_options(received_dir, filter_code=params["filter_code"], **filter_kwargs)
    render_context = build_table_page_context_from_params(
        rows=rows,
        columns=columns,
        pagination=pagination_info,
        filter_options=filter_options,
        params=params,
        systems_info=get_all_systems_info(),
        **template_extra,
    )
    if not public_only:
        return render_no_store_template(template_name, **render_context)
    return render_template(template_name, **render_context)


def register_results_list_routes(results_bp):
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
