import os
import sys
import types


def _setup_stubs():
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")

    otp_mod = types.ModuleType("utils.otp_manager")
    otp_mod.get_affiliations = lambda email: ["dev"]
    otp_mod.is_allowed = lambda email: True
    sys.modules["utils.otp_manager"] = otp_mod

    otp_redis_mod = types.ModuleType("utils.otp_redis_manager")
    otp_redis_mod.get_affiliations = lambda email: ["dev"]
    otp_redis_mod.is_allowed = lambda email: True
    otp_redis_mod.send_otp = lambda email: (True, "stub")
    otp_redis_mod.verify_otp = lambda email, code: True
    otp_redis_mod.invalidate_otp = lambda email: None
    sys.modules["utils.otp_redis_manager"] = otp_redis_mod


_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
