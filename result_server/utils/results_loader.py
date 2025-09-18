import os
import json
import re
from datetime import datetime
from utils.result_file import get_file_confidential_tags
from utils.otp_manager import get_affiliations
from flask import url_for

#--------------------------------------------------------------------------------------------------------------
def load_json_with_confidential_filter(json_file, directory, affs=None, public_only=True, authenticated=False):
    """
    指定ディレクトリの JSON を読み込み、confidential タグに基づいて
    フィルタリングする。
    
    Args:
        json_file (str): JSON ファイル名
        directory (str): ファイルのあるディレクトリ
        affs (list, optional): セッションユーザーの所属リスト
        public_only (bool): 公開のみかどうか
        authenticated (bool): 認証済みかどうか
    
    Returns:
        dict or None: 読み込んだ JSON データ（フィルタに引っかかれば None）
    """
    if affs is None:
        affs = []

    tags = get_file_confidential_tags(json_file, directory)
    #print(f"Processing {json_file}, tags={tags}, public_only={public_only}, authenticated={authenticated}, flush=True)
    if public_only and tags:
        return None
    if tags and not authenticated:
        return None
    if tags and affs:
        if not (set(tags) & set(affs)):
            return None

    try:
        with open(os.path.join(directory, json_file), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None
#--------------------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------------------------------

SAVE_DIR = "received"
ESTIMATED_DIR = "estimated_results"

def load_results_table(public_only=True, session_email=None, authenticated=False):
    affs = get_affiliations(session_email) if session_email else []
    files = os.listdir(SAVE_DIR)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)
    tgz_files = [f for f in files if f.endswith(".tgz")]

    rows = []
    for json_file in json_files:
        data = load_json_with_confidential_filter(json_file, SAVE_DIR, affs, public_only, authenticated)
        if data is None:
            continue

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

        # get timestamp and uuid
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
            # error handling to avoid strange link generation such as ../resuts//dev/results/result_...json
            #"json_link": url_for("results.show_result", filename=json_file.split("results/")[-1].lstrip("/")),
            #"data_link": url_for("results.show_result", filename=tgz_file.split("results/")[-1].lstrip("/")) if tgz_file else None,
            "json_link": url_for("results.show_result", filename=json_file),
            "data_link": url_for("results.show_result", filename=tgz_file) if tgz_file else None,
            #"json_link": json_file,
            #"data_link": tgz_file,
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


def load_estimated_results_table(public_only=True, session_email=None, authenticated=False):
    affs = get_affiliations(session_email) if session_email else []
    files = os.listdir(ESTIMATED_DIR)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)

    rows = []
    for json_file in json_files:
        data = load_json_with_confidential_filter(json_file, ESTIMATED_DIR, affs, public_only, authenticated)
        if data is None:
            continue

        current = data.get("current_system", {})
        future = data.get("future_system", {})

        # get timestamp and uuid
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

        row = {
            "timestamp": timestamp,
            "code": data.get("code", ""),
            "exp": data.get("exp", ""),
            "benchmark_system": data.get("benchmark_system", ""),
            "benchmark_fom": data.get("benchmark_fom", ""),
            "benchmark_nodes": data.get("benchmark_nodes", ""),
            "systemA_fom": current.get("fom", ""),
            "systemA_system": current.get("system", ""),
            "systemA_nodes": current.get("nodes", ""),
            "systemA_method": current.get("method", ""),
            "systemB_fom": future.get("fom", ""),
            "systemB_system": future.get("system", ""),
            "systemB_nodes": future.get("nodes", ""),
            "systemB_method": future.get("method", ""),
            "performance_ratio": data.get("performance_ratio", ""),
            "json_link": json_file,
        }
        rows.append(row)

    columns = [
        ("Timestamp", "timestamp"),
        ("CODE", "code"),
        ("Exp", "exp"),
        ("Benchmark System", "benchmark_system"),
        ("Benchmark FOM", "benchmark_fom"),
        ("Benchmark Nodes", "benchmark_nodes"),
        ("System A FOM", "systemA_fom"),
        ("System A Nodes", "systemA_nodes"),
        ("System A Method", "systemA_method"),
        ("System B FOM", "systemB_fom"),
        ("System B Nodes", "systemB_nodes"),
        ("System B Method", "systemB_method"),
        ("Performance Ratio", "performance_ratio"),
        ("JSON", "json_link"),
    ]
    return rows, columns
