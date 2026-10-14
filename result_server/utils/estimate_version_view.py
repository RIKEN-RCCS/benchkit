"""Build an opt-in, authenticated detail view of recorded version differences."""

import os

from utils.estimate_version_snapshot import read_estimation_version_snapshot
from utils.estimate_versions import collect_estimate_version_records


def configure_estimate_version_check(app):
    for key in ("ESTIMATION_VERSION_REPO", "ESTIMATION_VERSION_REF"):
        app.config[key] = os.environ.get(f"RESULT_SERVER_{key}", "")


def build_estimate_version_check(estimate, config):
    repository = config.get("ESTIMATION_VERSION_REPO")
    ref = config.get("ESTIMATION_VERSION_REF")
    if config.get("PUBLIC_PORTAL_MODE") or not repository or not ref:
        return None

    view = {"status": "unknown", "commit": None, "ref": None,
            "changed_count": 0, "unknown_count": 0, "rows": []}
    if not isinstance(estimate, dict) or not isinstance(estimate.get("code"), str):
        view["unknown_count"] = 1
        return view

    records, issues = collect_estimate_version_records(estimate)
    packages, sections = set(), set()
    for key, record in records.items():
        if key[-1] not in ("applied_package", "requested_package"):
            continue
        name = record["name"]
        if isinstance(name, str) and name.strip():
            (packages if _top_level(key[:-1]) else sections).add(name)
    try:
        snapshot = read_estimation_version_snapshot(
            repository, ref, estimate["code"], packages=sorted(packages),
            section_packages=sorted(sections),
        )
    except (ValueError, TypeError):
        view["unknown_count"] = 1
        return view

    view.update(commit=snapshot["commit"], ref=snapshot["ref"] if snapshot["commit"] else None)
    for key, record in sorted(records.items()):
        scope, component = key[:-1], key[-1]
        name, old = record["name"], record["version"]
        declaration = None
        if component == "estimation_method":
            declaration = snapshot["app"]
        elif component in ("applied_package", "requested_package") and isinstance(name, str):
            group = "packages" if _top_level(scope) else "section_packages"
            declaration = snapshot[group].get(name)
        # Model identities/weights cannot be derived from a package version.
        new = declaration.get("version") if isinstance(declaration, dict) else None
        known = all(isinstance(value, str) and value.strip() for value in (name, old, new))
        if known and old == new:
            continue
        state = "different" if known else "unknown"
        view["changed_count" if known else "unknown_count"] += 1
        view["rows"].append({
            "scope": " / ".join(scope), "component": component.replace("_", " "),
            "name": name if isinstance(name, str) and name.strip() else "Unknown",
            "recorded": old if isinstance(old, str) and old.strip() else "Unknown",
            "reference": new if isinstance(new, str) and new.strip() else "Unknown",
            "status": state,
        })
    view["unknown_count"] += len(issues)
    if not records or (snapshot["commit"] is None and not view["unknown_count"]):
        view["unknown_count"] += 1
    view["status"] = ("different" if view["changed_count"] else
                      "unknown" if view["unknown_count"] else "same")
    return view


def _top_level(scope):
    return scope == ("top_level",) or (len(scope) == 2 and scope[1] == "package")
