import os
import json
import re
from flask import abort, jsonify, send_from_directory, Response

#SAVE_DIR = "received"

#def load_result_file(filename: str, save_dir: str = SAVE_DIR):
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


#def get_file_confidential_tags(filename: str, save_dir: str = SAVE_DIR):
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


def _read_confidential_from_json(json_file: str, save_dir: str):
    filepath = os.path.join(save_dir, json_file)
    #print(f"_read_confidential_from_json:filepath {filepath}", flush=True)    
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            #print(f"_read_confidential_from_json:data {data}", flush=True)

        # confidential キーがない場合は None と同じ扱いにする
        c = data.get("confidential", None)
        #print(f"_read_confidential_from_json:confidential {c}", flush=True)

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
