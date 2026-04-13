from __future__ import annotations

import json
import os
from datetime import datetime

from utils.node_hours import extract_timestamp_from_filename
from utils.results_loader import summarize_result_quality


def _format_timestamp(filename: str, filepath: str) -> tuple[object, str]:
    ts = extract_timestamp_from_filename(filename)
    if ts is not None:
        return ts, ts.strftime("%Y-%m-%d %H:%M:%S")

    stat = os.stat(filepath)
    ts = datetime.fromtimestamp(stat.st_mtime)
    return ts, ts.strftime("%Y-%m-%d %H:%M:%S")


def _summarize_source_info(data: dict) -> dict:
    source_info = data.get("source_info")
    if not isinstance(source_info, dict) or not source_info:
        return {
            "status": "not tracked",
            "source_type": "—",
            "reference": "—",
            "missing_fields": ["source_info"],
        }

    source_type = source_info.get("source_type") or "unknown"
    if source_type == "git":
        required_fields = ("repo_url", "branch", "commit_hash")
        branch = source_info.get("branch") or ""
        commit_hash = source_info.get("commit_hash") or ""
        short_hash = commit_hash[:7] if commit_hash else ""
        reference = f"{branch}@{short_hash}" if branch and short_hash else branch or short_hash or "git metadata incomplete"
    elif source_type == "file":
        required_fields = ("file_path", "md5sum")
        file_path = source_info.get("file_path") or ""
        md5sum = source_info.get("md5sum") or ""
        short_md5 = md5sum[:8] if md5sum else ""
        basename = os.path.basename(file_path) if file_path else ""
        reference = f"{basename}@{short_md5}" if basename and short_md5 else basename or short_md5 or "file metadata incomplete"
    else:
        required_fields = ()
        reference = "unknown source type"

    missing_fields = [field for field in required_fields if not source_info.get(field)]
    if source_type == "unknown":
        missing_fields = ["source_type"]

    return {
        "status": "top-level source tracked" if not missing_fields else "not tracked",
        "source_type": source_type,
        "reference": reference,
        "missing_fields": missing_fields,
    }


def build_result_quality_rollup(directory: str) -> dict:
    latest = {}

    try:
        files = os.listdir(directory)
    except OSError:
        files = []

    for filename in files:
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        if "FOM" not in data or "system" not in data:
            continue

        app = data.get("code") or "unknown"
        system = data.get("system") or "unknown"
        sort_key, display_timestamp = _format_timestamp(filename, filepath)
        key = (app, system)

        current = latest.get(key)
        if current and current["_sort_key"] >= sort_key:
            continue

        quality = summarize_result_quality(data)
        stats = quality["stats"]
        source_summary = _summarize_source_info(data)
        latest[key] = {
            "_sort_key": sort_key,
            "app": app,
            "system": system,
            "timestamp": display_timestamp,
            "filename": filename,
            "source_tracked": stats["source_info_complete"],
            "source_status": source_summary["status"],
            "source_type": source_summary["source_type"],
            "source_reference": source_summary["reference"],
            "source_missing_fields": source_summary["missing_fields"],
            "breakdown_present": stats["has_breakdown"],
            "estimation_ready": quality["level"] in ("ready", "rich"),
            "rich": quality["level"] == "rich",
            "quality_label": quality["label"],
            "warnings": quality["warnings"],
        }

    rows = []
    for _, row in sorted(latest.items(), key=lambda item: (item[0][0].lower(), item[0][1].lower())):
        row.pop("_sort_key", None)
        rows.append(row)

    return {
        "entry_count": len(rows),
        "rows": rows,
    }
