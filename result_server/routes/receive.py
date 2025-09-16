from flask import Blueprint, request, abort
import os
from datetime import datetime
import uuid

receive_bp = Blueprint("receive", __name__)

EXPECTED_API_KEY = os.environ.get("RESULT_SERVER_KEY")
SAVE_DIR = "received"

@receive_bp.route("write-api", methods=["POST"])
def receive():
    api_key = request.headers.get("X-API-Key")
    if api_key != EXPECTED_API_KEY:
        abort(401, description="Invalid API Key")

    data = request.data
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())

    json_filename = f"result_{timestamp}_{unique_id}.json"
    json_path = os.path.join(SAVE_DIR, json_filename)
    # rename (atomic)を使って確実にflushする
    tmp_path = json_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp_path, json_path)

    print(f"Saved: {json_path}", flush=True)
    return {
        "status": "ok",
        "id": unique_id,
        "timestamp": timestamp,
        "json_file": json_filename,
    }, 200
