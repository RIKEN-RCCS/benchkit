"""Read one Estimate page and authorized filter options without duplicate document passes."""
from pathlib import Path

from . import estimate_list_index
from .document_snapshot import document_snapshot
from .estimated_table_rows import build_estimated_table_columns, build_estimated_table_row
from .result_catalog import CatalogUnavailable
from .result_file import _extract_confidential_tags
from .result_records import extract_result_uuid, format_result_timestamp, load_result_json
from .storage_files import list_names
from .table_filters import get_nested_field, matches_table_filters
from .table_pagination import paginate_list


def visible(payload, affiliations):
    tags = _extract_confidential_tags(payload)
    return not tags or 'admin' in affiliations or bool(set(tags) & set(affiliations))


def load_estimated_page(directory, *, affiliations, page, per_page,
                        filter_system=None, filter_code=None, filter_exp=None):
    filters = {'system':filter_system,'code':filter_code,'exp':filter_exp}
    with document_snapshot(cache_documents=False) as snapshot:
        indexed = snapshot is not None and estimate_list_index.exists(snapshot.conn)
        if snapshot is not None:
            if str(Path(directory).absolute()) != snapshot.store.roots['estimates']:
                raise CatalogUnavailable('Estimate directory does not match the encrypted instance')
            if indexed:
                names, pagination, options = estimate_list_index.select(snapshot.conn,
                    public_only=False, authenticated=True, affiliations=affiliations,
                    page=page, per_page=per_page, filters=filters)
                records = snapshot.documents('estimates', names)
            else:
                records = snapshot.documents('estimates')
        else:
            records = ((name, load_result_json(name, directory)) for name in
                       sorted(list_names(directory), reverse=True) if name.endswith('.json'))
        rows = []
        if not indexed:
            values = {field:set() for field in estimate_list_index.FIELDS}
        for name, payload in records:
            allowed = isinstance(payload, dict) and visible(payload, affiliations)
            matches = allowed and matches_table_filters(payload, filter_system, filter_code,
                filter_exp, field_map=estimate_list_index.FIELDS)
            if indexed and not matches:
                raise CatalogUnavailable('Selected Estimate changed; rebuild the index')
            if not allowed:
                continue
            if not indexed:
                for field, path in estimate_list_index.FIELDS.items():
                    value = get_nested_field(payload, path)
                    if value and value != 'N/A':
                        values[field].add(value)
            if matches:
                rows.append(build_estimated_table_row(name, payload,
                    fallback_uuid=extract_result_uuid(name), fallback_timestamp=format_result_timestamp(name)))
        if not indexed:
            rows, pagination = paginate_list(rows, page, per_page)
            options = {plural:sorted(values[field]) for field,plural in
                       [('system','systems'),('code','codes'),('exp','exps')]}
        return rows, build_estimated_table_columns(), pagination, options
