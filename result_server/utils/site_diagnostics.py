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


def _summarize_list_rows(rows):
    summary = {}
    for row in rows:
        system = (row.get("system") or "").strip()
        if not system:
            continue
        enable = (row.get("enable") or "").strip().lower()
        item = summary.setdefault(system, {"enabled_rows": 0, "disabled_rows": 0})
        if enable == "yes":
            item["enabled_rows"] += 1
        else:
            item["disabled_rows"] += 1
    return summary


def _scan_program_diagnostics(programs_root, registered_systems):
    if not os.path.isdir(programs_root):
        return {
            "application_directory_count": 0,
            "apps_missing_files": [],
            "apps_without_estimate": [],
            "apps_with_estimate_count": 0,
            "unknown_listed_systems": [],
        }

    registered_system_set = set(registered_systems)
    application_directory_count = 0
    apps_missing_files = []
    apps_without_estimate = []
    apps_with_estimate_count = 0
    unknown_listed_systems = []

    for entry in sorted(os.scandir(programs_root), key=lambda e: e.name.lower()):
        if not entry.is_dir():
            continue

        application_directory_count += 1

        required_files = ("list.csv", "build.sh", "run.sh")
        missing_files = [
            filename for filename in required_files
            if not os.path.exists(os.path.join(entry.path, filename))
        ]
        if missing_files:
            apps_missing_files.append({
                "app": entry.name,
                "missing_files": missing_files,
            })

        estimate_path = os.path.join(entry.path, "estimate.sh")
        if os.path.exists(estimate_path):
            apps_with_estimate_count += 1
        else:
            apps_without_estimate.append(entry.name)

        list_rows = _read_csv_rows(os.path.join(entry.path, "list.csv"))
        for system, counts in _summarize_list_rows(list_rows).items():
            if system in registered_system_set:
                continue
            unknown_listed_systems.append({
                "app": entry.name,
                "system": system,
                "enabled_rows": counts["enabled_rows"],
                "disabled_rows": counts["disabled_rows"],
            })

    return {
        "application_directory_count": application_directory_count,
        "apps_missing_files": apps_missing_files,
        "apps_without_estimate": apps_without_estimate,
        "apps_with_estimate_count": apps_with_estimate_count,
        "unknown_listed_systems": unknown_listed_systems,
    }


def build_site_diagnostics(
    system_csv_path=None,
    queue_csv_path=None,
    system_info_csv_path=None,
    programs_dir=None,
):
    programs_root = os.path.normpath(programs_dir or _DEFAULT_PROGRAMS_DIR)
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
        programs_dir=programs_root,
        system_csv_path=system_csv_path or _DEFAULT_SYSTEM_CSV,
    )
    program_diagnostics = _scan_program_diagnostics(programs_root, registered_systems)

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
        "application_directory_count": program_diagnostics["application_directory_count"],
        "apps_missing_files": program_diagnostics["apps_missing_files"],
        "apps_without_estimate": program_diagnostics["apps_without_estimate"],
        "apps_with_estimate_count": program_diagnostics["apps_with_estimate_count"],
        "unknown_listed_systems": program_diagnostics["unknown_listed_systems"],
    }
