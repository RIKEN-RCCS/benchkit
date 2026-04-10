from __future__ import annotations

import json
import os

from utils.results_loader import summarize_result_quality


def build_result_quality_rollup(directory: str) -> dict:
    rows = {}
    total_results = 0

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
        row = rows.setdefault(
            app,
            {
                "app": app,
                "results": 0,
                "source_tracked": 0,
                "breakdown": 0,
                "estimation_ready": 0,
                "rich": 0,
            },
        )

        quality = summarize_result_quality(data)
        stats = quality["stats"]

        row["results"] += 1
        if stats["source_info_complete"]:
            row["source_tracked"] += 1
        if stats["has_breakdown"]:
            row["breakdown"] += 1
        if quality["level"] in ("ready", "rich"):
            row["estimation_ready"] += 1
        if quality["level"] == "rich":
            row["rich"] += 1

        total_results += 1

    quality_rows = []
    for app in sorted(rows):
        row = rows[app]
        results = row["results"] or 1
        row["source_tracked_pct"] = round(100 * row["source_tracked"] / results)
        row["breakdown_pct"] = round(100 * row["breakdown"] / results)
        row["estimation_ready_pct"] = round(100 * row["estimation_ready"] / results)
        row["rich_pct"] = round(100 * row["rich"] / results)
        quality_rows.append(row)

    return {
        "total_results": total_results,
        "app_count": len(quality_rows),
        "rows": quality_rows,
    }
