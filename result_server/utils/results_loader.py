import os
from math import ceil

from utils.result_file import get_file_confidential_tags
from utils.result_records import load_result_json, load_visible_result_json
from utils.result_table_rows import build_result_table_row


ALLOWED_PER_PAGE = (50, 100, 200)
DEFAULT_PER_PAGE = 100

RESULT_FIELD_MAP = {"system": "system", "code": "code", "exp": "Exp"}
ESTIMATED_FIELD_MAP = {"system": "current_system.system", "code": "code", "exp": "exp"}

RESULT_TABLE_COLUMNS = [
    {"label": "Timestamp", "key": "timestamp", "tooltip": "Date and time when benchmark execution completed and results were automatically submitted to server", "tooltip_class": "tooltip-left"},
    {"label": "CODE", "key": "code"},
    {"label": "Branch/Hash", "key": "source_hash", "tooltip": "Source code branch name and short commit hash (git) or short md5sum (file archive)"},
    {"label": "Exp", "key": "exp", "tooltip": "Experimental conditions (filtered by CODE)"},
    {"label": "FOM", "key": "fom", "tooltip": "Figure of Merit - Benchmark performance metric value, typically elapsed time in seconds for main section"},
    {"label": "FOM version", "key": "fom_version", "tooltip": "Version identifier for the FOM measurement section - helps identify which code region was measured when users modify the timing boundaries"},
    {"label": "SYSTEM", "key": "system", "tooltip": "Computing system name"},
    {"label": "Nodes", "key": "nodes"},
    {"label": "P/N", "key": "numproc_node", "tooltip": "Number of processes per node"},
    {"label": "T/P", "key": "nthreads", "tooltip": "Number of threads per process"},
    {"label": "Profiler / PA", "key": "profile_summary", "tooltip": "Profiler tool, level, report summary, and PA data download access"},
    {"label": "JSON", "key": "json_link", "tooltip": "Detailed benchmark results in JSON format", "tooltip_class": "tooltip-right"},
    {"label": "CI", "key": "ci_summary", "tooltip": "CI trigger source and pipeline ID"},
]


def load_results_table(
    directory,
    public_only=True,
    session_email=None,
    authenticated=False,
    affiliations=None,
    page=1,
    per_page=100,
    filter_system=None,
    filter_code=None,
    filter_exp=None,
    padata_directory=None,
):
    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    affiliations = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_filenames = sorted([filename for filename in files if filename.endswith(".json")], reverse=True)
    padata_dir = padata_directory or directory
    padata_filenames = [filename for filename in os.listdir(padata_dir) if filename.endswith(".tgz")]

    columns = RESULT_TABLE_COLUMNS

    filters_are_active = _filters_are_active(filter_system, filter_code, filter_exp)

    if not filters_are_active:
        visible_filenames = [
            filename
            for filename in json_filenames
            if _is_result_filename_visible(
                filename,
                directory,
                affiliations,
                public_only,
                authenticated,
            )
        ]

        paginated_filenames, pagination_info = paginate_list(visible_filenames, page, per_page)
        rows = []
        for filename in paginated_filenames:
            result_data = load_result_json(filename, directory)
            if result_data is None:
                continue
            rows.append(build_result_table_row(filename, result_data, padata_filenames))

        return rows, columns, pagination_info

    rows = []
    for filename in json_filenames:
        result_data = load_visible_result_json(
            filename,
            directory,
            affiliations,
            public_only,
            authenticated,
        )
        if result_data is None:
            continue
        if not _matches_table_filters(result_data, filter_system, filter_code, filter_exp, field_map=RESULT_FIELD_MAP):
            continue
        rows.append(build_result_table_row(filename, result_data, padata_filenames))

    paginated_rows, pagination_info = paginate_list(rows, page, per_page)
    return paginated_rows, columns, pagination_info


def load_estimated_results_table(
    directory,
    public_only=True,
    session_email=None,
    authenticated=False,
    affiliations=None,
    page=1,
    per_page=100,
    filter_system=None,
    filter_code=None,
    filter_exp=None,
):
    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    affiliations = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_filenames = sorted([filename for filename in files if filename.endswith(".json")], reverse=True)
    filters_are_active = _filters_are_active(filter_system, filter_code, filter_exp)

    rows = []
    for filename in json_filenames:
        result_data = load_visible_result_json(
            filename,
            directory,
            affiliations,
            public_only,
            authenticated,
        )
        if result_data is None:
            continue

        if filters_are_active and not _matches_table_filters(
            result_data,
            filter_system,
            filter_code,
            filter_exp,
            field_map=ESTIMATED_FIELD_MAP,
        ):
            continue

        current = result_data.get("current_system", {})
        future = result_data.get("future_system", {})
        estimate_meta = result_data.get("estimate_metadata", {})
        applicability = result_data.get("applicability", {})

        timestamp = _format_timestamp_from_filename(filename)
        estimate_uuid = estimate_meta.get("estimation_result_uuid") or _extract_uuid_from_filename(filename)

        rows.append({
            "timestamp": estimate_meta.get("estimation_result_timestamp") or timestamp,
            "code": result_data.get("code", ""),
            "exp": result_data.get("exp", ""),
            "systemA_system": current.get("system", ""),
            "systemA_fom": current.get("fom", ""),
            "systemA_target_nodes": current.get("target_nodes", ""),
            "systemA_scaling_method": current.get("scaling_method", ""),
            "systemA_bench_system": current.get("benchmark", {}).get("system", ""),
            "systemA_bench_fom": current.get("benchmark", {}).get("fom", ""),
            "systemA_bench_nodes": current.get("benchmark", {}).get("nodes", ""),
            "systemB_system": future.get("system", ""),
            "systemB_fom": future.get("fom", ""),
            "systemB_target_nodes": future.get("target_nodes", ""),
            "systemB_scaling_method": future.get("scaling_method", ""),
            "systemB_bench_system": future.get("benchmark", {}).get("system", ""),
            "systemB_bench_fom": future.get("benchmark", {}).get("fom", ""),
            "systemB_bench_nodes": future.get("benchmark", {}).get("nodes", ""),
            "applicability_status": applicability.get("status", ""),
            "requested_estimation_package": estimate_meta.get("requested_estimation_package", ""),
            "estimation_package": estimate_meta.get("estimation_package", ""),
            "method_class": estimate_meta.get("method_class", ""),
            "detail_level": estimate_meta.get("detail_level", ""),
            "current_estimation_package": estimate_meta.get("current_package", {}).get("estimation_package", ""),
            "future_estimation_package": estimate_meta.get("future_package", {}).get("estimation_package", ""),
            "requested_current_estimation_package": estimate_meta.get("current_package", {}).get("requested_estimation_package", ""),
            "requested_future_estimation_package": estimate_meta.get("future_package", {}).get("requested_estimation_package", ""),
            "estimate_uuid": estimate_uuid or "",
            "performance_ratio": result_data.get("performance_ratio", ""),
            "json_link": filename,
        })

    columns = [
        ("Timestamp", "timestamp"),
        ("CODE", "code"),
        ("Exp", "exp"),
        ("A System", "systemA_system"),
        ("A FOM", "systemA_fom"),
        ("A Target Nodes", "systemA_target_nodes"),
        ("A Scaling Method", "systemA_scaling_method"),
        ("A Bench System", "systemA_bench_system"),
        ("A Bench FOM", "systemA_bench_fom"),
        ("A Bench Nodes", "systemA_bench_nodes"),
        ("B System", "systemB_system"),
        ("B FOM", "systemB_fom"),
        ("B Target Nodes", "systemB_target_nodes"),
        ("B Scaling Method", "systemB_scaling_method"),
        ("B Bench System", "systemB_bench_system"),
        ("B Bench FOM", "systemB_bench_fom"),
        ("B Bench Nodes", "systemB_bench_nodes"),
        ("Applicability", "applicability_status"),
        ("Requested Package", "requested_estimation_package"),
        ("Applied Package", "estimation_package"),
        ("Estimate UUID", "estimate_uuid"),
        ("Performance Ratio", "performance_ratio"),
        ("JSON", "json_link"),
    ]

    paginated_rows, pagination_info = paginate_list(rows, page, per_page)
    return paginated_rows, columns, pagination_info


def get_filter_options(
    directory,
    public_only=True,
    authenticated=False,
    affiliations=None,
    field_map=None,
    filter_code=None,
):
    if field_map is None:
        field_map = RESULT_FIELD_MAP

    affiliations = affiliations if affiliations is not None else []
    systems = set()
    codes = set()
    experiments = set()

    try:
        files = os.listdir(directory)
    except OSError:
        return {"systems": [], "codes": [], "exps": []}

    for filename in [name for name in files if name.endswith(".json")]:
        result_data = load_visible_result_json(
            filename,
            directory,
            affiliations,
            public_only,
            authenticated,
        )
        if result_data is None:
            continue

        system = _get_nested_field(result_data, field_map["system"])
        if system and system != "N/A":
            systems.add(system)

        code = _get_nested_field(result_data, field_map["code"])
        if code and code != "N/A":
            codes.add(code)

        exp = _get_nested_field(result_data, field_map["exp"])
        if exp and exp != "N/A":
            if not filter_code or _get_nested_field(result_data, field_map["code"]) == filter_code:
                experiments.add(exp)

    return {
        "systems": sorted(systems),
        "codes": sorted(codes),
        "exps": sorted(experiments),
    }


def paginate_list(items, page, per_page):
    total = len(items)
    total_pages = max(1, ceil(total / per_page)) if total > 0 else 1

    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = items[start:end]

    pagination_info = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }
    return paginated_items, pagination_info


def _is_result_filename_visible(filename, directory, affiliations, public_only, authenticated):
    tags = get_file_confidential_tags(filename, directory)
    if public_only and tags:
        return False
    if tags and not authenticated:
        return False
    if tags and "admin" not in affiliations:
        if not affiliations or not (set(tags) & set(affiliations)):
            return False
    return True


def _filters_are_active(filter_system, filter_code, filter_exp):
    return any(value is not None for value in (filter_system, filter_code, filter_exp))


def _get_nested_field(data, field_path):
    keys = field_path.split(".")
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def _matches_table_filters(data, filter_system, filter_code, filter_exp, field_map=None):
    if field_map is None:
        field_map = RESULT_FIELD_MAP

    if filter_system is not None and _get_nested_field(data, field_map["system"]) != filter_system:
        return False
    if filter_code is not None and _get_nested_field(data, field_map["code"]) != filter_code:
        return False
    if filter_exp is not None and _get_nested_field(data, field_map["exp"]) != filter_exp:
        return False
    return True


def _format_timestamp_from_filename(filename):
    import re
    from datetime import datetime

    match = re.search(r"\d{8}_\d{6}", filename)
    if not match:
        return "Unknown"

    try:
        ts = datetime.strptime(match.group(), "%Y%m%d_%H%M%S")
    except Exception:
        return "Unknown"
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _extract_uuid_from_filename(filename):
    import re

    uuid_match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        filename,
        re.IGNORECASE,
    )
    return uuid_match.group(0) if uuid_match else None
