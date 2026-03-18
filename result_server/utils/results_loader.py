import os
import json
import re
from datetime import datetime
from math import ceil
from utils.result_file import get_file_confidential_tags
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
    if public_only and tags:
        return None
    if tags and not authenticated:
        return None
    if tags and "admin" not in affs:
        if not affs or not (set(tags) & set(affs)):
            return None

    try:
        with open(os.path.join(directory, json_file), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None

#--------------------------------------------------------------------------------------------------------------

def load_single_result(filename, save_dir):
    """
    指定ファイル名のJSONを読み込み dict で返す。
    ファイルが存在しない場合は None を返す。
    権限チェックはルート側で実施するため、ここでは単純なJSON読み込みのみ行う。

    Args:
        filename (str): JSONファイル名
        save_dir (str): ファイルのあるディレクトリ（必須）

    Returns:
        dict or None: 読み込んだJSONデータ、ファイルが存在しない場合はNone
    """
    filepath = os.path.join(save_dir, filename)
    if not os.path.isfile(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_multiple_results(filenames, save_dir):
    """
    複数の結果JSONを読み込み、タイムスタンプ昇順でソートしたリストを返す。

    Args:
        filenames (list[str]): JSONファイル名のリスト
        save_dir (str): ファイルのあるディレクトリ（必須）

    Returns:
        list[dict]: [{"filename": str, "timestamp": str, "data": dict}, ...]
            タイムスタンプ昇順でソート済み
    """
    results = []
    for filename in filenames:
        data = load_single_result(filename, save_dir)
        if data is None:
            continue

        # ファイル名から YYYYMMDD_HHMMSS パターンでタイムスタンプを抽出
        timestamp = "Unknown"
        match = re.search(r"\d{8}_\d{6}", filename)
        if match:
            try:
                ts = datetime.strptime(match.group(), "%Y%m%d_%H%M%S")
                timestamp = ts.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        results.append({
            "filename": filename,
            "timestamp": timestamp,
            "data": data,
        })

    # タイムスタンプ昇順でソート（"Unknown" は先頭に来る）
    results.sort(key=lambda r: r["timestamp"])
    return results

def _build_row(json_file, data, tgz_files):
    """JSONデータからテーブル行を構築するヘルパー関数"""
    code = data.get("code", "N/A")
    sys_name = data.get("system", "N/A")
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
        except Exception:
            pass

    uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", json_file, re.IGNORECASE)
    uid = uuid_match.group(0) if uuid_match else None
    tgz_file = next((f for f in tgz_files if uid in f), None) if uid else None

    # metrics.vector の有無を判定
    metrics = data.get("metrics", {})
    has_vector = isinstance(metrics, dict) and "vector" in metrics

    row = {
        "timestamp": timestamp,
        "code": code,
        "exp": exp,
        "fom": fom,
        "fom_version": fom_version,
        "system": sys_name,
        "cpu": cpu,
        "gpu": gpu,
        "nodes": nodes,
        "cpus": cpus,
        "gpus": gpus,
        "cpu_cores": cpu_cores,
        "json_link": url_for("results.show_result", filename=json_file),
        "data_link": url_for("results.show_result", filename=tgz_file) if tgz_file else None,
        "has_vector": has_vector,
        "detail_link": url_for("results.result_detail", filename=json_file) if has_vector else None,
        "filename": json_file,
    }
    return row


def _has_active_filters(filter_system, filter_code, filter_exp):
    """フィルタが1つでも指定されているか判定"""
    return any(f is not None for f in (filter_system, filter_code, filter_exp))


def _matches_filters(data, filter_system, filter_code, filter_exp):
    """JSONデータがフィルタ条件に一致するか判定"""
    if filter_system is not None and data.get("system") != filter_system:
        return False
    if filter_code is not None and data.get("code") != filter_code:
        return False
    if filter_exp is not None and data.get("Exp") != filter_exp:
        return False
    return True


def load_results_table(directory, public_only=True, session_email=None, authenticated=False, affiliations=None,
                       page=1, per_page=100, filter_system=None, filter_code=None, filter_exp=None):
    # per_page バリデーション
    if per_page not in (50, 100, 200):
        per_page = 100

    affs = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)
    tgz_files = [f for f in files if f.endswith(".tgz")]

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

    has_filters = _has_active_filters(filter_system, filter_code, filter_exp)

    if not has_filters:
        # フィルタなし: ファイル名リストに対して confidential フィルタを適用後、スライスして対象ページのJSONのみ読み込み
        # confidential フィルタはJSONの中身ではなくファイル名ベースなので、先に適用可能なファイルを特定
        # ただし confidential チェックにはファイル読み込みが不要（タグはファイル名から判定）
        # load_json_with_confidential_filter が None を返すファイルを除外する必要があるため、
        # まず有効なファイルリストを構築してからスライスする
        valid_json_files = []
        for json_file in json_files:
            tags = get_file_confidential_tags(json_file, directory)
            if public_only and tags:
                continue
            if tags and not authenticated:
                continue
            if tags and "admin" not in affs:
                if not affs or not (set(tags) & set(affs)):
                    continue
            valid_json_files.append(json_file)

        paginated_files, pagination_info = paginate_list(valid_json_files, page, per_page)

        rows = []
        for json_file in paginated_files:
            try:
                with open(os.path.join(directory, json_file), "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            rows.append(_build_row(json_file, data, tgz_files))

        return rows, columns, pagination_info
    else:
        # フィルタあり: 全JSON読み込み後にフィルタ適用、結果リストをスライス
        rows = []
        for json_file in json_files:
            data = load_json_with_confidential_filter(json_file, directory, affs, public_only, authenticated)
            if data is None:
                continue
            if not _matches_filters(data, filter_system, filter_code, filter_exp):
                continue
            rows.append(_build_row(json_file, data, tgz_files))

        paginated_rows, pagination_info = paginate_list(rows, page, per_page)
        return paginated_rows, columns, pagination_info


def _matches_estimated_filters(data, filter_system, filter_code, filter_exp):
    """推定結果のJSONデータがフィルタ条件に一致するか判定"""
    if filter_system is not None and data.get("benchmark_system") != filter_system:
        return False
    if filter_code is not None and data.get("code") != filter_code:
        return False
    if filter_exp is not None and data.get("exp") != filter_exp:
        return False
    return True


def load_estimated_results_table(directory, public_only=True, session_email=None, authenticated=False, affiliations=None,
                                 page=1, per_page=100, filter_system=None, filter_code=None, filter_exp=None):
    # per_page バリデーション
    if per_page not in (50, 100, 200):
        per_page = 100

    affs = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)

    has_filters = _has_active_filters(filter_system, filter_code, filter_exp)

    rows = []
    for json_file in json_files:
        data = load_json_with_confidential_filter(json_file, directory, affs, public_only, authenticated)
        if data is None:
            continue

        if has_filters and not _matches_estimated_filters(data, filter_system, filter_code, filter_exp):
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
            except Exception:
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

    paginated_rows, pagination_info = paginate_list(rows, page, per_page)
    return paginated_rows, columns, pagination_info


def get_filter_options(directory, public_only=True, authenticated=False, affiliations=None):
    """
    全JSONファイルからフィルタドロップダウンの選択肢を抽出して返す。

    Args:
        directory (str): JSONファイルのあるディレクトリ
        public_only (bool): 公開のみかどうか
        authenticated (bool): 認証済みかどうか
        affiliations (list, optional): セッションユーザーの所属リスト

    Returns:
        dict: {"systems": sorted_list, "codes": sorted_list, "exps": sorted_list}
    """
    affs = affiliations if affiliations is not None else []
    systems = set()
    codes = set()
    exps = set()

    try:
        files = os.listdir(directory)
    except OSError:
        return {"systems": [], "codes": [], "exps": []}

    json_files = [f for f in files if f.endswith(".json")]

    for json_file in json_files:
        data = load_json_with_confidential_filter(json_file, directory, affs, public_only, authenticated)
        if data is None:
            continue

        val = data.get("system", "")
        if val and val != "N/A":
            systems.add(val)

        val = data.get("code", "")
        if val and val != "N/A":
            codes.add(val)

        val = data.get("Exp", "")
        if val and val != "N/A":
            exps.add(val)

    return {
        "systems": sorted(systems),
        "codes": sorted(codes),
        "exps": sorted(exps),
    }


def get_estimated_filter_options(directory, public_only=True, authenticated=False, affiliations=None):
    """
    推定結果の全JSONファイルからフィルタドロップダウンの選択肢を抽出して返す。

    Args:
        directory (str): JSONファイルのあるディレクトリ
        public_only (bool): 公開のみかどうか
        authenticated (bool): 認証済みかどうか
        affiliations (list, optional): セッションユーザーの所属リスト

    Returns:
        dict: {"systems": sorted_list, "codes": sorted_list, "exps": sorted_list}
    """
    affs = affiliations if affiliations is not None else []
    systems = set()
    codes = set()
    exps = set()

    try:
        files = os.listdir(directory)
    except OSError:
        return {"systems": [], "codes": [], "exps": []}

    json_files = [f for f in files if f.endswith(".json")]

    for json_file in json_files:
        data = load_json_with_confidential_filter(json_file, directory, affs, public_only, authenticated)
        if data is None:
            continue

        val = data.get("benchmark_system", "")
        if val and val != "N/A":
            systems.add(val)

        val = data.get("code", "")
        if val and val != "N/A":
            codes.add(val)

        val = data.get("exp", "")
        if val and val != "N/A":
            exps.add(val)

    return {
        "systems": sorted(systems),
        "codes": sorted(codes),
        "exps": sorted(exps),
    }


def paginate_list(items: list, page: int, per_page: int) -> tuple[list, dict]:
    """
    リストにページネーションを適用する。

    Args:
        items: ページネーション対象のリスト
        page: ページ番号（1始まり）
        per_page: 1ページあたりの件数

    Returns:
        (paginated_items, pagination_info)
        pagination_info = {
            "page": int,
            "per_page": int,
            "total": int,
            "total_pages": int,
        }
    """
    total = len(items)
    total_pages = max(1, ceil(total / per_page)) if total > 0 else 1

    # クランプ: 範囲外のページ番号を有効範囲に収める
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = items[start:end]

    pagination_info = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }

    return paginated_items, pagination_info
