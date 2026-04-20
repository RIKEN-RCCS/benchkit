from __future__ import annotations

import json
import os
import re
from typing import Optional

from flask import Response, abort, send_from_directory, session

from utils.session_user_context import get_session_user_context


def load_result_file(filename: str, save_dir: str):
    filepath = os.path.join(save_dir, filename)
    if not os.path.exists(filepath):
        abort(404)

    if filename.endswith(".json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                return Response(
                    json.dumps(data, indent=4, ensure_ascii=False),
                    mimetype="application/json",
                )
        except json.JSONDecodeError:
            abort(400, "Invalid JSON")

    abs_dir = os.path.abspath(save_dir)
    return send_from_directory(abs_dir, filename, as_attachment=True)


def get_file_confidential_tags(filename: str, save_dir: str):
    """Return confidential tags from a JSON file or its matching PA archive."""
    if filename.endswith(".json"):
        return _read_confidential_from_json(filename, save_dir)

    # For TGZ files, find the matching JSON by UUID and reuse its tags.
    uuid_match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        filename,
        re.IGNORECASE,
    )
    if not uuid_match:
        return []

    uuid = uuid_match.group(0)
    for json_filename in os.listdir(save_dir):
        if json_filename.endswith(".json") and uuid in json_filename:
            return _read_confidential_from_json(json_filename, save_dir)
    return []


def check_file_permission(filename: str, dir_path: str) -> None:
    """Abort with 403 when the current session cannot access the file."""
    tags = get_file_confidential_tags(filename, dir_path)
    if not tags:
        return

    user_context = get_session_user_context()
    authenticated = user_context["authenticated"]
    affiliations = user_context["affiliations"]
    if not authenticated or not (set(tags) & set(affiliations)):
        abort(403, "You do not have permission to access this file")


def require_authenticated_session(message: str) -> None:
    """Abort with 403 when the current session is not authenticated."""
    if not session.get("authenticated", False):
        abort(403, message)


def serve_permitted_result_file(filename: str, permission_dir: str, data_dir: Optional[str] = None):
    """Check permission tags and then serve the requested file."""
    check_file_permission(filename, permission_dir)
    return load_result_file(filename, data_dir or permission_dir)


def serve_authenticated_result_file(filename: str, data_dir: str, *, message: str):
    """Require authentication and then serve a file from the given directory."""
    require_authenticated_session(message)
    return serve_permitted_result_file(filename, data_dir)


def load_permitted_result_json(
    filename: str,
    permission_dir: str,
    data_dir: Optional[str] = None,
    *,
    not_found_message: str = "Result file not found",
):
    """Check permission tags and then load JSON content with a custom 404 message."""
    from utils.result_records import load_result_json

    check_file_permission(filename, permission_dir)
    result = load_result_json(filename, data_dir or permission_dir)
    if result is None:
        abort(404, not_found_message)
    return result


def load_authenticated_result_json(
    filename: str,
    data_dir: str,
    *,
    message: str,
    not_found_message: str,
):
    """Require authentication and then load JSON content from the given directory."""
    require_authenticated_session(message)
    return load_permitted_result_json(
        filename,
        data_dir,
        not_found_message=not_found_message,
    )


def _read_confidential_from_json(json_file: str, save_dir: str):
    filepath = os.path.join(save_dir, json_file)
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        confidential_value = data.get("confidential", None)

        if isinstance(confidential_value, list):
            return [
                str(item).strip()
                for item in confidential_value
                if item and str(item).lower() != "null"
            ]

        if isinstance(confidential_value, str):
            confidential_value = confidential_value.strip()
            if confidential_value.lower() != "null" and confidential_value != "":
                return [confidential_value]

        return []
    except Exception:
        return []
