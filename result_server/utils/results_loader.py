import os

from utils.result_file import get_file_confidential_tags
from utils.estimated_table_rows import build_estimated_table_columns, build_estimated_table_row
from utils.result_records import (
    extract_result_uuid,
    format_result_timestamp,
    load_result_json,
    load_visible_result_json,
)
from utils.result_table_rows import build_result_table_row
from utils.table_filters import filters_are_active, matches_table_filters
from utils.table_pagination import DEFAULT_PER_PAGE, normalize_per_page, paginate_list

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
    authenticated=False,
    affiliations=None,
    page=1,
    per_page=100,
    filter_system=None,
    filter_code=None,
    filter_exp=None,
    padata_directory=None,
):
    per_page = normalize_per_page(per_page)

    affiliations = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_filenames = sorted([filename for filename in files if filename.endswith(".json")], reverse=True)
    padata_dir = padata_directory or directory
    padata_filenames = [filename for filename in os.listdir(padata_dir) if filename.endswith(".tgz")]

    columns = RESULT_TABLE_COLUMNS

    has_filters = filters_are_active(filter_system, filter_code, filter_exp)

    if not has_filters:
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
        if not matches_table_filters(
            result_data,
            filter_system,
            filter_code,
            filter_exp,
            field_map=RESULT_FIELD_MAP,
        ):
            continue
        rows.append(build_result_table_row(filename, result_data, padata_filenames))

    paginated_rows, pagination_info = paginate_list(rows, page, per_page)
    return paginated_rows, columns, pagination_info


def load_estimated_results_table(
    directory,
    public_only=True,
    authenticated=False,
    affiliations=None,
    page=1,
    per_page=100,
    filter_system=None,
    filter_code=None,
    filter_exp=None,
):
    per_page = normalize_per_page(per_page)

    affiliations = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_filenames = sorted([filename for filename in files if filename.endswith(".json")], reverse=True)
    has_filters = filters_are_active(filter_system, filter_code, filter_exp)

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

        if has_filters and not matches_table_filters(
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
