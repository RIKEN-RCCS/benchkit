"""
統合データ受信API Blueprint

新パス:
  POST /api/ingest/result   - 結果JSON受信
  POST /api/ingest/estimate - 推定結果JSON受信
  POST /api/ingest/padata   - PA Data (tgz) 受信

互換ルート (deprecated):
  POST /write-api   → ingest_result
  POST /write-est   → ingest_estimate
  POST /upload-tgz  → ingest_padata
"""

from flask import Blueprint, request, abort, current_app, jsonify
import os
import json
import uuid
import shutil
from datetime import datetime

api_bp = Blueprint("api", __name__)

EXPECTED_API_KEY = os.environ.get("RESULT_SERVER_KEY")


# ==========================================
# 共通ユーティリティ
# ==========================================

def require_api_key():
    """APIキー認証"""
    api_key = request.headers.get("X-API-Key")
    if api_key != EXPECTED_API_KEY:
        abort(401, description="Invalid API Key")


def save_json_file(data, prefix, out_dir, given_uuid=None):
    """JSONデータをファイルに保存（アトミック書き込み）"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = given_uuid or str(uuid.uuid4())
    filename = f"{prefix}_{timestamp}_{unique_id}.json"
    path = os.path.join(out_dir, filename)
    tmp_path = path + ".tmp"

    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    os.rename(tmp_path, path)
    print(f"Saved {prefix}: {path}", flush=True)

    return {
        "status": "ok",
        "id": unique_id,
        "timestamp": timestamp,
        "json_file": filename,
    }


def is_valid_uuid(value):
    """UUID形式の検証"""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


# ==========================================
# 新パス: /api/ingest/*
# ==========================================

@api_bp.route("/api/ingest/result", methods=["POST"])
def ingest_result():
    """結果JSON受信"""
    require_api_key()
    data = request.data
    return save_json_file(
        data=data,
        prefix="result",
        out_dir=current_app.config["RECEIVED_DIR"],
    ), 200


@api_bp.route("/api/ingest/estimate", methods=["POST"])
def ingest_estimate():
    """推定結果JSON受信"""
    require_api_key()
    data = request.data
    return save_json_file(
        data=data,
        prefix="estimate",
        out_dir=current_app.config["ESTIMATED_DIR"],
        given_uuid=request.headers.get("X-UUID"),
    ), 200


@api_bp.route("/api/ingest/padata", methods=["POST"])
def ingest_padata():
    """PA Data (tgz) 受信"""
    api_key = request.headers.get("X-API-Key")
    if api_key != EXPECTED_API_KEY:
        abort(401, description="Invalid API Key")

    uuid_str = request.form.get("id")
    if not uuid_str or not is_valid_uuid(uuid_str):
        abort(400, description="Invalid or missing UUID")

    timestamp = request.form.get("timestamp")
    if not timestamp:
        abort(400, description="Missing Timestamp")

    uploaded_file = request.files.get("file")
    if not uploaded_file:
        abort(400, description="No file uploaded")

    received_dir = current_app.config["RECEIVED_DIR"]

    matched_files = [
        f for f in os.listdir(received_dir)
        if f.endswith(".tgz") and uuid_str in f
    ]

    if matched_files:
        old_file_path = os.path.join(received_dir, matched_files[0])
        backup_path = old_file_path + ".bak"
        shutil.move(old_file_path, backup_path)
        save_path = old_file_path
    else:
        save_path = os.path.join(received_dir, f"padata_{timestamp}_{uuid_str}.tgz")

    tmp_path = save_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(uploaded_file.read())
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp_path, save_path)

    print(f"Saved: {save_path}", flush=True)
    return {
        "status": "uploaded",
        "id": uuid_str,
        "timestamp": timestamp,
        "file": os.path.basename(save_path),
        "replaced": bool(matched_files),
    }, 200


# ==========================================
# Query API: /api/query/*
# ==========================================

@api_bp.route("/api/query/result", methods=["GET"])
def query_result():
    """Search results by system, code, exp and return the latest match.

    Query parameters:
      system (required): e.g. Fugaku
      code   (required): e.g. qws
      exp    (optional): e.g. default

    Returns the full JSON of the most recent matching result file.
    """
    require_api_key()

    system = request.args.get("system")
    code = request.args.get("code")
    exp = request.args.get("exp")

    if not system or not code:
        abort(400, description="system and code are required")

    received_dir = current_app.config["RECEIVED_DIR"]
    json_files = sorted(
        [f for f in os.listdir(received_dir) if f.endswith(".json")],
        reverse=True,
    )

    for json_file in json_files:
        try:
            with open(os.path.join(received_dir, json_file), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        if data.get("system") != system:
            continue
        if data.get("code") != code:
            continue
        if exp is not None and data.get("Exp") != exp:
            continue

        return jsonify(data), 200

    abort(404, description=f"No result found for system={system}, code={code}, exp={exp}")


# ==========================================
# 互換ルート (deprecated)
# ==========================================

@api_bp.route("/write-api", methods=["POST"])
def compat_write_api():
    current_app.logger.warning("Deprecated: /write-api → use /api/ingest/result")
    return ingest_result()


@api_bp.route("/write-est", methods=["POST"])
def compat_write_est():
    current_app.logger.warning("Deprecated: /write-est → use /api/ingest/estimate")
    return ingest_estimate()


@api_bp.route("/upload-tgz", methods=["POST"])
def compat_upload_tgz():
    current_app.logger.warning("Deprecated: /upload-tgz → use /api/ingest/padata")
    return ingest_padata()
