from flask import abort, current_app, request, session
import hashlib
import hmac
import json
import secrets
import sqlite3

from utils.results_loader import load_results_table
from utils.result_catalog import CatalogUnavailable, ResultCatalog
from utils.session_user_context import get_session_user_context
from utils.system_info import get_all_systems_info
from utils.report_selection import definition_options, list_requested
from utils.table_pagination import DEFAULT_PER_PAGE
from utils.table_page_utils import (
    build_table_page_context_from_params,
    render_auth_required_table_page,
    render_table_page_response,
)
from utils.table_query_params import parse_table_query_params


def _render_results_list(public_only, template_name, redirect_endpoint):
    params = parse_table_query_params(request.args)
    for key in ('filter_system', 'filter_code', 'filter_exp'):
        params[key] = params[key] or None
    execute = (list_requested(request.args) if request.args.get('candidates') != '1'
               else request.args.get('search') == '1')
    public_surface = public_only and current_app.config.get("PUBLIC_PORTAL_MODE", False)

    received_dir = current_app.config["RECEIVED_DIR"]
    received_padata_dir = current_app.config.get(
        "RECEIVED_MEASUREMENT_ARTIFACTS_DIR",
        current_app.config.get("RECEIVED_PADATA_DIR", received_dir),
    )
    systems_info = get_all_systems_info()

    load_kwargs = dict(
        public_only=public_only,
        page=params["page"],
        per_page=params["per_page"],
        filter_system=params["filter_system"],
        filter_code=params["filter_code"],
        filter_exp=params["filter_exp"],
        padata_directory=received_padata_dir,
        execution_profile_db_path=current_app.config.get("EXECUTION_PROFILE_DB_PATH"),
        public_surface=public_surface,
    )
    template_extra = {}

    if not public_only:
        user_context = get_session_user_context()
        if not user_context["authenticated"]:
            return render_auth_required_table_page(
                "results_confidential.html",
                per_page=DEFAULT_PER_PAGE,
                systems_info=systems_info,
                authenticated=False,
            )
        load_kwargs.update(
            authenticated=user_context["authenticated"],
            affiliations=user_context["affiliations"],
        )
        template_extra["authenticated"] = user_context["authenticated"]

    if execute:
        catalog_path = current_app.config.get('RESULT_CATALOG_PATH')
        if catalog_path:
            try:
                catalog = ResultCatalog(catalog_path, received_dir, artifact_directory=received_padata_dir)
                with catalog.snapshot() as reader:
                    rows, columns, pagination_info = load_results_table(received_dir, query_reader=reader, **load_kwargs)
            except (CatalogUnavailable, sqlite3.Error, OSError, ValueError):
                abort(503, description='Result index unavailable; rebuilding may be required')
        else:
            rows, columns, pagination_info = load_results_table(received_dir, **load_kwargs)
    else:
        rows, columns = [], []
        pagination_info = {'page': 1, 'per_page': params['per_page'], 'total': 0, 'total_pages': 1}
    catalog_data, catalog_unavailable = None, False
    catalog_path = current_app.config.get("RESULT_CATALOG_PATH")
    filter_options = ({} if catalog_path else
                      definition_options(params['filter_code'], params['filter_system'], params['filter_exp']))
    if catalog_path:
        try:
            catalog_data = ResultCatalog(catalog_path, received_dir).candidates(
                public_only=public_only,
                authenticated=load_kwargs.get("authenticated", False),
                affiliations=load_kwargs.get("affiliations", ()),
                system=params['filter_system'], code=params['filter_code'], exp=params['filter_exp'],
                page=request.args.get('catalog_page', 1, type=int),
            )
            filter_options = {plural: [item['value'] for item in catalog_data['options'][field]]
                              for field, plural in [('system', 'systems'), ('code', 'codes'), ('exp', 'exps')]}
        except (CatalogUnavailable, sqlite3.Error, OSError, ValueError):
            # Never infer public visibility or report zero from an incomplete index.
            catalog_unavailable = True
            filter_options = {'systems': [], 'codes': [], 'exps': []}
    render_context = build_table_page_context_from_params(
        rows=rows,
        columns=columns,
        pagination=pagination_info,
        filter_options=filter_options,
        params=params,
        systems_info=systems_info,
        **template_extra,
    )
    render_context.update(search_executed=execute, explicit_search=True,
                          catalog_data=catalog_data, catalog_unavailable=catalog_unavailable)
    if not session.get('_result_comparison_scope'):
        session['_result_comparison_scope'] = secrets.token_hex(16)
    identity = [public_only, bool(session.get('authenticated')), session.get('user_email', ''),
                sorted(load_kwargs.get('affiliations', ())), session['_result_comparison_scope']]
    render_context['comparison_scope'] = hmac.new(
        str(current_app.secret_key).encode(), json.dumps(identity).encode(), hashlib.sha256).hexdigest()
    return render_table_page_response(
        template_name,
        page_context=render_context,
        no_store=not public_only,
        redirect_endpoint=redirect_endpoint,
        params=params,
    )


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
