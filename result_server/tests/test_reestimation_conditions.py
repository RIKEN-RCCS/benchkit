import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


spec = importlib.util.spec_from_file_location(
    "reestimation_conditions",
    Path(__file__).parents[2] / "scripts" / "estimation" / "reestimation_conditions.py",
)
conditions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conditions)


@pytest.fixture
def source():
    return {
        "exp": "case-a",
        "current_system": {
            "system": "CPU-A", "target_nodes": "2",
            "benchmark": {"uuid": "11111111-1111-1111-1111-111111111111"},
        },
        "future_system": {"system": "CPU-B", "target_nodes": "8"},
        "estimate_metadata": {
            "current_package": {"requested_estimation_package": "weakscaling"},
            "future_package": {
                "requested_estimation_package": "instrumented_app_sections_dummy",
                "estimation_package": "identity",
            },
        },
    }


def test_restores_recorded_conditions_not_fallback(source):
    settings, request = conditions.resolve_conditions(source, {}, {})
    assert settings["BK_ESTIMATION_CURRENT_TARGET_NODES"] == "2"
    assert settings["BK_ESTIMATION_FUTURE_TARGET_NODES"] == "8"
    assert settings["BK_ESTIMATION_FUTURE_PACKAGE"] == "instrumented_app_sections_dummy"
    assert settings["BK_ESTIMATION_BASELINE_UUID"] == source["current_system"]["benchmark"]["uuid"]
    assert request["explicit_changes"] == {}


def test_explicit_changes_are_recorded(source):
    settings, request = conditions.resolve_conditions(source, {}, {"BK_ESTIMATION_FUTURE_TARGET_NODES": "16"})
    assert settings["BK_ESTIMATION_FUTURE_TARGET_NODES"] == "16"
    assert request["explicit_changes"]["BK_ESTIMATION_FUTURE_TARGET_NODES"] == {"recorded": "8", "requested": "16"}


def test_missing_record_can_be_supplied_explicitly(source):
    del source["future_system"]["target_nodes"]
    with pytest.raises(ValueError, match="Missing"):
        conditions.resolve_conditions(source, {}, {})
    settings, _ = conditions.resolve_conditions(source, {}, {"BK_ESTIMATION_FUTURE_TARGET_NODES": "4"})
    assert settings["BK_ESTIMATION_FUTURE_TARGET_NODES"] == "4"


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "$(touch bad)", True])
def test_invalid_nodes_are_not_defaults(source, value):
    source["future_system"]["target_nodes"] = value
    with pytest.raises(ValueError):
        conditions.resolve_conditions(source, {}, {})


def test_latest_policy_does_not_pin_uuid(source):
    settings, request = conditions.resolve_conditions(source, {}, {"reestimation_baseline_policy": "select-latest-baseline"})
    assert "BK_ESTIMATION_BASELINE_UUID" not in settings
    assert request["baseline_policy"] == "select-latest-baseline"


def test_latest_policy_rejects_conflicting_uuid(source):
    with pytest.raises(ValueError):
        conditions.resolve_conditions(source, {"baseline_policy": "select-latest-baseline"}, {
            "BK_ESTIMATION_BASELINE_UUID": source["current_system"]["benchmark"]["uuid"],
        })


def test_missing_baseline_uuid_is_not_latest_selection(source):
    source["current_system"]["benchmark"] = {}
    with pytest.raises(ValueError, match="UUID"):
        conditions.resolve_conditions(source, {}, {})


@pytest.mark.parametrize("context", [{"scope": "future"}, {"baseline_policy": "unknown"}])
def test_unsupported_requests_are_rejected(source, context):
    with pytest.raises(ValueError):
        conditions.resolve_conditions(source, context, {})


def test_applied_package_does_not_replace_missing_requested_package(source):
    del source["estimate_metadata"]["future_package"]["requested_estimation_package"]
    with pytest.raises(ValueError, match="FUTURE_PACKAGE"):
        conditions.resolve_conditions(source, {}, {})


def test_generic_package_override_is_explicit(source):
    settings, request = conditions.resolve_conditions(source, {}, {"BK_ESTIMATION_PACKAGE": "new_package"})
    assert settings["BK_ESTIMATION_PACKAGE"] == settings["BK_ESTIMATION_FUTURE_PACKAGE"] == "new_package"
    assert request["explicit_changes"]["BK_ESTIMATION_FUTURE_PACKAGE"]["requested"] == "new_package"


def test_conflicting_package_overrides_are_rejected(source):
    with pytest.raises(ValueError, match="Conflicting"):
        conditions.resolve_conditions(source, {}, {"BK_ESTIMATION_PACKAGE": "a", "BK_ESTIMATION_FUTURE_PACKAGE": "b"})


@pytest.mark.parametrize("package", ["../outside", "/tmp/package", "$(command)", "a\nb"])
def test_invalid_package_identifiers_are_rejected(source, package):
    with pytest.raises(ValueError):
        conditions.resolve_conditions(source, {}, {"BK_ESTIMATION_FUTURE_PACKAGE": package})


def test_separate_future_reference_is_not_silently_replaced(source):
    source["future_system"]["benchmark"] = {"uuid": "22222222-2222-2222-2222-222222222222"}
    with pytest.raises(ValueError, match="Separate"):
        conditions.resolve_conditions(source, {"source_result_uuid": "other"}, {})
    conditions.resolve_conditions(source, {"source_result_uuid": "22222222-2222-2222-2222-222222222222"}, {})


def test_entrypoint_restores_environment_and_records_request(source, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "source_estimate.json").write_text(json.dumps(source))
    context_path = results / "reestimation_context.json"
    context_path.write_text(json.dumps({"source_result_uuid": "original", "reason": "manual-rerun"}))
    script = tmp_path / "estimate.sh"
    script.write_text('printf "%s" "$BK_ESTIMATION_FUTURE_TARGET_NODES" > executed.txt\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BK_ESTIMATION_", "reestimation_"))}
    env["BK_ESTIMATION_FUTURE_TARGET_NODES"] = "16"
    subprocess.run([sys.executable, str(spec.origin), str(script)], cwd=tmp_path, env=env, check=True)
    assert (tmp_path / "executed.txt").read_text() == "16"
    context = json.loads(context_path.read_text())
    assert context["reason"] == "manual-rerun"
    assert context["resolved_request"]["explicit_changes"]["BK_ESTIMATION_FUTURE_TARGET_NODES"]["recorded"] == "8"


def test_missing_conditions_do_not_execute_app(source, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    del source["current_system"]["target_nodes"]
    (results / "source_estimate.json").write_text(json.dumps(source))
    (results / "reestimation_context.json").write_text("{}")
    script = tmp_path / "estimate.sh"
    script.write_text("touch executed.txt\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BK_ESTIMATION_", "reestimation_"))}
    completed = subprocess.run([sys.executable, str(spec.origin), str(script)], cwd=tmp_path, env=env, capture_output=True)
    assert completed.returncode == 1
    assert not (tmp_path / "executed.txt").exists()


@pytest.mark.parametrize("matches", [True, False])
@pytest.mark.parametrize("response_mode", ["filter", "uuid"])
def test_pinned_baseline_query_and_identity_check(matches, response_mode):
    uuid = "11111111-1111-1111-1111-111111111111"
    response = {"_meta": {"uuid": uuid if matches else "different"}, "system": "CPU-A", "code": "demo", "Exp": "case-a", "FOM": 2}
    if response_mode == "uuid":
        response.pop("_meta")
        response.update(_server_uuid=uuid if matches else "different", _server_timestamp="20261014_120000")
    else:
        response["_meta"]["timestamp"] = "2026-10-14 12:00:00"
    script = '''
set -e
source scripts/estimation/result_query.sh
bk_result_server_get_json() {
  [[ "$1" == "/api/query/result?uuid=$BK_ESTIMATION_BASELINE_UUID" ]] || return 1
  printf '%s' "$RESPONSE"
}
fetch_current_fom CPU-A demo case-a
[[ "$est_current_bench_uuid" == "$BK_ESTIMATION_BASELINE_UUID" ]]
[[ "$est_current_bench_timestamp" == "2026-10-14 12:00:00" ]]
'''
    result = subprocess.run(["bash", "-c", script], cwd=Path(__file__).parents[2],
                            env={**os.environ, "RESULT_SERVER": "https://example.test", "BK_ESTIMATION_BASELINE_UUID": uuid, "RESPONSE": json.dumps(response)},
                            capture_output=True)
    assert (result.returncode == 0) == matches
