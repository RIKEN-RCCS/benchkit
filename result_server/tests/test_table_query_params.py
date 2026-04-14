import os
import sys

from werkzeug.datastructures import MultiDict


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.table_query_params import parse_table_query_params


def test_parse_table_query_params_reads_filters_and_pagination():
    args = MultiDict([
        ("page", "3"),
        ("per_page", "50"),
        ("system", "Fugaku"),
        ("code", "qws"),
        ("exp", "CASE0"),
    ])

    params = parse_table_query_params(args)

    assert params == {
        "page": 3,
        "per_page": 50,
        "filter_system": "Fugaku",
        "filter_code": "qws",
        "filter_exp": "CASE0",
    }


def test_parse_table_query_params_falls_back_for_invalid_per_page():
    args = MultiDict([
        ("page", "1"),
        ("per_page", "75"),
    ])

    params = parse_table_query_params(args)

    assert params["page"] == 1
    assert params["per_page"] == 100
    assert params["filter_system"] is None
    assert params["filter_code"] is None
    assert params["filter_exp"] is None
