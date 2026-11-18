"""Explicit public export, built from a private snapshot by a trusted publisher."""
import json
import os
from pathlib import Path
import time

# Only fields already consumed by the public Result views are exported.
SCALARS = ('system', 'code', 'Exp', 'FOM', 'FOM_unit', 'FOM_version',
           'node_count', 'numproc_node', 'nthreads', 'cpus_per_node',
           '_server_uuid', '_server_timestamp', 'execution_backend', 'execution_activity')
PROFILE = ('tool', 'level', 'report_format', 'run_count', 'events', 'ncu_options', 'report_kinds')


def select_fields(value, fields):
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in fields if key in value}


def public_document(value):
    """Exclude confidential documents and unknown fields, including nested ones."""
    from utils.result_file import _extract_confidential_tags
    if not isinstance(value, dict) or _extract_confidential_tags(value):
        return None
    result = select_fields(value, SCALARS)
    # Reject object-valued scalar fields instead of publishing arbitrary metadata.
    result = {key: item for key, item in result.items()
              if item is None or isinstance(item, (str, int, float, bool))}
    profile = select_fields(value.get('profile_data'), PROFILE)
    profile = {key: item for key, item in profile.items()
               if isinstance(item, (str, int, float, bool)) or
               (isinstance(item, list) and all(isinstance(x, str) for x in item))}
    if profile:
        result['profile_data'] = profile
    metrics = value.get('metrics')
    if isinstance(metrics, dict):
        public_metrics = {}
        scalar = metrics.get('scalar')
        if isinstance(scalar, dict):
            public_metrics['scalar'] = {key: item for key, item in scalar.items()
                                        if isinstance(item, (int, float)) and not isinstance(item, bool)}
        vector = metrics.get('vector')
        if isinstance(vector, dict):
            clean = {}
            for axis in ('x_axis', 'y_axis'):
                fields = select_fields(vector.get(axis), ('name', 'unit'))
                clean[axis] = {key: item for key, item in fields.items() if isinstance(item, str)}
            table = vector.get('table')
            if isinstance(table, dict):
                columns, rows = table.get('columns'), table.get('rows')
                if (isinstance(columns, list) and all(isinstance(x, str) for x in columns)
                        and isinstance(rows, list) and all(isinstance(row, list) and
                        all(isinstance(x, (str, int, float)) or x is None for x in row) for row in rows)):
                    clean['table'] = {'columns': columns, 'rows': rows}
            public_metrics['vector'] = clean
        if public_metrics:
            result['metrics'] = public_metrics
    build = value.get('build')
    if isinstance(build, dict):
        clean_build = select_fields(build, ('tool',))
        clean_build = {key: item for key, item in clean_build.items() if isinstance(item, str)}
        spack = build.get('spack')
        if isinstance(spack, dict):
            clean_spack = {}
            for label in ('compiler', 'mpi'):
                clean_spack[label] = {key: item for key, item in
                                     select_fields(spack.get(label), ('name', 'version')).items()
                                     if isinstance(item, str)}
            clean_spack['packages'] = [{key: item for key, item in select_fields(pkg, ('name', 'version')).items()
                                        if isinstance(item, str)} for pkg in spack.get('packages', [])
                                       if isinstance(pkg, dict)] if isinstance(spack.get('packages', []), list) else []
            clean_build['spack'] = clean_spack
        result['build'] = clean_build
    source = select_fields(value.get('source_info'),
                           ('source_type', 'ref_name', 'branch', 'resolved_commit', 'commit_hash', 'sha256sum', 'md5sum'))
    if source:
        result['source_info'] = {key: item for key, item in source.items() if isinstance(item, str)}
    breakdown = value.get('fom_breakdown')
    if isinstance(breakdown, dict):
        clean_breakdown = {}
        for collection in ('sections', 'overlaps'):
            items = breakdown.get(collection)
            if not isinstance(items, list):
                continue
            clean_items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                clean_item = {'name': item.get('name')} if isinstance(item.get('name'), str) else {}
                artifacts = item.get('artifacts')
                if isinstance(artifacts, list):
                    clean_item['artifacts'] = [{'type':'file_reference', 'path': artifact['path']}
                        for artifact in artifacts if isinstance(artifact, dict) and
                        artifact.get('type') == 'file_reference' and isinstance(artifact.get('path'), str)]
                clean_items.append(clean_item)
            clean_breakdown[collection] = clean_items
        result['fom_breakdown'] = clean_breakdown
    # Activity is displayed publicly, while allocation/runner metadata is private.
    from utils.result_table_rows import _extract_result_activity
    activity = _extract_result_activity(value)
    if activity:
        result['environment_snapshot'] = {'summary': {'activity': activity}}
    return result


def archive_visibility(documents):
    """Match the existing filename/declared-UUID rule within one immutable snapshot."""
    from utils.result_file import UUID_PATTERN, _extract_confidential_tags
    import re
    overlapping = re.compile('(?=(' + UUID_PATTERN.pattern + '))', UUID_PATTERN.flags)
    visibility = {}
    for name, document in documents:
        if not isinstance(document, dict):
            continue
        identities = {match.group(1).lower() for match in overlapping.finditer(name)}
        declared = document.get('_server_uuid')
        if declared is not None:
            identities.add(str(declared).lower())
        allowed = not _extract_confidential_tags(document)
        for identifier in identities:
            visibility[identifier] = visibility.get(identifier, True) and allowed
    return visibility


def export_public(store, destination, *, policy=None, maximum_bytes=256 * 1024 * 1024, published_path=None):
    """New generation only. Caller publishes it only after successful validation."""
    from utils.result_catalog import ResultCatalog
    from utils.result_file import PUBLIC_PADATA_FILENAME_RE, UUID_PATTERN, _extract_confidential_tags
    from flask import Flask
    root = Path(destination)
    root.mkdir(mode=0o700)
    for name in ('received', 'estimated_results', 'received_padata', 'received_estimation_artifacts', 'index'):
        (root / name).mkdir(mode=0o700)
    from .public_disclosure import AutomaticDisclosure, DisclosurePolicy
    policy = policy or DisclosurePolicy()
    automatic = isinstance(policy, AutomaticDisclosure)

    used = 0
    count = 0
    artifact_count = 0
    # A single SQL transaction fixes visibility and bytes for the entire export.
    from utils.document_snapshot import document_snapshot
    app = Flask(__name__)
    app.extensions['cx_persistence'] = store
    with app.app_context(), document_snapshot(store) as snapshot:
        archive_access = archive_visibility((name, snapshot.read_json('results', name))
                                           for name in snapshot.names('results'))
        for name in snapshot.names('results'):
            document = snapshot.read_json('results', name)
            value = public_document(document)
            value = policy.document(name, document, value)
            if value is None:
                continue
            if automatic:
                references = []
                for artifact, (basename, rule) in policy.artifact_rules(document).items():
                    if not archive_access.get(document.get('_server_uuid', '').lower(), False):
                        continue
                    if not PUBLIC_PADATA_FILENAME_RE.fullmatch(artifact) or not snapshot.exists('artifacts', artifact):
                        continue
                    payload = bytearray()
                    for chunk in store.chunks('artifacts', artifact, conn=snapshot.conn):
                        payload.extend(chunk)
                        if len(payload) > min(maximum_bytes - used, 16 * 1024 * 1024):
                            break
                    else:
                        selected = policy.numeric_archive(bytes(payload), rule, maximum_bytes - used)
                        if selected is not None:
                            target = root / 'received_padata' / artifact
                            if not target.exists():
                                target.write_bytes(selected)
                                used += len(selected)
                                artifact_count += 1
                            references.append({'type':'file_reference', 'path':'results/' + basename})
                if references:
                    value['fom_breakdown'] = {'sections':[{'name':'Profile', 'artifacts':references}]}
            store._name(name)
            encoded = json.dumps(value, ensure_ascii=True, allow_nan=False).encode()
            used += len(encoded)
            if used > maximum_bytes:
                raise ValueError('Export exceeds budget')
            (root / 'received' / name).write_bytes(encoded)
            count += 1
        archives = [] if automatic else snapshot.names('artifacts')
        for name in archives:
            if name not in policy.archives:
                continue
            identifier = UUID_PATTERN.search(name)
            if (PUBLIC_PADATA_FILENAME_RE.fullmatch(name) and identifier is not None
                    and archive_access.get(identifier.group(0).lower(), False)):
                payload = bytearray()
                for chunk in store.chunks('artifacts', name, conn=snapshot.conn):
                    payload.extend(chunk)
                    if len(payload) > maximum_bytes:
                        raise ValueError('Archive exceeds budget')
                selected = policy.archive(name, bytes(payload), maximum_bytes=maximum_bytes-used)
                if selected is not None:
                    used += len(selected)
                    (root / 'received_padata' / name).write_bytes(selected)
                    artifact_count += 1
    # Build the derived index in memory so it cannot exceed the disk budget.
    import sqlite3
    from contextlib import contextmanager
    class MemoryCatalog(ResultCatalog):
        @contextmanager
        def _lock(self):
            yield
        @contextmanager
        def _connect(self, readonly=False, *, upgrading=False):
            yield self.connection
    catalog = MemoryCatalog(root / 'index/catalog.sqlite3', root / 'received',
                            artifact_directory=root / 'received_padata')
    connection = sqlite3.connect(':memory:')
    try:
        connection.row_factory = sqlite3.Row
        catalog.connection = connection
        catalog.initialize_schema(connection)
        catalog.rebuild()
        if published_path is not None:
            for table in ('catalog_state', 'catalog_sources', 'query_records'):
                connection.execute('UPDATE '+table+' SET directory=replace(directory,?,?)',
                                   (str(root), str(published_path)))
            connection.commit()
        size = connection.execute('PRAGMA page_count').fetchone()[0] * connection.execute('PRAGMA page_size').fetchone()[0]
        # Reserve space for the destination and its rollback journal.
        if used + 2 * size + 4096 > maximum_bytes:
            raise ValueError('Index exceeds export budget')
        with sqlite3.connect(root/'index/catalog.sqlite3') as output:
            connection.backup(output)
    finally:
        connection.close()
    manifest = {'version': 1, 'created_at': time.time(), 'results': count, 'archives': artifact_count}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


def validate_public_environment():
    forbidden = ('RESULT_SERVER_PERSISTENCE_DB', 'RESULT_SERVER_PERSISTENCE_KEY',
                 'RESULT_SERVER_PERSISTENCE_ARTIFACT_DB', 'RESULT_SERVER_KEYS', 'RESULT_SERVER_KEY',
                 'RESULT_SERVER_BUDGET_DB_KEY_FILE', 'RESULT_SERVER_RUNNER_MONITOR_KEY_FILE')
    if any(os.environ.get(key) for key in forbidden):
        raise RuntimeError('Public export service received private bindings')


def install_public_export_guard(app, root):
    from flask import abort, request
    from utils.portal_access import classify_endpoint, ACCESS_PUBLIC, ACCESS_PUBLIC_CONDITIONAL
    root = Path(root)
    app.config.update(EXECUTION_PROFILE_DB_PATH=None, SESSION_COOKIE_NAME='cx_public_view')

    def guard():
        if request.method not in ('GET', 'HEAD') or classify_endpoint(request.endpoint or '') not in (
                ACCESS_PUBLIC, ACCESS_PUBLIC_CONDITIONAL):
            abort(404)
        try:
            manifest = json.loads((root / 'manifest.json').read_text())
            age = time.time() - request.environ.get('cx.public.checked_at', manifest['created_at'])
            if manifest['version'] != 1 or not -30 <= age <= 300:
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError):
            abort(503, description='Public export unavailable or expired')
    app.before_request_funcs.setdefault(None, []).insert(0, guard)


def create_ingest_app():
    """Trusted writer backend for existing API URLs, excluded from public Web."""
    from app import create_instance_app
    from flask import abort, request
    from utils.portal_access import classify_endpoint, ACCESS_RUNNER_API
    application = create_instance_app('public')

    def api_only():
        if classify_endpoint(request.endpoint or '') != ACCESS_RUNNER_API:
            abort(404)
    application.before_request_funcs.setdefault(None, []).insert(0, api_only)
    return application
