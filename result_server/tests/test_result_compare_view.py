import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_support import install_portal_test_stubs

install_portal_test_stubs()

from utils.result_compare_view import build_result_compare_context


def test_build_result_compare_context_marks_same_system_code_as_not_mixed():
    context = build_result_compare_context(
        [
            {"data": {"system": "Fugaku", "code": "qws", "FOM": 1.0}},
            {"data": {"system": "Fugaku", "code": "qws", "FOM": 0.9}},
        ]
    )

    assert context["headline"] == "Fugaku / qws - Comparing 2 results"
    assert context["mixed"] is False
    assert context["has_vector_metrics"] is False


def test_build_result_compare_context_marks_mixed_rows():
    context = build_result_compare_context(
        [
            {"data": {"system": "Fugaku", "code": "qws"}},
            {"data": {"system": "Other", "code": "qws"}},
        ]
    )

    assert context["mixed"] is True
