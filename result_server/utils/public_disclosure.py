"""Explicit value and archive-member approvals for derived public content."""
import hashlib
import io
import json
import math
from pathlib import PurePosixPath
import tarfile


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _subset(approved, source):
    if isinstance(approved, dict):
        return isinstance(source, dict) and all(k in source and _subset(v, source[k]) for k, v in approved.items())
    return type(approved) is type(source) and approved == source


def _safe_member_name(name):
    if not isinstance(name, str) or not name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and '..' not in path.parts


class DisclosurePolicy:
    """Approvals name exact source versions and exact values or member bytes."""
    maximum_input_bytes = 256 * 1024 * 1024
    def __init__(self, documents=None, archives=None):
        self.documents = json.loads(json.dumps(documents or {}, allow_nan=False))
        self.archives = json.loads(json.dumps(archives or {}, allow_nan=False))

    def document(self, name, source, projected):
        approval = self.documents.get(name)
        if not approval or approval.get('source_sha256') != digest(source):
            return None
        value = approval.get('value')
        if not isinstance(value, dict) or not _subset(value, projected):
            return None
        return json.loads(json.dumps(value, allow_nan=False))

    def archive(self, name, payload, *, maximum_bytes):
        if maximum_bytes <= 0:
            return None
        approval = self.archives.get(name)
        if not approval or hashlib.sha256(payload).hexdigest() != approval.get('source_sha256'):
            return None
        selected = approval.get('members', {})
        if not selected or len(selected) > 256:
            return None
        output = io.BytesIO()
        seen = set()
        total = 0
        expanded = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as source:
                with tarfile.open(fileobj=output, mode='w:gz') as target:
                    for member in source:
                        expanded += member.size
                        if expanded > self.maximum_input_bytes:
                            raise ValueError('Archive expansion exceeds budget')
                        if not _safe_member_name(member.name) or member.name in seen:
                            raise ValueError('Unsafe archive')
                        seen.add(member.name)
                        if len(seen) > 4096:
                            raise ValueError('Too many archive members')
                        if member.name not in selected:
                            continue
                        if not member.isfile() or member.size > maximum_bytes:
                            raise ValueError('Unsupported selected member')
                        total += member.size
                        if total > maximum_bytes:
                            raise ValueError('Selected archive exceeds budget')
                        with source.extractfile(member) as stream:
                            data = stream.read(maximum_bytes + 1)
                        if len(data) != member.size or hashlib.sha256(data).hexdigest() != selected[member.name]:
                            raise ValueError('Member approval differs')
                        clean = tarfile.TarInfo(member.name)
                        clean.size = len(data)
                        clean.mode = 0o644
                        target.addfile(clean, io.BytesIO(data))
            if not set(selected) <= seen or len(output.getvalue()) > maximum_bytes:
                return None
            return output.getvalue()
        except (tarfile.TarError, OSError, ValueError, EOFError):
            return None


class AutomaticDisclosure:
    """Administrator-defined rules by benchmark, independent of individual Results."""
    maximum_input_bytes = DisclosurePolicy.maximum_input_bytes

    def __init__(self, benchmarks):
        self.benchmarks = benchmarks

    def document(self, name, source, projected):
        import re
        if projected is None or not isinstance(source.get('confidential'), (type(None), str, list)):
            return None
        code = projected.get('code')
        rules = self.benchmarks.get(code, {})
        fields = ('system', 'code', 'Exp', 'FOM', 'FOM_unit', 'FOM_version',
                  'node_count', 'numproc_node', 'nthreads', 'cpus_per_node',
                  '_server_uuid', '_server_timestamp')
        result = {key: projected[key] for key in fields if key in projected}
        fom = result.get('FOM')
        if isinstance(fom, float) and not math.isfinite(fom):
            del result['FOM']
        from utils.result_table_rows import _extract_result_activity
        activity = _extract_result_activity(source) or source.get('execution_activity')
        if isinstance(activity, str) and activity:
            result['environment_snapshot'] = {'summary': {'activity': activity}}
        info = projected.get('source_info', {})
        raw_info = source.get('source_info')
        if isinstance(raw_info, dict) and raw_info.get('repo_url') in rules.get('public_repositories', []):
            ref = info.get('ref_name') or info.get('branch')
            commit = info.get('resolved_commit') or info.get('commit_hash', '')
            if ref in rules.get('refs', []) and re.fullmatch('[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', commit):
                result['source_info'] = {'source_type':'git', 'ref_name':ref, 'resolved_commit':commit[:7]}
        if info.get('source_type') == 'file':
            for algorithm, length in (('sha256sum', 12), ('md5sum', 8)):
                checksum = info.get(algorithm)
                if checksum and checksum in rules.get('public_checksums', []):
                    result['source_info'] = {'source_type':'file', algorithm:checksum[:length]}
                    break
        profile = projected.get('profile_data', {})
        public_profile = {}
        for key, allowed in rules.get('profile', {}).items():
            value = profile.get(key)
            if isinstance(value, list):
                values = [item for item in value if item in allowed]
                if values:
                    public_profile[key] = values
            elif value in allowed:
                public_profile[key] = value
        if type(profile.get('run_count')) is int:
            public_profile['run_count'] = profile['run_count']
        if public_profile:
            result['profile_data'] = public_profile
        build = projected.get('build', {})
        public_build = {}
        if build.get('tool') in rules.get('build_tools', []):
            public_build['tool'] = build['tool']
        spack = build.get('spack', {})
        selected = {}
        for role in ('compiler', 'mpi', 'packages'):
            candidates = spack.get(role, []) if role == 'packages' else [spack.get(role, {})]
            values = [entry for entry in candidates if entry.get('name') in rules.get(role, {})
                      and entry.get('version') in rules[role][entry['name']]]
            if values:
                selected[role] = values if role == 'packages' else values[0]
        if selected:
            public_build['spack'] = selected
        if public_build:
            result['build'] = public_build
        metrics = projected.get('metrics', {})
        scalar = {k:v for k,v in metrics.get('scalar', {}).items()
                  if k in rules.get('scalar_metrics', []) and
                  (type(v) is int or (type(v) is float and math.isfinite(v)))}
        if scalar:
            result['metrics'] = {'scalar':scalar}
        vector = metrics.get('vector', {})
        table = vector.get('table', {})
        layout = rules.get('vector_layout')
        if layout and all(vector.get(k) == layout.get(k) for k in ('x_axis', 'y_axis')) and (
                table.get('columns') == layout['columns'] and all(
                    len(row) == len(layout['columns']) and all(
                        type(v) is int or (type(v) is float and math.isfinite(v)) for v in row)
                    for row in table.get('rows', []))):
            result.setdefault('metrics', {})['vector'] = vector
        return result

    def artifact_rules(self, source):
        from utils.measurement_artifacts import measurement_artifact_basename_from_path, stored_measurement_artifact_filename
        if not all(isinstance(source.get(k), str) for k in ('code', '_server_uuid', '_server_timestamp')):
            return {}
        configured = self.benchmarks.get(source['code'], {}).get('pa', {})
        found = {}
        breakdown = source.get('fom_breakdown') or {}
        for group in ('sections', 'overlaps'):
            for section in breakdown.get(group, []):
                for item in section.get('artifacts', []):
                    if item.get('type') != 'file_reference':
                        continue
                    basename = measurement_artifact_basename_from_path(item.get('path'))
                    if basename in configured:
                        name = stored_measurement_artifact_filename(source['_server_timestamp'], source['_server_uuid'], basename)
                        found[name] = (basename, configured[basename])
        return found

    def numeric_archive(self, payload, rule, maximum_bytes):
        """Publish only registered CSV columns containing finite numeric measurements."""
        import csv
        member_name = rule.get('member')
        if not _safe_member_name(member_name):
            return None
        columns = rule['columns']
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
                data = None
                expanded = 0
                for index, member in enumerate(archive):
                    expanded += member.size
                    if index >= 256 or expanded > min(maximum_bytes, 16 * 1024 * 1024):
                        return None
                    if member.name != member_name:
                        continue
                    if data is not None or not member.isreg() or not 0 < member.size <= 1024 * 1024:
                        return None
                    data = archive.extractfile(member).read()
            if data is None:
                return None
            rows = csv.DictReader(io.StringIO(data.decode('utf-8')), strict=True)
            headers = rows.fieldnames or []
            if len(headers) != len(set(headers)) or not set(columns) <= set(headers):
                return None
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(columns)
            for row in rows:
                numbers = [float(row[k]) for k in columns]
                if not all(map(math.isfinite, numbers)):
                    return None
                writer.writerow(numbers)
            content = output.getvalue().encode()
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode='w:gz') as dest:
                info = tarfile.TarInfo(member_name)
                info.size = len(content)
                dest.addfile(info, io.BytesIO(content))
            result = buf.getvalue()
            return result if len(result) <= maximum_bytes else None
        except (ValueError, OSError, EOFError, tarfile.TarError, csv.Error, TypeError):
            return None
