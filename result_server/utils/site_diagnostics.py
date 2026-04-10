import csv
import os

from utils.app_support_matrix import (
    _DEFAULT_SYSTEM_CSV,
    _DEFAULT_PROGRAMS_DIR,
    load_app_system_support_matrix,
)
from utils.system_info import SYSTEM_INFO_CSV


_DEFAULT_QUEUE_CSV = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "queue.csv"
)


def _read_csv_rows(path):
    if not os.path.exists(path):
        return []

    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_site_diagnostics(
    system_csv_path=None,
    queue_csv_path=None,
    system_info_csv_path=None,
    programs_dir=None,
):
    system_rows = _read_csv_rows(os.path.normpath(system_csv_path or _DEFAULT_SYSTEM_CSV))
    queue_rows = _read_csv_rows(os.path.normpath(queue_csv_path or _DEFAULT_QUEUE_CSV))
    system_info_rows = _read_csv_rows(
        os.path.normpath(system_info_csv_path or SYSTEM_INFO_CSV)
    )

    systems = []
    seen_systems = set()
    for row in system_rows:
        system = (row.get("system") or "").strip()
        if system and system not in seen_systems:
            seen_systems.add(system)
            systems.append(row)

    queue_names = {
        (row.get("queue") or "").strip()
        for row in queue_rows
        if (row.get("queue") or "").strip()
    }
    system_info_names = {
        (row.get("system") or "").strip()
        for row in system_info_rows
        if (row.get("system") or "").strip()
    }

    missing_queue_definitions = []
    missing_system_info = []
    registered_systems = []

    for row in systems:
        system = (row.get("system") or "").strip()
        queue = (row.get("queue") or "").strip()
        registered_systems.append(system)

        if queue and queue not in queue_names:
            missing_queue_definitions.append({
                "system": system,
                "queue": queue,
            })

        if system and system not in system_info_names:
            missing_system_info.append(system)

    coverage_systems, app_support_rows = load_app_system_support_matrix(
        programs_dir=programs_dir or _DEFAULT_PROGRAMS_DIR,
        system_csv_path=system_csv_path or _DEFAULT_SYSTEM_CSV,
    )

    enabled_by_system = {system: 0 for system in coverage_systems}
    partial_support = []

    for row in app_support_rows:
        app = row["app"]
        for system in coverage_systems:
            item = row["systems"].get(system, {})
            status = item.get("status")
            if status == "enabled":
                enabled_by_system[system] += 1
            elif status == "enabled_partial":
                partial_support.append({
                    "app": app,
                    "system": system,
                    "build_supported": item.get("build_supported", False),
                    "run_supported": item.get("run_supported", False),
                    "enabled_rows": item.get("enabled_rows", 0),
                })

    unused_systems = [
        system for system, count in enabled_by_system.items() if count == 0
    ]

    return {
        "registered_system_count": len(registered_systems),
        "application_count": len(app_support_rows),
        "missing_queue_definitions": missing_queue_definitions,
        "missing_system_info": missing_system_info,
        "partial_support": partial_support,
        "unused_systems": unused_systems,
    }
