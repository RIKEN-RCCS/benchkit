"""Unified ingestion and query API routes for portal data."""

from flask import Blueprint, request, abort, current_app, jsonify, send_file
import os
import json
import re
import uuid
import shutil
import io
import tarfile
from datetime import datetime

api_bp = Blueprint("api", __name__)

EXPECTED_API_KEY = os.environ.get("RESULT_SERVER_KEY")


# ==========================================
# Shared utilities
# ==========================================

def require_api_key():
    """Validate the request API key."""
    api_key = request.headers.get("X-API-Key")
    if api_key != EXPECTED_API_KEY:
        abort(401, description="Invalid API Key")


def save_json_file(data, prefix, out_dir, given_uuid=None):
    """Persist a JSON payload using atomic file replacement."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = given_uuid or str(uuid.uuid4())
    filename = f"{prefix}_{timestamp}_{unique_id}.json"
    path = os.path.join(out_dir, filename)
    tmp_path = path + ".tmp"

    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        abort(400, description="Invalid JSON payload")

    if not isinstance(payload, dict):
        abort(400, description="Top-level JSON object is required")

    if prefix == "result":
        payload["_server_uuid"] = unique_id
        payload["_server_timestamp"] = timestamp
    elif prefix == "estimate":
        estimate_meta = payload.get("estimate_metadata")
        if not isinstance(estimate_meta, dict):
            estimate_meta = {}
        estimate_meta["estimation_result_uuid"] = unique_id
        estimate_meta["estimation_result_timestamp"] = datetime.strptime(
            timestamp, "%Y%m%d_%H%M%S"
        ).strftime("%Y-%m-%d %H:%M:%S")
        payload["estimate_metadata"] = estimate_meta

    serialized = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    with open(tmp_path, "wb") as f:
        f.write(serialized)
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
    """Return whether the given string is a valid UUID."""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _load_json_by_uuid(directory, field_path, uuid_value):
    """Return the first JSON payload whose target field matches the UUID."""
    json_files = sorted(
        [f for f in os.listdir(directory) if f.endswith(".json")],
        reverse=True,
    )

    for json_file in json_files:
        path = os.path.join(directory, json_file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        current = data
        for key in field_path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)

        if current == uuid_value:
            return data

        # Compatibility fallback: also match UUIDs embedded in filenames.
        if uuid_value in json_file:
            return data

    return None


def _find_result_file_by_uuid(received_dir, uuid_value):
    json_files = sorted(
        [f for f in os.listdir(received_dir) if f.endswith(".json")],
        reverse=True,
    )

    for json_file in json_files:
        path = os.path.join(received_dir, json_file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        if data.get("_server_uuid") == uuid_value or uuid_value in json_file:
            return json_file, path, data

    return None, None, None


def _safe_extract_tar_bytes(file_storage, target_dir):
    with tarfile.open(fileobj=file_storage.stream, mode="r:*") as tar:
        for member in tar.getmembers():
            normalized = os.path.normpath(member.name)
            if os.path.isabs(normalized) or normalized.startswith(".."):
                abort(400, description="Unsafe archive entry")
        try:
            tar.extractall(target_dir, filter="data")
        except TypeError:
            tar.extractall(target_dir)


# ==========================================
# Ingestion routes: /api/ingest/*
# ==========================================

@api_bp.route("/api/ingest/result", methods=["POST"])
def ingest_result():
    """Receive and persist a collected result JSON payload."""
    require_api_key()
    data = request.data
    return save_json_file(
        data=data,
        prefix="result",
        out_dir=current_app.config["RECEIVED_DIR"],
    ), 200


@api_bp.route("/api/ingest/estimate", methods=["POST"])
def ingest_estimate():
    """Receive and persist an estimated-result JSON payload."""
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
    """Receive and store a PA Data archive."""
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

    received_dir = current_app.config["RECEIVED_PADATA_DIR"]

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


@api_bp.route("/api/ingest/estimation-inputs", methods=["POST"])
def ingest_estimation_inputs():
    """Estimation input archive (tgz) upload and expansion."""
    require_api_key()

    uuid_str = request.form.get("id")
    if not uuid_str or not is_valid_uuid(uuid_str):
        abort(400, description="Invalid or missing UUID")

    uploaded_file = request.files.get("file")
    if not uploaded_file:
        abort(400, description="No file uploaded")

    received_dir = current_app.config["RECEIVED_DIR"]
    result_filename, _, _ = _find_result_file_by_uuid(received_dir, uuid_str)
    if not result_filename:
        abort(404, description=f"No result found for uuid={uuid_str}")

    result_stem = os.path.splitext(result_filename)[0]
    inputs_root = current_app.config["RECEIVED_ESTIMATION_INPUTS_DIR"]
    target_dir = os.path.join(inputs_root, result_stem)
    replaced = os.path.isdir(target_dir)
    if replaced:
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    _safe_extract_tar_bytes(uploaded_file, target_dir)

    print(f"Saved estimation inputs: {target_dir}", flush=True)
    return {
        "status": "uploaded",
        "id": uuid_str,
        "directory": result_stem,
        "replaced": replaced,
    }, 200


# ==========================================
# Query API: /api/query/*
# ==========================================

@api_bp.route("/api/query/result", methods=["GET"])
def query_result():
    """Search results by uuid or by system/code/exp and return one result.

    Query parameters:
      uuid   (optional): result UUID
      system (required unless uuid is specified): e.g. Fugaku
      code   (required unless uuid is specified): e.g. qws
      exp    (optional): e.g. default

    Returns the full JSON of the matching result file.
    """
    require_api_key()

    uuid_value = request.args.get("uuid")
    system = request.args.get("system")
    code = request.args.get("code")
    exp = request.args.get("exp")

    if uuid_value:
        if not is_valid_uuid(uuid_value):
            abort(400, description="Invalid UUID")

        data = _load_json_by_uuid(
            current_app.config["RECEIVED_DIR"],
            ["_server_uuid"],
            uuid_value,
        )
        if data is None:
            abort(404, description=f"No result found for uuid={uuid_value}")
        return jsonify(data), 200

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

        # Add _meta with timestamp and uuid extracted from filename
        ts_match = re.search(r"\d{8}_\d{6}", json_file)
        meta_timestamp = None
        if ts_match:
            try:
                ts = datetime.strptime(ts_match.group(), "%Y%m%d_%H%M%S")
                meta_timestamp = ts.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        uuid_match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            json_file, re.IGNORECASE,
        )
        meta_uuid = uuid_match.group(0) if uuid_match else None

        data["_meta"] = {"timestamp": meta_timestamp, "uuid": meta_uuid}
        return jsonify(data), 200

    abort(404, description=f"No result found for system={system}, code={code}, exp={exp}")


@api_bp.route("/api/query/estimation-inputs", methods=["GET"])
def query_estimation_inputs():
    """Return estimation input artifacts for a result UUID as a tar.gz archive."""
    require_api_key()

    uuid_value = request.args.get("uuid")
    if not uuid_value or not is_valid_uuid(uuid_value):
        abort(400, description="Invalid UUID")

    result_filename, _, _ = _find_result_file_by_uuid(
        current_app.config["RECEIVED_DIR"], uuid_value
    )
    if not result_filename:
        abort(404, description=f"No result found for uuid={uuid_value}")

    result_stem = os.path.splitext(result_filename)[0]
    source_dir = os.path.join(
        current_app.config["RECEIVED_ESTIMATION_INPUTS_DIR"], result_stem
    )
    if not os.path.isdir(source_dir):
        abort(404, description=f"No estimation inputs found for uuid={uuid_value}")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for entry in sorted(os.listdir(source_dir)):
            tar.add(
                os.path.join(source_dir, entry),
                arcname=entry,
            )
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/gzip",
        as_attachment=True,
        download_name=f"estimation_inputs_{result_stem}.tgz",
    )


@api_bp.route("/api/query/estimate", methods=["GET"])
def query_estimate():
    """Return one estimate JSON document identified by UUID."""
    require_api_key()

    uuid_value = request.args.get("uuid")
    if not uuid_value or not is_valid_uuid(uuid_value):
        abort(400, description="Invalid UUID")

    data = _load_json_by_uuid(
        current_app.config["ESTIMATED_DIR"],
        ["estimate_metadata", "estimation_result_uuid"],
        uuid_value,
    )
    if data is None:
        abort(404, description=f"No estimate found for uuid={uuid_value}")

    return jsonify(data), 200


# ==========================================
# Compatibility routes (deprecated)
# ==========================================

@api_bp.route("/write-api", methods=["POST"])
def compat_write_api():
    current_app.logger.warning("Deprecated: /write-api -> use /api/ingest/result")
    return ingest_result()


@api_bp.route("/write-est", methods=["POST"])
def compat_write_est():
    current_app.logger.warning("Deprecated: /write-est -> use /api/ingest/estimate")
    return ingest_estimate()


@api_bp.route("/upload-tgz", methods=["POST"])
def compat_upload_tgz():
    current_app.logger.warning("Deprecated: /upload-tgz -> use /api/ingest/padata")
    return ingest_padata()
