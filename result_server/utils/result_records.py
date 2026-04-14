import json
import os
import re
from datetime import datetime

from utils.result_file import get_file_confidential_tags


def load_visible_result_json(
    filename,
    directory,
    affiliations=None,
    public_only=True,
    authenticated=False,
):
    """Load a result JSON file after applying confidentiality checks."""
    affiliations = affiliations or []

    tags = get_file_confidential_tags(filename, directory)
    if public_only and tags:
        return None
    if tags and not authenticated:
        return None
    if tags and "admin" not in affiliations:
        if not affiliations or not (set(tags) & set(affiliations)):
            return None

    return load_result_json(filename, directory)


def load_result_json(filename, directory):
    """Load a single JSON file from a result directory."""
    filepath = os.path.join(directory, filename)
    if not os.path.isfile(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def load_result_json_batch(filenames, directory):
    """Load multiple JSON files and keep a display timestamp for compare views."""
    results = []
    for filename in filenames:
        data = load_result_json(filename, directory)
        if data is None:
            continue

        results.append({
            "filename": filename,
            "timestamp": format_result_timestamp(filename),
            "data": data,
        })

    results.sort(key=lambda item: item["timestamp"])
    return results


def summarize_result_quality(data):
    """Summarize how estimation-ready and provenance-rich a result JSON is."""
    warnings = []

    fom = data.get("FOM")
    has_fom = fom not in (None, "", "null", "N/A")

    source_info = data.get("source_info")
    has_source_info = isinstance(source_info, dict) and bool(source_info)
    source_info_complete = False
    if has_source_info:
        source_type = source_info.get("source_type")
        if source_type == "git":
            source_info_complete = all(source_info.get(key) for key in ("repo_url", "branch", "commit_hash"))
        elif source_type == "file":
            source_info_complete = all(source_info.get(key) for key in ("file_path", "md5sum"))
        else:
            warnings.append("source_info has unknown source_type")
    else:
        warnings.append("source_info is missing")

    if has_source_info and not source_info_complete:
        warnings.append("source_info is incomplete")

    fom_breakdown = data.get("fom_breakdown")
    sections = []
    overlaps = []
    if isinstance(fom_breakdown, dict):
        if isinstance(fom_breakdown.get("sections"), list):
            sections = fom_breakdown.get("sections", [])
        if isinstance(fom_breakdown.get("overlaps"), list):
            overlaps = fom_breakdown.get("overlaps", [])

    has_breakdown = bool(sections or overlaps)
    if not has_breakdown:
        warnings.append("fom_breakdown is missing")

    section_names = [section.get("name") for section in sections if isinstance(section, dict) and section.get("name")]
    if len(section_names) != len(set(section_names)):
        warnings.append("duplicate section names found")

    unknown_overlap_refs = 0
    for overlap in overlaps:
        if not isinstance(overlap, dict):
            continue
        members = overlap.get("sections", [])
        if not isinstance(members, list) or not members:
            warnings.append("overlap has no sections")
            continue
        for member in members:
            if member not in section_names:
                unknown_overlap_refs += 1

    if unknown_overlap_refs:
        warnings.append("overlap references undefined sections")

    section_package_count = sum(
        1 for section in sections
        if isinstance(section, dict) and isinstance(section.get("estimation_package"), str) and section.get("estimation_package")
    )
    overlap_package_count = sum(
        1 for overlap in overlaps
        if isinstance(overlap, dict) and isinstance(overlap.get("estimation_package"), str) and overlap.get("estimation_package")
    )
    artifact_count = sum(
        len(item.get("artifacts", []))
        for item in sections + overlaps
        if isinstance(item, dict) and isinstance(item.get("artifacts"), list)
    )

    expected_package_items = len(sections) + len(overlaps)
    actual_package_items = section_package_count + overlap_package_count
    estimation_ready = has_breakdown and expected_package_items > 0 and expected_package_items == actual_package_items
    provenance_rich = estimation_ready and source_info_complete and artifact_count > 0

    if has_breakdown and expected_package_items > actual_package_items:
        warnings.append("some breakdown items are missing estimation_package")

    if provenance_rich:
        level = "rich"
        label = "Rich"
        summary = "Breakdown, estimation bindings, source provenance, and artifacts are present."
    elif estimation_ready:
        level = "ready"
        label = "Ready"
        summary = "Breakdown and estimation bindings are present."
    else:
        level = "basic"
        label = "Basic"
        summary = "Core result fields are present, but estimation-related detail is limited."

    return {
        "level": level,
        "label": label,
        "summary": summary,
        "warnings": warnings,
        "stats": {
            "has_fom": has_fom,
            "has_source_info": has_source_info,
            "source_info_complete": source_info_complete,
            "has_breakdown": has_breakdown,
            "section_count": len(sections),
            "overlap_count": len(overlaps),
            "section_package_count": section_package_count,
            "overlap_package_count": overlap_package_count,
            "artifact_count": artifact_count,
        },
    }


def format_result_timestamp(filename):
    match = re.search(r"\d{8}_\d{6}", filename)
    if not match:
        return "Unknown"

    try:
        ts = datetime.strptime(match.group(), "%Y%m%d_%H%M%S")
    except Exception:
        return "Unknown"
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def extract_result_uuid(filename):
    uuid_match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        filename,
        re.IGNORECASE,
    )
    return uuid_match.group(0) if uuid_match else None


def format_numeric_value(value):
    if value in (None, "", "N/A", "null", "nan"):
        return value
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return value


def split_display_timestamp(value):
    if not value:
        return "", ""
    if " " not in value:
        return value, ""
    return value.split(" ", 1)


def short_identifier(value, length=8):
    return value[:length] if value else ""


def build_multiline_title(base, labeled_values):
    lines = [base] if base else []
    for label, value in labeled_values:
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def build_compare_headline(system, code, count):
    if not system and not code:
        return f"Comparing {count} results"
    return f"{system or '-'} / {code or '-'} - Comparing {count} results"
