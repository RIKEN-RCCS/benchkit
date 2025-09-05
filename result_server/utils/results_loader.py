import os
import json
import re
from datetime import datetime
from utils.result_file import get_file_confidential_tags
from utils.otp_manager import get_affiliations

SAVE_DIR = "received"

def load_results_table(public_only=True, session_email=None, authenticated=False):
    files = os.listdir(SAVE_DIR)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)
    tgz_files = [f for f in files if f.endswith(".tgz")]

    rows = []
    for json_file in json_files:
        tags = get_file_confidential_tags(json_file)

        if public_only and tags:
            continue

        if tags and not authenticated:
            # 認証なしならスキップ
            continue
        if tags and session_email:
            affs = get_affiliations(session_email)
            if not (set(tags) & set(affs)):
                continue

        # JSON読み込み
        try:
            with open(os.path.join(SAVE_DIR, json_file), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        code = data.get("code", "N/A")
        sys = data.get("system", "N/A")
        fom = data.get("FOM", "N/A")
        fom_version = data.get("FOM_version", "N/A")
        exp = data.get("Exp", "N/A")
        cpu = data.get("cpu_name", "N/A")
        gpu = data.get("gpu_name", "N/A")
        nodes = data.get("node_count", "N/A")
        cpus = data.get("cpus_per_node", "N/A")
        gpus = data.get("gpus_per_node", "N/A")
        cpu_cores = data.get("cpu_cores", "N/A")

        match = re.search(r"\d{8}_\d{6}", json_file)
        timestamp = "Unknown"
        if match:
            try:
                ts = datetime.strptime(match.group(), "%Y%m%d_%H%M%S")
                timestamp = ts.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

        uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", json_file, re.IGNORECASE)
        uid = uuid_match.group(0) if uuid_match else None
        tgz_file = next((f for f in tgz_files if uid in f), None) if uid else None

        row = {
            "timestamp": timestamp,
            "code": code,
            "exp": exp,
            "fom": fom,
            "fom_version": fom_version,
            "system": sys,
            "cpu": cpu,
            "gpu": gpu,
            "nodes": nodes,
            "cpus": cpus,
            "gpus": gpus,
            "cpu_cores": cpu_cores,
            "json_link": json_file,
            "data_link": tgz_file,
        }
        rows.append(row)

    columns = [
        ("Timestamp", "timestamp"),
        ("CODE", "code"),
        ("Exp", "exp"),
        ("FOM", "fom"),
        ("FOM version", "fom_version"),
        ("SYSTEM", "system"),
        ("CPU Name", "cpu"),
        ("GPU Name", "gpu"),
        ("Nodes", "nodes"),
        ("CPU/node", "cpus"),
        ("GPU/node", "gpus"),
        ("CPU Core Count", "cpu_cores"),
        ("JSON", "json_link"),
        ("PA Data", "data_link"),
    ]
    return rows, columns
