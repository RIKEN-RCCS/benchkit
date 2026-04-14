import os
from math import ceil

from utils.result_file import get_file_confidential_tags
from utils.estimated_table_rows import build_estimated_table_columns, build_estimated_table_row
from utils.result_records import (
    extract_result_uuid,
    format_result_timestamp,
    load_result_json,
    load_visible_result_json,
)
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

        timestamp = format_result_timestamp(filename)
        estimate_uuid = extract_result_uuid(filename)
        rows.append(
            build_estimated_table_row(
                filename,
                result_data,
                fallback_uuid=estimate_uuid,
                fallback_timestamp=timestamp,
            )
        )

    columns = build_estimated_table_columns()

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
