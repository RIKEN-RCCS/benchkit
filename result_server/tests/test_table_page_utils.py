import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import build_portal_shell_app, build_results_index_app
from utils.table_page_utils import (
    build_auth_required_table_page_context,
    build_filtered_redirect_args,
    build_table_page_context,
    build_table_page_context_from_params,
    build_table_page_redirect,
    build_table_page_redirect_from_params,
    render_auth_required_table_page,
    render_no_store_template,
    render_table_page_response,
)


def test_build_filtered_redirect_args_omits_missing_filters():
    args = build_filtered_redirect_args(2, 50, "Fugaku", None, "CASE0")

    assert args == {
        "page": 2,
        "per_page": 50,
        "system": "Fugaku",
        "exp": "CASE0",
    }


def test_render_no_store_template_sets_cache_headers():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )

    with app.test_request_context("/estimated"):
        response = render_no_store_template("estimated_results.html", authenticated=False, rows=[], columns=[], systems_info={}, pagination={"page": 1, "per_page": 100, "total": 0, "total_pages": 1}, filter_options={"systems": [], "codes": [], "exps": []}, current_system=None, current_code=None, current_exp=None, current_per_page=100)

    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"


def test_build_table_page_context_keeps_common_keys():
    context = build_table_page_context(
        rows=[{"filename": "result0.json"}],
        columns=[{"key": "system", "label": "System"}],
        pagination={"page": 2, "per_page": 50, "total": 3, "total_pages": 1},
        filter_options={"systems": ["Fugaku"], "codes": ["qws"], "exps": ["CASE0"]},
        current_system="Fugaku",
        current_code="qws",
        current_exp="CASE0",
        current_per_page=50,
        systems_info={"Fugaku": {"name": "Fugaku"}},
        authenticated=True,
    )

    assert context["rows"] == [{"filename": "result0.json"}]
    assert context["columns"][0]["key"] == "system"
    assert context["pagination"]["page"] == 2
    assert context["systems_info"]["Fugaku"]["name"] == "Fugaku"
    assert context["authenticated"] is True


def test_build_table_page_context_from_params_maps_filters():
    context = build_table_page_context_from_params(
        rows=[{"filename": "result0.json"}],
        columns=[{"key": "system", "label": "System"}],
        pagination={"page": 2, "per_page": 50, "total": 3, "total_pages": 1},
        filter_options={"systems": ["Fugaku"], "codes": ["qws"], "exps": ["CASE0"]},
        params={"filter_system": "Fugaku", "filter_code": "qws", "filter_exp": "CASE0", "per_page": 50},
        systems_info={"Fugaku": {"name": "Fugaku"}},
        authenticated=True,
    )

    assert context["current_system"] == "Fugaku"
    assert context["current_code"] == "qws"
    assert context["current_exp"] == "CASE0"
    assert context["current_per_page"] == 50


def test_build_auth_required_table_page_context_builds_empty_page():
    context = build_auth_required_table_page_context(
        per_page=100,
        systems_info={"Fugaku": {"name": "Fugaku"}},
        authenticated=False,
    )

    assert context["rows"] == []
    assert context["columns"] == []
    assert context["pagination"]["per_page"] == 100
    assert context["authenticated"] is False


def test_render_auth_required_table_page_renders_no_store_response():
    app = build_portal_shell_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )

    with app.test_request_context("/estimated"):
        response = render_auth_required_table_page(
            "estimated_results.html",
            per_page=100,
            systems_info={},
            authenticated=False,
        )

    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]


def test_build_table_page_redirect_uses_filtered_args():
    app = build_results_index_app()

    with app.test_request_context("/results"):
        response = build_table_page_redirect("results.results", 3, 20, "Fugaku", "qws", None)

    assert response.status_code == 302
    assert response.location.endswith("/results/?page=3&per_page=20&system=Fugaku&code=qws")


def test_build_table_page_redirect_from_params_uses_param_map():
    app = build_results_index_app()

    with app.test_request_context("/results"):
        response = build_table_page_redirect_from_params(
            "results.results",
            4,
            {"per_page": 10, "filter_system": "Fugaku", "filter_code": None, "filter_exp": "CASE0"},
        )

    assert response.status_code == 302
    assert response.location.endswith("/results/?page=4&per_page=10&system=Fugaku&exp=CASE0")


def test_render_table_page_response_redirects_when_page_changes():
    app = build_results_index_app()

    with app.test_request_context("/results"):
        response = render_table_page_response(
            "results.html",
            page_context={
                "rows": [],
                "columns": [],
                "pagination": {"page": 2, "per_page": 50, "total": 10, "total_pages": 1},
                "filter_options": {"systems": [], "codes": [], "exps": []},
                "current_system": None,
                "current_code": None,
                "current_exp": None,
                "current_per_page": 50,
            },
            redirect_endpoint="results.results",
            params={"page": 1, "per_page": 50, "filter_system": None, "filter_code": None, "filter_exp": None},
        )

    assert response.status_code == 302
    assert response.location.endswith("/results/?page=2&per_page=50")
