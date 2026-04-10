import csv
import os
import re


_DEFAULT_SYSTEM_CSV = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "system.csv"
)
_DEFAULT_PROGRAMS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "programs"
)


def load_registered_systems(system_csv_path=None):
    path = os.path.normpath(system_csv_path or _DEFAULT_SYSTEM_CSV)
    systems = []
    seen = set()

    if not os.path.exists(path):
        return systems

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            system = (row.get("system") or "").strip()
            if system and system not in seen:
                seen.add(system)
                systems.append(system)

    return systems


def _summarize_list_csv(list_csv_path):
    summary = {}

    if not os.path.exists(list_csv_path):
        return summary

    with open(list_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
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


def _file_mentions_system(path, system):
    if not os.path.exists(path):
        return False

    with open(path, encoding="utf-8") as f:
        content = f.read()

    return system in _extract_supported_systems(content, [system])


def _extract_supported_systems(content, candidate_systems):
    candidates = set(candidate_systems)
    supported = set()

    case_start_pattern = re.compile(
        r"""^\s*case\s+(?:"?\$system"?|"?\$\{system\}"?|"?\$1"?)\s+in\s*$"""
    )
    case_end_pattern = re.compile(r"^\s*esac\b")
    label_pattern = re.compile(r"^\s*([A-Za-z0-9_|-]+)\)\s*(?:#.*)?$")

    in_system_case = False
    for line in content.splitlines():
        if not in_system_case:
            if case_start_pattern.match(line):
                in_system_case = True
            continue

        if case_end_pattern.match(line):
            in_system_case = False
            continue

        match = label_pattern.match(line)
        if not match:
            continue

        for token in match.group(1).split("|"):
            token = token.strip()
            if token in candidates:
                supported.add(token)

    for system in candidate_systems:
        exact = re.escape(system)
        if re.search(
            rf"""(?:\$system|\$\{{system\}}|\$1).*?(?:==|=)\s*["']?{exact}["']?""",
            content,
        ) or re.search(
            rf"""["']?{exact}["']?\s*(?:==|=).*?(?:\$system|\$\{{system\}}|\$1)""",
            content,
        ):
            supported.add(system)

    return supported


def load_app_system_support_matrix(programs_dir=None, system_csv_path=None):
    programs_root = os.path.normpath(programs_dir or _DEFAULT_PROGRAMS_DIR)
    registered_systems = load_registered_systems(system_csv_path=system_csv_path)
    matrix_rows = []

    if not os.path.isdir(programs_root):
        return registered_systems, matrix_rows

    for entry in sorted(os.scandir(programs_root), key=lambda e: e.name.lower()):
        if not entry.is_dir():
            continue

        list_csv_path = os.path.join(entry.path, "list.csv")
        build_sh_path = os.path.join(entry.path, "build.sh")
        run_sh_path = os.path.join(entry.path, "run.sh")
        if not os.path.exists(list_csv_path):
            continue

        summary = _summarize_list_csv(list_csv_path)
        systems = {}

        for system in registered_systems:
            item = summary.get(system)
            build_supported = _file_mentions_system(build_sh_path, system)
            run_supported = _file_mentions_system(run_sh_path, system)
            scripts_supported = build_supported and run_supported

            if item and item["enabled_rows"] > 0 and scripts_supported:
                status = "enabled"
            elif item and item["enabled_rows"] > 0:
                status = "enabled_partial"
            elif item:
                status = "configured_off"
            else:
                status = "not_listed"

            systems[system] = {
                "status": status,
                "enabled_rows": item["enabled_rows"] if item else 0,
                "disabled_rows": item["disabled_rows"] if item else 0,
                "build_supported": build_supported,
                "run_supported": run_supported,
            }

        matrix_rows.append({
            "app": entry.name,
            "systems": systems,
        })

    return registered_systems, matrix_rows
