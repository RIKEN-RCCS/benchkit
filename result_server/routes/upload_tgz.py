from flask import Blueprint, request, abort
import os
import uuid
import shutil

upload_bp = Blueprint("upload", __name__)

EXPECTED_API_KEY = os.environ.get("RESULT_SERVER_KEY")
SAVE_DIR = "received"

@upload_bp.route("/upload-tgz", methods=["POST"])
def upload_tgz():
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

    matched_files = [
        f for f in os.listdir(SAVE_DIR)
        if f.endswith(".tgz") and uuid_str in f
    ]

    if matched_files:
        # backup and rename
        old_file_path = os.path.join(SAVE_DIR, matched_files[0])
        backup_path = old_file_path + ".bak"
        shutil.move(old_file_path, backup_path)
        save_path = old_file_path
    else:
        save_path = os.path.join(SAVE_DIR, f"padata_{timestamp}_{uuid_str}.tgz")

    # rename (atomic)を使って確実にflushする
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
        "replaced": bool(matched_files)
    }, 200

def is_valid_uuid(value):
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False
