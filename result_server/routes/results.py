import os
import json
from flask import Blueprint, render_template, send_from_directory, abort, jsonify
import re
from datetime import datetime

results_bp = Blueprint("results", __name__)
SAVE_DIR = "received"

@results_bp.route("/results")
def list_results():
    files = os.listdir(SAVE_DIR)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)
    tgz_files = [f for f in files if f.endswith(".tgz")]

    rows = []
    for json_file in json_files:
        json_path = os.path.join(SAVE_DIR, json_file)
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
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
        except Exception:
            code = sys = fom = cpu = gpu = nodes = cpus = gpus = cpu_cores = "Invalid"

        match = re.search(r"\d{8}_\d{6}", json_file)
        if match:
            try:
                ts = datetime.strptime(match.group(), "%Y%m%d_%H%M%S")
                timestamp = ts.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                timestamp = "Invalid"
        else:
            timestamp = "Unknown"

        uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", json_file, re.IGNORECASE)
        if uuid_match:
            uid = uuid_match.group(0)
        else:
            uid = None

        if uid:
            tgz_file = next((f for f in tgz_files if uid in f), None)
        else:
            tgz_file = None

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

    return render_template("results.html", columns=columns, rows=rows)


@results_bp.route("/results/<filename>")
def show_result(filename):
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
    
