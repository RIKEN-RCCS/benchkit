import os
import json
import re
from datetime import datetime
from math import ceil
from utils.result_file import get_file_confidential_tags
from flask import url_for

# ページサイズ定数
ALLOWED_PER_PAGE = (50, 100, 200)
DEFAULT_PER_PAGE = 100

# フィールドマッピング定数
RESULT_FIELD_MAP = {"system": "system", "code": "code", "exp": "Exp"}
ESTIMATED_FIELD_MAP = {"system": "current_system.system", "code": "code", "exp": "exp"}

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


def summarize_result_quality(data):
    """Result JSON の品質サマリを返す。"""
    warnings = []

    fom = data.get("FOM")
    has_fom = fom not in (None, "", "null", "N/A")

    source_info = data.get("source_info")
    has_source_info = isinstance(source_info, dict) and bool(source_info)
    source_info_complete = False
    if has_source_info:
        source_type = source_info.get("source_type")
        if source_type == "git":
            source_info_complete = all(source_info.get(k) for k in ("repo_url", "branch", "commit_hash"))
        elif source_type == "file":
            source_info_complete = all(source_info.get(k) for k in ("file_path", "md5sum"))
        else:
            warnings.append("source_info has unknown source_type")
    else:
        warnings.append("source_info is missing")

    if has_source_info and not source_info_complete:
        warnings.append("source_info is incomplete")

    fom_breakdown = data.get("fom_breakdown")
    sections = []
    overlaps = []
    if isinstance(fom_breakdown, dict):
        if isinstance(fom_breakdown.get("sections"), list):
            sections = fom_breakdown.get("sections", [])
        if isinstance(fom_breakdown.get("overlaps"), list):
            overlaps = fom_breakdown.get("overlaps", [])

    has_breakdown = bool(sections or overlaps)
    if not has_breakdown:
        warnings.append("fom_breakdown is missing")

    section_names = [s.get("name") for s in sections if isinstance(s, dict) and s.get("name")]
    if len(section_names) != len(set(section_names)):
        warnings.append("duplicate section names found")

    unknown_overlap_refs = 0
    for overlap in overlaps:
        if not isinstance(overlap, dict):
            continue
        members = overlap.get("sections", [])
        if not isinstance(members, list) or not members:
            warnings.append("overlap has no sections")
            continue
        for member in members:
            if member not in section_names:
                unknown_overlap_refs += 1

    if unknown_overlap_refs:
        warnings.append("overlap references undefined sections")

    section_pkg_count = sum(
        1 for s in sections
        if isinstance(s, dict) and isinstance(s.get("estimation_package"), str) and s.get("estimation_package")
    )
    overlap_pkg_count = sum(
        1 for o in overlaps
        if isinstance(o, dict) and isinstance(o.get("estimation_package"), str) and o.get("estimation_package")
    )
    artifact_count = sum(
        len(item.get("artifacts", []))
        for item in sections + overlaps
        if isinstance(item, dict) and isinstance(item.get("artifacts"), list)
    )

    expected_pkg_items = len(sections) + len(overlaps)
    actual_pkg_items = section_pkg_count + overlap_pkg_count
    estimation_ready = has_breakdown and expected_pkg_items > 0 and expected_pkg_items == actual_pkg_items
    provenance_rich = estimation_ready and source_info_complete and artifact_count > 0

    if has_breakdown and expected_pkg_items > actual_pkg_items:
        warnings.append("some breakdown items are missing estimation_package")

    if provenance_rich:
        level = "rich"
        label = "Rich"
        summary = "Breakdown, estimation bindings, source provenance, and artifacts are present."
    elif estimation_ready:
        level = "ready"
        label = "Ready"
        summary = "Breakdown and estimation bindings are present."
    else:
        level = "basic"
        label = "Basic"
        summary = "Core result fields are present, but estimation-related detail is limited."

    return {
        "level": level,
        "label": label,
        "summary": summary,
        "warnings": warnings,
        "stats": {
            "has_fom": has_fom,
            "has_source_info": has_source_info,
            "source_info_complete": source_info_complete,
            "has_breakdown": has_breakdown,
            "section_count": len(sections),
            "overlap_count": len(overlaps),
            "section_package_count": section_pkg_count,
            "overlap_package_count": overlap_pkg_count,
            "artifact_count": artifact_count,
        },
    }


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
    nodes = data.get("node_count", "N/A")

    numproc_node = data.get("numproc_node", "N/A")
    if numproc_node is None or numproc_node == "":
        numproc_node = "N/A"

    nthreads = data.get("nthreads", "N/A")
    if nthreads is None or nthreads == "":
        nthreads = "N/A"

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
    uid = uuid_match.group(0) if uuid_match else data.get("_server_uuid")
    tgz_file = next((f for f in tgz_files if uid in f), None) if uid else None

    # metrics.vector の有無を判定
    metrics = data.get("metrics", {})
    has_vector = isinstance(metrics, dict) and "vector" in metrics

    # pipeline_timing fields
    pipeline_timing = data.get("pipeline_timing", None)
    if isinstance(pipeline_timing, dict):
        build_time = str(pipeline_timing.get("build_time", "-")) if "build_time" in pipeline_timing else "-"
        queue_time = str(pipeline_timing.get("queue_time", "-")) if "queue_time" in pipeline_timing else "-"
        run_time = str(pipeline_timing.get("run_time", "-")) if "run_time" in pipeline_timing else "-"
    else:
        build_time = "-"
        queue_time = "-"
        run_time = "-"

    execution_mode = data.get("execution_mode", "-") or "-"
    ci_trigger = data.get("ci_trigger", "-") or "-"
    build_job = data.get("build_job", "-") or "-"
    run_job = data.get("run_job", "-") or "-"
    pipeline_id = data.get("pipeline_id", "-")
    if pipeline_id is None:
        pipeline_id = "-"
    else:
        pipeline_id = str(pipeline_id)

    # source_info の読み込み
    source_info = data.get("source_info", None)

    # source_hash の生成（Branch/Hash列用）
    if source_info and isinstance(source_info, dict):
        st = source_info.get("source_type")
        if st == "git":
            _branch = source_info.get("branch", "")
            commit = source_info.get("commit_hash", "")
            short_hash = commit[:7] if commit else ""
            source_hash = f"{_branch}@{short_hash}" if _branch and short_hash else short_hash or _branch or "-"
        elif st == "file":
            md5 = source_info.get("md5sum", "")
            source_hash = md5[:8] if md5 else "-"
        else:
            source_hash = "-"
    else:
        source_hash = "-"

    quality = summarize_result_quality(data)

    row = {
        "timestamp": timestamp,
        "code": code,
        "exp": exp,
        "fom": fom,
        "fom_version": fom_version,
        "system": sys_name,
        "nodes": nodes,
        "numproc_node": numproc_node,
        "nthreads": nthreads,
        "json_link": url_for("results.show_result", filename=json_file),
        "data_link": url_for("results.show_result", filename=tgz_file) if tgz_file else None,
        "has_vector": has_vector,
        "detail_link": url_for("results.result_detail", filename=json_file),
        "filename": json_file,
        "build_time": build_time,
        "queue_time": queue_time,
        "run_time": run_time,
        "execution_mode": execution_mode,
        "ci_trigger": ci_trigger,
        "build_job": build_job,
        "run_job": run_job,
        "pipeline_id": pipeline_id,
        "source_info": source_info,
        "source_hash": source_hash,
        "quality": quality,
    }
    return row


def _has_active_filters(filter_system, filter_code, filter_exp):
    """フィルタが1つでも指定されているか判定"""
    return any(f is not None for f in (filter_system, filter_code, filter_exp))


def _get_nested(data, field_path):
    """ドット記法のフィールドパスでネストされた値を取得する。"""
    keys = field_path.split(".")
    val = data
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None
    return val


def _matches_filters(data, filter_system, filter_code, filter_exp, field_map=None):
    """フィールドマッピングに基づいてフィルタ条件を判定する。"""
    if field_map is None:
        field_map = RESULT_FIELD_MAP
    if filter_system is not None:
        val = _get_nested(data, field_map["system"])
        if val != filter_system:
            return False
    if filter_code is not None:
        val = _get_nested(data, field_map["code"])
        if val != filter_code:
            return False
    if filter_exp is not None:
        val = _get_nested(data, field_map["exp"])
        if val != filter_exp:
            return False
    return True


def load_results_table(directory, public_only=True, session_email=None, authenticated=False, affiliations=None,
                       page=1, per_page=100, filter_system=None, filter_code=None, filter_exp=None,
                       padata_directory=None):
    # per_page バリデーション
    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    affs = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)
    tgz_dir = padata_directory or directory
    tgz_files = [f for f in os.listdir(tgz_dir) if f.endswith(".tgz")]

    columns = [
        ("Timestamp", "timestamp"),
        ("CODE", "code"),
        ("Branch/Hash", "source_hash"),
        ("Exp", "exp"),
        ("FOM", "fom"),
        ("FOM version", "fom_version"),
        ("SYSTEM", "system"),
        ("Nodes", "nodes"),
        ("P/N", "numproc_node"),
        ("T/P", "nthreads"),
        ("JSON", "json_link"),
        ("PA Data", "data_link"),
        ("Trigger", "ci_trigger"),
        ("Pipeline", "pipeline_id"),
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
            if not _matches_filters(data, filter_system, filter_code, filter_exp, field_map=RESULT_FIELD_MAP):
                continue
            rows.append(_build_row(json_file, data, tgz_files))

        paginated_rows, pagination_info = paginate_list(rows, page, per_page)
        return paginated_rows, columns, pagination_info


def load_estimated_results_table(directory, public_only=True, session_email=None, authenticated=False, affiliations=None,
                                 page=1, per_page=100, filter_system=None, filter_code=None, filter_exp=None):
    # per_page バリデーション
    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    affs = affiliations if affiliations is not None else []
    files = os.listdir(directory)
    json_files = sorted([f for f in files if f.endswith(".json")], reverse=True)

    has_filters = _has_active_filters(filter_system, filter_code, filter_exp)

    rows = []
    for json_file in json_files:
        data = load_json_with_confidential_filter(json_file, directory, affs, public_only, authenticated)
        if data is None:
            continue

        if has_filters and not _matches_filters(data, filter_system, filter_code, filter_exp, field_map=ESTIMATED_FIELD_MAP):
            continue

        current = data.get("current_system", {})
        future = data.get("future_system", {})
        estimate_meta = data.get("estimate_metadata", {})
        applicability = data.get("applicability", {})

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

        estimate_timestamp = estimate_meta.get("estimation_result_timestamp") or timestamp
        estimate_uuid = estimate_meta.get("estimation_result_uuid") or uid

        row = {
            "timestamp": estimate_timestamp,
            "code": data.get("code", ""),
            "exp": data.get("exp", ""),
            # System A (current_system)
            "systemA_system": current.get("system", ""),
            "systemA_fom": current.get("fom", ""),
            "systemA_target_nodes": current.get("target_nodes", ""),
            "systemA_scaling_method": current.get("scaling_method", ""),
            "systemA_bench_system": current.get("benchmark", {}).get("system", ""),
            "systemA_bench_fom": current.get("benchmark", {}).get("fom", ""),
            "systemA_bench_nodes": current.get("benchmark", {}).get("nodes", ""),
            # System B (future_system)
            "systemB_system": future.get("system", ""),
            "systemB_fom": future.get("fom", ""),
            "systemB_target_nodes": future.get("target_nodes", ""),
            "systemB_scaling_method": future.get("scaling_method", ""),
            "systemB_bench_system": future.get("benchmark", {}).get("system", ""),
            "systemB_bench_fom": future.get("benchmark", {}).get("fom", ""),
            "systemB_bench_nodes": future.get("benchmark", {}).get("nodes", ""),
            # Common
            "applicability_status": applicability.get("status", ""),
            "requested_estimation_package": estimate_meta.get("requested_estimation_package", ""),
            "estimation_package": estimate_meta.get("estimation_package", ""),
            "method_class": estimate_meta.get("method_class", ""),
            "detail_level": estimate_meta.get("detail_level", ""),
            "current_estimation_package": estimate_meta.get("current_package", {}).get("estimation_package", ""),
            "future_estimation_package": estimate_meta.get("future_package", {}).get("estimation_package", ""),
            "requested_current_estimation_package": estimate_meta.get("current_package", {}).get("requested_estimation_package", ""),
            "requested_future_estimation_package": estimate_meta.get("future_package", {}).get("requested_estimation_package", ""),
            "estimate_uuid": estimate_uuid or "",
            "performance_ratio": data.get("performance_ratio", ""),
            "json_link": json_file,
        }
        rows.append(row)

    columns = [
        ("Timestamp", "timestamp"),
        ("CODE", "code"),
        ("Exp", "exp"),
        # System A (current_system)
        ("A System", "systemA_system"),
        ("A FOM", "systemA_fom"),
        ("A Target Nodes", "systemA_target_nodes"),
        ("A Scaling Method", "systemA_scaling_method"),
        ("A Bench System", "systemA_bench_system"),
        ("A Bench FOM", "systemA_bench_fom"),
        ("A Bench Nodes", "systemA_bench_nodes"),
        # System B (future_system)
        ("B System", "systemB_system"),
        ("B FOM", "systemB_fom"),
        ("B Target Nodes", "systemB_target_nodes"),
        ("B Scaling Method", "systemB_scaling_method"),
        ("B Bench System", "systemB_bench_system"),
        ("B Bench FOM", "systemB_bench_fom"),
        ("B Bench Nodes", "systemB_bench_nodes"),
        # Common
        ("Applicability", "applicability_status"),
        ("Requested Package", "requested_estimation_package"),
        ("Applied Package", "estimation_package"),
        ("Estimate UUID", "estimate_uuid"),
        ("Performance Ratio", "performance_ratio"),
        ("JSON", "json_link"),
    ]

    paginated_rows, pagination_info = paginate_list(rows, page, per_page)
    return paginated_rows, columns, pagination_info


def get_filter_options(directory, public_only=True, authenticated=False, affiliations=None,
                       field_map=None, filter_code=None):
    """
    全JSONファイルからフィルタドロップダウンの選択肢を抽出して返す。
    field_map に基づいて systems/codes/exps のフィールド名を動的に参照する。

    Args:
        directory (str): JSONファイルのあるディレクトリ
        public_only (bool): 公開のみかどうか
        authenticated (bool): 認証済みかどうか
        affiliations (list, optional): セッションユーザーの所属リスト
        field_map (dict, optional): フィールド名マッピング。None の場合は RESULT_FIELD_MAP を使用。

    Returns:
        dict: {"systems": sorted_list, "codes": sorted_list, "exps": sorted_list}
    """
    if field_map is None:
        field_map = RESULT_FIELD_MAP
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

        val = _get_nested(data, field_map["system"])
        if val and val != "N/A":
            systems.add(val)

        val = _get_nested(data, field_map["code"])
        if val and val != "N/A":
            codes.add(val)

        val = _get_nested(data, field_map["exp"])
        if val and val != "N/A":
            if not filter_code or _get_nested(data, field_map["code"]) == filter_code:
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
