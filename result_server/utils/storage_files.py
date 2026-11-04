"""Logical document/artifact access, with explicit legacy filesystem compatibility."""

import json
import io
import os
from pathlib import Path


def binding(path):
    from utils.profile_storage import configured_store
    store = configured_store()
    if store is None:
        return None
    target = Path(path).absolute()
    for role, root in store.roots.items():
        try:
            name = target.relative_to(root).as_posix()
        except ValueError:
            continue
        return store, role, "" if name == "." else name
    from utils.encrypted_sqlite import EncryptedDatabaseError
    raise EncryptedDatabaseError('Document access is outside the encrypted instance bindings')


def list_names(directory):
    bound = binding(directory)
    if not bound:
        return os.listdir(directory)
    store, role, prefix = bound
    prefix = prefix + "/" if prefix else ""
    return sorted({name[len(prefix):].split("/", 1)[0] for name in store.names(role, prefix)})


def is_file(path):
    bound = binding(path)
    if bound:
        store, role, name = bound
        return bool(name) and store.exists(role, name)
    return os.path.isfile(path) and not os.path.islink(path)


def is_directory(path):
    bound = binding(path)
    if bound:
        store, role, name = bound
        return not name or bool(store.names(role, name + "/"))
    return os.path.isdir(path)


def read_json(path):
    bound = binding(path)
    if bound:
        store, role, name = bound
        return json.loads(store.read(role, name))
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def send_object(path, *, download_name=None, mimetype=None):
    from flask import send_file
    bound = binding(path)
    if not bound:
        return send_file(path, as_attachment=True, download_name=download_name, mimetype=mimetype)
    store, role, name = bound
    # Validation and existence happen before sending the HTTP headers.
    if not store.exists(role, name):
        from flask import abort
        abort(404)
    return stream_download(store.chunks(role, name), download_name or Path(name).name, mimetype=mimetype)


def stream_download(chunks, download_name, *, mimetype=None):
    from flask import send_file
    # Reuse Werkzeug's MIME and RFC 5987 filename handling without a disk file.
    response = send_file(io.BytesIO(), as_attachment=True, download_name=download_name, mimetype=mimetype)
    response.response = chunks
    response.headers.pop('Content-Length', None)
    response.headers["Cache-Control"] = "no-store"
    return response
