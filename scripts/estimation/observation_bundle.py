"""Application-independent observation bundle paths and publication."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


def valid_member(name):
    if not isinstance(name, str) or '\\' in name:
        return False
    parts = name.split('/')
    return (len(parts) >= 1 and PurePosixPath(name).as_posix() == name
            and all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', part)
                    and part not in ('.', '..') for part in parts)
            and parts[0] not in ('estimation_artifacts',)
            and not (len(parts) == 1 and (re.fullmatch(r'result[0-9]*\.json', name)
                or name.startswith('estimate') or name in ('source_estimate.json',
                    'reestimation_context.json', 'server_result_meta.json'))))


def write_bundle(files, root, archive):
    root, archive = Path(root).resolve(), Path(archive)
    members = {}
    paths = {}
    for file in files:
        file = Path(file)
        if any(p.is_symlink() for p in (file, *file.parents)) or not file.is_file():
            raise ValueError('Unsafe observation bundle input')
        name = file.resolve().relative_to(root).as_posix()
        if not valid_member(name) or name in members:
            raise ValueError('Invalid or duplicate observation bundle member')
        members[name] = hashlib.sha256(file.read_bytes()).hexdigest()
        paths[name] = file
    if not members:
        raise ValueError('Empty observation bundle')
    with tarfile.open(archive, 'w:gz') as tar:
        for name, file in paths.items():
            tar.add(file, arcname=name, recursive=False)
    manifest = dict(schema_version=1, format='benchkit-observation-bundle/v1',
        files=members, summary=dict(bundle=dict(type='file_reference',
            path='results/' + archive.resolve().relative_to(root).as_posix(),
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))
    output = archive.with_suffix('').with_suffix('.json')
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    return str(output)
