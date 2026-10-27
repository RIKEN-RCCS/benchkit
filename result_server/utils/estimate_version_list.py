"""Permission-filtered, read-only overview of explicit Estimate version differences."""

from collections import Counter
from pathlib import Path

from flask import url_for
from werkzeug.exceptions import Forbidden

from utils.estimate_version_snapshot import read_estimation_version_reference
from utils.estimate_version_view import build_estimate_version_check
from utils.result_file import check_file_permission
from utils.result_records import load_result_json
from utils.table_pagination import paginate_list


def _text(value):
    return str(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _mapping(value):
    return value if isinstance(value, dict) else {}


def build_version_check_list(directory, config, *, status="different", code="", page=1, per_page=50):
    reference = {"ref": None, "commit": None}
    context = {"enabled": False, "reference": reference, "rows": [], "codes": [],
               "counts": {"different": 0, "unknown": 0, "same": 0},
               "notice": "", "status_filter": status, "code_filter": code}
    context["pagination"] = paginate_list([], page, per_page)[1]
    repository, ref = config.get("ESTIMATION_VERSION_REPO"), config.get("ESTIMATION_VERSION_REF")
    if config.get("PUBLIC_PORTAL_MODE") or not repository or not ref:
        return context
    context["enabled"] = True
    try:
        reference.update(read_estimation_version_reference(repository, ref))
    except (TypeError, ValueError):
        pass
    context["reference"] = reference
    pinned_config = {**config, "ESTIMATION_VERSION_REF": reference["commit"]}
    try:
        paths = sorted(Path(directory).iterdir())
    except (TypeError, OSError):
        context["notice"] = "Stored Estimates are unavailable."
        return context
    rows, codes = [], set()
    for path in paths:
        if path.suffix != ".json" or path.is_symlink() or not path.is_file():
            continue
        try:
            check_file_permission(path.name, directory)
        except Forbidden:
            continue
        estimate = load_result_json(path.name, directory)
        if not isinstance(estimate, dict):
            context["notice"] = "Some stored records could not be read; this list may be incomplete."
            continue
        app = _text(estimate.get("code"))
        if app:
            codes.add(app)
        if code and app != code:
            continue
        view = (build_estimate_version_check(estimate, pinned_config)
                if reference["commit"] else None)
        if view is None:
            view = {"status": "unknown", "changed_count": 0, "unknown_count": 1}
        metadata = _mapping(estimate.get("estimate_metadata"))
        conditions = []
        for side in ("current_system", "future_system"):
            system = _mapping(estimate.get(side))
            conditions.append(f"{_text(system.get('system')) or 'Unknown'} / nodes {_text(system.get('target_nodes')) or 'Unknown'}")
        detail_url = url_for("estimated.estimated_detail", filename=path.name)
        rows.append({
            "filename": path.name,
            "uuid": _text(metadata.get("estimation_result_uuid")) or "Unknown",
            "source_uuid": _text(metadata.get("source_result_uuid")) or "Unknown",
            "timestamp": _text(metadata.get("estimation_result_timestamp")) or "Unknown",
            "code": app or "Unknown", "exp": _text(estimate.get("exp")) or "Unknown",
            "conditions": " -> ".join(conditions),
            "status": view["status"], "differences": view["changed_count"],
            "unknowns": view["unknown_count"], "detail_url": detail_url,
            "history_url": detail_url + "#estimate-lineage-title",
        })
    context["codes"] = sorted(codes)
    counts = Counter(row["status"] for row in rows)
    context["counts"].update(counts)
    rows.sort(key=lambda row: (row["timestamp"], row["filename"]), reverse=True)
    selected = [row for row in rows if status == "all" or row["status"] == status]
    context["rows"], context["pagination"] = paginate_list(selected, page, per_page)
    return context
