"""Compare explicit version records without judging accuracy or scheduling work."""


def compare_estimate_versions(previous, candidate):
    """Compare two Estimate payloads for the same app.

    Versions are opaque identifiers, not ordered releases. A difference is not
    proof that the candidate is newer or that re-estimation is appropriate.
    Missing/ambiguous records remain unknown. Conditions, observation versions,
    FOMs and repository commits do not participate in this comparison.
    """
    if not isinstance(previous, dict) or not isinstance(candidate, dict):
        return _unknown_result("invalid_estimate")
    code = previous.get("code")
    if not _identifier(code) or not _identifier(candidate.get("code")):
        return _unknown_result("missing_app")
    if code != candidate["code"]:
        return _unknown_result("different_app")

    before, before_issues = _version_records(previous)
    after, after_issues = _version_records(candidate)
    changes, unknowns = [], []
    for key in sorted(before.keys() | after.keys()):
        old, new = before.get(key), after.get(key)
        entry = {"scope": list(key[:-1]), "component": key[-1],
                 "previous": old, "candidate": new}
        if not _complete(old) or not _complete(new):
            unknowns.append({**entry, "reason": "missing_name_or_version"})
        elif old != new:
            changes.append(entry)
    unknowns.extend({**issue, "source": "previous"} for issue in before_issues)
    unknowns.extend({**issue, "source": "candidate"} for issue in after_issues)
    return {
        "status": "different" if changes else "unknown" if unknowns else "same",
        "complete": not unknowns,
        "changes": changes,
        "unknowns": unknowns,
    }


def _unknown_result(reason):
    return {"status": "unknown", "complete": False, "changes": [],
            "unknowns": [{"reason": reason}]}


def _identifier(value):
    return isinstance(value, str) and bool(value.strip())


def _complete(record):
    return (isinstance(record, dict) and _identifier(record.get("name"))
            and _identifier(record.get("version")))


def _version_records(estimate):
    records, issues = {}, []

    def add(scope, component, name, version):
        records[(*scope, component)] = {"name": name, "version": version}

    def packages(node, scope):
        for prefix, component in (("", "applied_package"),
                                  ("requested_", "requested_package")):
            name_key = f"{prefix}estimation_package"
            version_key = f"{name_key}_version"
            if name_key in node or version_key in node:
                add(scope, component, node.get(name_key), node.get(version_key))

    def model(node, scope):
        if "model" not in node:
            return
        value = node["model"]
        if not isinstance(value, dict):
            value = {}
        add(scope, "model", value.get("name"), value.get("version"))

    def named_nodes(value, scope, kind):
        if not isinstance(value, list):
            issues.append({"scope": list(scope), "reason": "invalid_collection"})
            return
        grouped = {}
        for node in value:
            if not isinstance(node, dict):
                issues.append({"scope": list(scope), "reason": "invalid_component"})
                continue
            name = (node.get("name") if kind != "candidate" else
                    node.get("requested_estimation_package") or node.get("estimation_package"))
            if not _identifier(name):
                issues.append({"scope": list(scope), "reason": "missing_component_name"})
                continue
            grouped.setdefault(name, []).append(node)
        for name, nodes in grouped.items():
            child_scope = (*scope, kind, name)
            if len(nodes) != 1:
                issues.append({"scope": list(child_scope), "reason": "ambiguous_component"})
                continue
            visit(nodes[0], child_scope)

    def visit(node, scope):
        if not isinstance(node, dict):
            issues.append({"scope": list(scope), "reason": "invalid_component"})
            return
        packages(node, scope)
        model(node, scope)
        if "candidate_estimates" in node:
            named_nodes(node["candidate_estimates"], scope, "candidate")

    metadata = estimate.get("estimate_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        issues.append({"scope": ["estimate_metadata"], "reason": "invalid_component"})
    method = metadata.get("app_estimation_method", {})
    add(("app",), "estimation_method", estimate["code"],
        method.get("version") if isinstance(method, dict) else None)
    packages(metadata, ("top_level",))
    model(estimate, ("top_level",))
    for side in ("current", "future"):
        package_key = f"{side}_package"
        if package_key in metadata:
            visit(metadata[package_key], (side, "package"))
        system_key = f"{side}_system"
        if system_key not in estimate:
            continue
        system = estimate[system_key]
        visit(system, (side,))
        if not isinstance(system, dict):
            continue
        breakdown = system.get("fom_breakdown", {})
        if not isinstance(breakdown, dict):
            issues.append({"scope": [side, "fom_breakdown"], "reason": "invalid_component"})
            continue
        for kind in ("sections", "overlaps"):
            if kind in breakdown:
                named_nodes(breakdown[kind], (side,), kind)
    return records, issues
