import os
import json
import re
from flask import abort, jsonify, send_from_directory, session, Response
from utils.user_store import get_user_store

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
                    mimetype="application/json"
                )
        except json.JSONDecodeError:
            abort(400, "Invalid JSON")
    else:
        abs_dir = os.path.abspath(save_dir)
        return send_from_directory(abs_dir, filename, as_attachment=True)


def get_file_confidential_tags(filename: str, save_dir: str):
    """
    JSON/TGZのconfidentialタグ取得
    """
    if filename.endswith(".json"):
        return _read_confidential_from_json(filename, save_dir)

    # tgzの場合、対応するUUIDを含むJSONを探す
    uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", filename, re.IGNORECASE)
    if not uuid_match:
        return []

    uuid = uuid_match.group(0)
    for f in os.listdir(save_dir):
        if f.endswith(".json") and uuid in f:
            return _read_confidential_from_json(f, save_dir)
    return []


def check_file_permission(filename: str, dir_path: str) -> None:
    """
    ファイルの confidential タグを確認し、アクセス権限がなければ abort(403) する。
    公開ファイル（タグなし）の場合は何もしない。
    """
    tags = get_file_confidential_tags(filename, dir_path)
    if not tags:
        return
    authenticated = session.get("authenticated", False)
    email = session.get("user_email")
    store = get_user_store()
    affs = store.get_affiliations(email) if email else []
    if not authenticated or not (set(tags) & set(affs)):
        abort(403, "You do not have permission to access this file")


def _read_confidential_from_json(json_file: str, save_dir: str):
    filepath = os.path.join(save_dir, json_file)
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # confidential キーがない場合は None と同じ扱いにする
        c = data.get("confidential", None)

        if isinstance(c, list):
            # null や空文字は除外
            return [str(x).strip() for x in c if x and str(x).lower() != "null"]
        elif isinstance(c, str):
            c = c.strip()
            if c.lower() != "null" and c != "":
                return [c]

        # None または null の場合は空リスト
        return []

    except Exception:
        return []
