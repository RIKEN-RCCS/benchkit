from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Set


def compute_node_hours(data: dict) -> float:
    """
    Compute node-hours from a Result JSON record.

    - `cross`: `node_count * run_time / 3600`
    - `native`: `node_count * (build_time + run_time) / 3600`
    - Missing or invalid `node_count` / `run_time` returns `0.0`
    - Missing or invalid `build_time` in native mode falls back to `0.0`
    """
    try:
        node_count = float(data.get("node_count", None))
    except (TypeError, ValueError):
        return 0.0

    pipeline_timing = data.get("pipeline_timing") or {}

    try:
        run_time = float(pipeline_timing.get("run_time", None))
    except (TypeError, ValueError):
        return 0.0

    execution_mode = data.get("execution_mode", "cross")

    if execution_mode == "native":
        try:
            build_time = float(pipeline_timing.get("build_time", None))
        except (TypeError, ValueError):
            build_time = 0.0
        return round(node_count * (build_time + run_time) / 3600, 2)

    return round(node_count * run_time / 3600, 2)


def extract_timestamp_from_filename(filename: str) -> Optional[datetime]:
    """
    Extract a `YYYYMMDD_HHMMSS` timestamp from a result filename.

    This is shared with the results loader so timestamp formatting stays
    consistent across portal pages.
    """
    match = re.search(r"\d{8}_\d{6}", filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def get_fiscal_year(dt: datetime) -> int:
    """Return the Japanese fiscal year for a date."""
    if dt.month <= 3:
        return dt.year - 1
    return dt.year


def get_fiscal_month_index(dt: datetime) -> int:
    """Return the fiscal-month index in the range `0..11`."""
    return (dt.month - 4) % 12


def get_half(dt: datetime) -> str:
    """Return `first` for April-September, otherwise `second`."""
    if 4 <= dt.month <= 9:
        return "first"
    return "second"


def _generate_period_labels(fiscal_year: int, period_type: str) -> List[str]:
    """
    Generate the display labels for the requested aggregation period.

    - `monthly`: `YYYY-MM`
    - `semi_annual`: `H1`, `H2`
    - `fiscal_year`: `FY{year}`
    """
    if period_type == "monthly":
        labels = []
        for i in range(12):
            month = (4 + i - 1) % 12 + 1
            year = fiscal_year if month >= 4 else fiscal_year + 1
            labels.append(f"{year}-{month:02d}")
        return labels
    if period_type == "semi_annual":
        return ["H1", "H2"]
    return [f"FY{fiscal_year}"]


def _get_period_key(dt: datetime, period_type: str) -> Optional[str]:
    """Map a datetime to the corresponding period label."""
    if period_type == "monthly":
        return f"{dt.year}-{dt.month:02d}"
    if period_type == "semi_annual":
        return "H1" if get_half(dt) == "first" else "H2"
    fy = get_fiscal_year(dt)
    return f"FY{fy}"


def aggregate_node_hours(
    directory: str,
    fiscal_year: int,
    period_type: str,
) -> dict:
    """
    Aggregate node-hours from all Result JSON files in a directory.

    Confidential filtering is handled by the admin-only route that calls
    this helper, so this function intentionally aggregates every result
    present in the directory.
    """
    periods = _generate_period_labels(fiscal_year, period_type)

    apps_set: Set[str] = set()
    systems_set: Set[str] = set()
    all_fiscal_years: Set[int] = set()

    table: Dict[str, Dict[str, Dict[str, float]]] = {}

    try:
        files = os.listdir(directory)
    except OSError:
        files = []

    json_files = [filename for filename in files if filename.endswith(".json")]

    for json_file in json_files:
        ts = extract_timestamp_from_filename(json_file)
        if ts is None:
            continue

        file_fy = get_fiscal_year(ts)
        all_fiscal_years.add(file_fy)

        if file_fy != fiscal_year:
            continue

        period_key = _get_period_key(ts, period_type)
        if period_key not in periods:
            continue

        filepath = os.path.join(directory, json_file)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        app = data.get("code", "")
        system = data.get("system", "")
        if not app or not system:
            continue

        node_hours = compute_node_hours(data)

        apps_set.add(app)
        systems_set.add(system)

        if app not in table:
            table[app] = {}
        if system not in table[app]:
            table[app][system] = {}
        table[app][system][period_key] = table[app][system].get(period_key, 0.0) + node_hours

    apps = sorted(apps_set)
    systems = sorted(systems_set)

    for app in apps:
        if app not in table:
            table[app] = {}
        for system in systems:
            if system not in table[app]:
                table[app][system] = {}
            for period in periods:
                if period not in table[app][system]:
                    table[app][system][period] = 0.0

    row_totals: Dict[str, Dict[str, float]] = {}
    for app in apps:
        row_totals[app] = {}
        for period in periods:
            total = sum(table[app][system][period] for system in systems)
            row_totals[app][period] = round(total, 2)

    col_totals: Dict[str, Dict[str, float]] = {}
    for system in systems:
        col_totals[system] = {}
        for period in periods:
            total = sum(table[app][system][period] for app in apps)
            col_totals[system][period] = round(total, 2)

    grand_totals: Dict[str, float] = {}
    for period in periods:
        total = sum(row_totals[app][period] for app in apps)
        grand_totals[period] = round(total, 2)

    for app in apps:
        for system in systems:
            for period in periods:
                table[app][system][period] = round(table[app][system][period], 2)

    available_fiscal_years = sorted(all_fiscal_years)

    return {
        "apps": apps,
        "systems": systems,
        "periods": periods,
        "table": table,
        "row_totals": row_totals,
        "col_totals": col_totals,
        "grand_totals": grand_totals,
        "available_fiscal_years": available_fiscal_years,
    }
