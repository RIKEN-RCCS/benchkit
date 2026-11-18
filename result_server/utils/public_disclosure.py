"""Explicit value and archive-member approvals for derived public content."""
import hashlib
import io
import json
from pathlib import PurePosixPath
import tarfile


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                      ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _subset(approved, source):
    if isinstance(approved, dict):
        return isinstance(source, dict) and all(k in source and _subset(v, source[k]) for k, v in approved.items())
    return type(approved) is type(source) and approved == source


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
                        path = PurePosixPath(member.name)
                        if path.is_absolute() or '..' in path.parts or member.name in seen:
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
