"""Restore explicit re-estimation settings before invoking an app estimator."""

import json
import os
from pathlib import Path
import re
import sys


FIELDS = {
    "BK_ESTIMATION_BASELINE_SYSTEM": lambda s: s.get("assumptions", {}).get("baseline_system") or s.get("current_system", {}).get("system"),
    "BK_ESTIMATION_BASELINE_EXP": lambda s: s.get("estimate_metadata", {}).get("current_source_result", {}).get("exp") or s.get("exp"),
    "BK_ESTIMATION_FUTURE_SYSTEM": lambda s: s.get("future_system", {}).get("system"),
    "BK_ESTIMATION_CURRENT_TARGET_NODES": lambda s: s.get("current_system", {}).get("target_nodes"),
    "BK_ESTIMATION_FUTURE_TARGET_NODES": lambda s: s.get("future_system", {}).get("target_nodes"),
    "BK_ESTIMATION_CURRENT_PACKAGE": lambda s: s.get("estimate_metadata", {}).get("current_package", {}).get("requested_estimation_package"),
    "BK_ESTIMATION_FUTURE_PACKAGE": lambda s: s.get("estimate_metadata", {}).get("future_package", {}).get("requested_estimation_package"),
}


def resolve_conditions(source, context, environment):
    if context.get("scope", "both") != "both":
        raise ValueError("Only both-side re-estimation is supported")
    policy = environment.get("reestimation_baseline_policy") or context.get("baseline_policy", "reuse-recorded-baseline")
    if policy not in ("reuse-recorded-baseline", "select-latest-baseline"):
        raise ValueError("Unsupported baseline policy")
    environment = dict(environment)
    if "BK_ESTIMATION_PACKAGE" in environment:
        if "BK_ESTIMATION_FUTURE_PACKAGE" in environment and environment["BK_ESTIMATION_PACKAGE"] != environment["BK_ESTIMATION_FUTURE_PACKAGE"]:
            raise ValueError("Conflicting future package settings")
        environment["BK_ESTIMATION_FUTURE_PACKAGE"] = environment["BK_ESTIMATION_PACKAGE"]
    future_uuid = source.get("future_system", {}).get("benchmark", {}).get("uuid")
    if future_uuid and future_uuid != context.get("source_result_uuid"):
        raise ValueError("Separate future reference restoration is not supported")
    settings = {}
    changes = {}
    for name, extract in FIELDS.items():
        recorded = extract(source)
        supplied = environment.get(name)
        value = supplied if supplied is not None else recorded
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
            raise ValueError(f"Missing or invalid re-estimation condition: {name}")
        value = str(value)
        if name.endswith("TARGET_NODES") and not re.fullmatch(r"[1-9][0-9]*", value):
            raise ValueError(f"Invalid node count: {name}")
        if name.endswith("PACKAGE") and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError(f"Invalid package identifier: {name}")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError(f"Invalid re-estimation condition: {name}")
        settings[name] = value
        if supplied is not None:
            changes[name] = {"recorded": recorded, "requested": value}
    if policy == "reuse-recorded-baseline":
        uuid = environment.get("BK_ESTIMATION_BASELINE_UUID") or source.get("current_system", {}).get("benchmark", {}).get("uuid")
        if not isinstance(uuid, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", uuid):
            raise ValueError("Recorded baseline UUID is missing or invalid")
        settings["BK_ESTIMATION_BASELINE_UUID"] = uuid
        changes_uuid = environment.get("BK_ESTIMATION_BASELINE_UUID")
        if changes_uuid is not None:
            changes["BK_ESTIMATION_BASELINE_UUID"] = {
                "recorded": source.get("current_system", {}).get("benchmark", {}).get("uuid"),
                "requested": uuid,
            }
    elif environment.get("BK_ESTIMATION_BASELINE_UUID"):
        raise ValueError("Latest baseline selection cannot specify a baseline UUID")
    settings["BK_ESTIMATION_PACKAGE"] = settings["BK_ESTIMATION_FUTURE_PACKAGE"]
    return settings, {"baseline_policy": policy, "conditions": settings, "explicit_changes": changes}


def main():
    context_path = Path("results/reestimation_context.json")
    environment = dict(os.environ)
    if context_path.exists():
        source = json.loads(Path("results/source_estimate.json").read_text())
        context = json.loads(context_path.read_text())
        settings, request = resolve_conditions(source, context, environment)
        environment.update(settings)
        context["baseline_policy"] = request["baseline_policy"]
        context["resolved_request"] = request
        temporary = context_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(context, indent=2) + "\n")
        temporary.replace(context_path)
    os.execvpe("bash", ["bash", *sys.argv[1:]], environment)


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(f"ERROR: Re-estimation conditions could not be restored: {error}", file=sys.stderr)
        sys.exit(1)
    except (OSError, TypeError, AttributeError):
        print("ERROR: Re-estimation conditions could not be restored; check recorded conditions and explicit settings", file=sys.stderr)
        sys.exit(1)
