import os
import json
import re
from flask import abort, jsonify, send_from_directory

SAVE_DIR = "received"

def load_result_file(filename: str):
    filepath = os.path.join(SAVE_DIR, filename)
    if not os.path.exists(filepath):
        abort(404)

    if filename.endswith(".json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data)
        except json.JSONDecodeError:
            abort(400, "Invalid JSON")
    else:
        return send_from_directory(SAVE_DIR, filename)


def get_file_confidential_tags(filename: str):
    """
    JSON/TGZのconfidentialタグ取得
    """
    if filename.endswith(".json"):
        return _read_confidential_from_json(filename)

    # tgzの場合、対応するUUIDを含むJSONを探す
    uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", filename, re.IGNORECASE)
    if not uuid_match:
        return []

    uuid = uuid_match.group(0)
    for f in os.listdir(SAVE_DIR):
        if f.endswith(".json") and uuid in f:
            return _read_confidential_from_json(f)
    return []


def _read_confidential_from_json(json_file: str):
    filepath = os.path.join(SAVE_DIR, json_file)
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        c = data.get("confidential")
#        if isinstance(c, list):
#            return [str(x) for x in c if x]
#        elif isinstance(c, str) and c.strip():
#            return [c.strip()]
        if isinstance(c, list):
            return [str(x).strip() for x in c if x and str(x).lower() != "null"]
        elif isinstance(c, str):
            c = c.strip()
            if c and c.lower() != "null":
                return [c]

        return []
    except Exception:
        return []
