from flask import Blueprint, request, abort
import os
from datetime import datetime
import uuid

receive_bp = Blueprint("receive", __name__)

EXPECTED_API_KEY = os.environ.get("RESULT_SERVER_KEY")
SAVE_DIR = "received"
ESTIMATED_RESULT_DIR = "estimated_results"

def require_api_key():
    api_key = request.headers.get("X-API-Key")
    if api_key != EXPECTED_API_KEY:
        abort(401, description="Invalid API Key")

def save_json_file(data, prefix, out_dir, given_uuid=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = given_uuid or str(uuid.uuid4())
    filename = f"{prefix}_{timestamp}_{unique_id}.json"
    path = os.path.join(out_dir, filename)
    tmp_path = path + ".tmp"

    #------------------------------This is for
    #data = request.data
    #------------------------------
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    #-----------------------------This is for
    #data = request.get_json()
    #-----------------------------
    #with open(tmp_path, "w", encoding="utf-8") as f:
    #    json.dump(data, f, indent=2, ensure_ascii=False)
    #    f.flush()
    #    os.fsync(f.fileno())

    os.rename(tmp_path, path)
    print(f"Saved {prefix}: {path}", flush=True)

    return {
        "status": "ok",
        "id": unique_id,
        "timestamp": timestamp,
        "json_file": filename,
    }


@receive_bp.route("write-api", methods=["POST"])
def receive_result():
    require_api_key()
    data = request.data
    #data = request.get_json()
    return save_json_file(
        data=data,
        prefix="result",
        out_dir=SAVE_DIR
    ), 200

@receive_bp.route("write-est", methods=["POST"])
def upload_estimate():
    require_api_key()
    data = request.data
    #data = request.get_json()
    return save_json_file(
        data=data,
        prefix="estimate",
        out_dir=ESTIMATED_RESULT_DIR,
        given_uuid=request.headers.get("X-UUID")
    ), 200





#@receive_bp.route("write-api", methods=["POST"])
#def receive():
#    api_key = request.headers.get("X-API-Key")
#    if api_key != EXPECTED_API_KEY:
#        abort(401, description="Invalid API Key")
#
#    data = request.data
#    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#    unique_id = str(uuid.uuid4())
#
#    json_filename = f"result_{timestamp}_{unique_id}.json"
#    json_path = os.path.join(SAVE_DIR, json_filename)
#    # rename (atomic)を使って確実にflushする
#    tmp_path = json_path + ".tmp"
#    with open(tmp_path, "wb") as f:
#        f.write(data)
#        f.flush()
#        os.fsync(f.fileno())
#    os.rename(tmp_path, json_path)
#
#    print(f"Saved: {json_path}", flush=True)
#    return {
#        "status": "ok",
#        "id": unique_id,
#        "timestamp": timestamp,
#        "json_file": json_filename,
#    }, 200
