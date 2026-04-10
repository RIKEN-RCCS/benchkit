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
        latest[key] = {
            "_sort_key": sort_key,
            "app": app,
            "system": system,
            "timestamp": display_timestamp,
            "filename": filename,
            "source_tracked": stats["source_info_complete"],
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
