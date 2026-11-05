"""Restore explicit re-estimation settings before invoking an app estimator."""

import json
import importlib.util
import os
from pathlib import Path
import re
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent))
from neural_models import MODELS as NEURAL_MODELS


FIELDS = {
    "BK_ESTIMATION_BASELINE_SYSTEM": lambda s: (s.get("assumptions") if isinstance(s.get("assumptions"), dict) else {}).get("baseline_system") or s.get("current_system", {}).get("system"),
    "BK_ESTIMATION_BASELINE_EXP": lambda s: s.get("estimate_metadata", {}).get("current_source_result", {}).get("exp") or s.get("exp"),
    "BK_ESTIMATION_FUTURE_SYSTEM": lambda s: s.get("future_system", {}).get("system"),
    "BK_ESTIMATION_CURRENT_TARGET_NODES": lambda s: s.get("current_system", {}).get("target_nodes"),
    "BK_ESTIMATION_FUTURE_TARGET_NODES": lambda s: s.get("future_system", {}).get("target_nodes"),
    "BK_ESTIMATION_CURRENT_PACKAGE": lambda s: s.get("estimate_metadata", {}).get("current_package", {}).get("requested_estimation_package"),
    "BK_ESTIMATION_FUTURE_PACKAGE": lambda s: s.get("estimate_metadata", {}).get("future_package", {}).get("requested_estimation_package"),
}


# Explicit model settings only; never snapshot arbitrary environment variables.
MODEL_CONDITIONS = {
    prefix + '_' + field: ('commit' if field == 'PERFTOOLS_COMMIT' else 'identifier')
    for prefix in ({'BK_GPU_LIGHTGBM', 'BK_GPU_MLP'} |
                   {p for model in NEURAL_MODELS.values() for p in model.environment_prefixes})
    for field in ('SOURCE_GPU', 'TARGET_GPU', 'PERFTOOLS_COMMIT')
}
MODEL_CONDITIONS['BK_GPU_KERNEL_ENSEMBLE_PACKAGES'] = 'package_list'


def validate_model_condition(value, kind, name):
    if kind == 'package_list':
        if not isinstance(value, str):
            raise ValueError('Invalid model candidate list: ' + name)
        candidates = [p.strip() for p in value.split(',')]
        if not candidates or any(not re.fullmatch(r'[A-Za-z0-9_]+', p) for p in candidates):
            raise ValueError('Invalid model candidate list: ' + name)
        return ','.join(candidates)
    pattern = r'[0-9a-fA-F]{40}' if kind == 'commit' else r'[A-Za-z0-9_.-]+'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError('Missing or invalid re-estimation condition: ' + name)
    return value




def observed_neural_conditions(source):
    """Use applied future candidates, never old parent records or arbitrary env."""
    by_package = {model.package: model for model in NEURAL_MODELS.values()}
    values, candidate_lists = {}, set()

    def remember(name, value):
        value = validate_model_condition(value, MODEL_CONDITIONS[name], name)
        if name in values and values[name] != value:
            raise ValueError('Conflicting applied neural conditions: ' + name)
        values[name] = value

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            candidates = node.get('candidate_estimates')
            if isinstance(candidates, list) and candidates:
                packages = [item.get('requested_estimation_package') or item.get('estimation_package')
                            for item in candidates if isinstance(item, dict)]
                if len(packages) == len(candidates) and all(isinstance(p, str) for p in packages):
                    candidate_lists.add(validate_model_condition(','.join(packages), 'package_list', 'candidates'))
            model = by_package.get(node.get('estimation_package'))
            if model:
                declaration = node.get('model') or {}
                commit = (declaration.get('provenance') or {}).get('external_commit')
                if commit:
                    if declaration.get('version') != model.release:
                        raise ValueError('Applied neural release disagrees with its package')
                    prefix = model.environment_prefixes[0]
                    remember(prefix + '_PERFTOOLS_COMMIT', commit)
                    for side in ('source', 'target'):
                        gpus = (node.get('metrics') or {}).get(side + '_gpus')
                        if isinstance(gpus, list) and len(gpus) == 1:
                            remember(prefix + '_' + side.upper() + '_GPU', gpus[0])
            for value in node.values():
                visit(value)

    visit(source.get('future_system') or {})
    if len(candidate_lists) == 1:
        values['BK_GPU_KERNEL_ENSEMBLE_PACKAGES'] = candidate_lists.pop()
    return values


def record_execution_conditions(path):
    source = json.loads(path.read_text())
    method_values, _ = method_conditions(source)
    recorded = {key: extract(source) for key, extract in FIELDS.items()}
    for key, value in method_values.items():
        if recorded.get(key) is None:
            recorded[key] = value
    for key in MODEL_CONDITIONS:
        if os.environ.get(key):
            recorded[key] = validate_model_condition(os.environ[key], MODEL_CONDITIONS[key], key)
    for key, value in observed_neural_conditions(source).items():
        if key in recorded and recorded[key] is not None and recorded[key] != value:
            # Per-section candidate declarations take precedence over the global list.
            if key == 'BK_GPU_KERNEL_ENSEMBLE_PACKAGES':
                continue
            raise ValueError('Requested and applied neural conditions differ: ' + key)
        recorded[key] = value
    source.setdefault('estimate_metadata', {})['execution_conditions'] = {
        key: value for key, value in recorded.items() if value is not None}
    temporary = path.with_suffix('.conditions.tmp')
    temporary.write_text(json.dumps(source, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def method_conditions(source):
    code = source.get('code')
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', code):
        return {}, {}
    root = Path(__file__).resolve().parents[2]
    path = root / 'programs' / code / 'estimation/conditions.py'
    if not path.is_file():
        return {}, {}
    if path.is_symlink() or root not in path.resolve().parents:
        raise ValueError('Unsafe method conditions adapter')
    spec = importlib.util.spec_from_file_location('_estimation_method_conditions', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.recorded_conditions(source)


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
    method_values, method_types = method_conditions(source)
    saved = source.get('estimate_metadata', {}).get('execution_conditions', {})
    if not isinstance(saved, dict):
        raise ValueError('Invalid recorded execution conditions')
    for name, extract in FIELDS.items():
        recorded = extract(source)
        recorded = saved.get(name, recorded)
        if recorded is None:
            recorded = method_values.get(name)
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
    model_types = {key: kind for key, kind in MODEL_CONDITIONS.items() if key in saved or key in environment}
    for name, kind in {**model_types, **method_types}.items():
        if name in FIELDS or not re.fullmatch(r'BK_[A-Z0-9_]+', name) or kind not in ('commit', 'identifier', 'package_list'):
            raise ValueError('Invalid method condition declaration')
        recorded = saved.get(name, method_values.get(name))
        value = environment.get(name, recorded)
        value = validate_model_condition(value, kind, name)
        settings[name] = value
        if name in environment:
            changes[name] = dict(recorded=recorded, requested=value)
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
    if len(sys.argv) == 3 and sys.argv[1] == "--record":
        record_execution_conditions(Path(sys.argv[2]))
        return
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
