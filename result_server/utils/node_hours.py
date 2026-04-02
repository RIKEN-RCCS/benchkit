from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Optional


def compute_node_hours(data: dict) -> float:
    """
    単一Result JSONからノード時間を算出する。

    - cross モード: node_count × run_time / 3600
    - native モード: node_count × (build_time + run_time) / 3600
    - node_count/run_time が欠損・非数値の場合は 0.0
    - native で build_time が欠損・非数値の場合は build_time=0 として算出

    Returns: float（小数点以下2桁に丸め）
    """
    try:
        node_count = float(data.get("node_count", None))
    except (TypeError, ValueError):
        return 0.0

    pipeline_timing = data.get("pipeline_timing") or {}

    try:
        run_time = float(pipeline_timing.get("run_time", None))
    except (TypeError, ValueError):
        return 0.0

    execution_mode = data.get("execution_mode", "cross")

    if execution_mode == "native":
        try:
            build_time = float(pipeline_timing.get("build_time", None))
        except (TypeError, ValueError):
            build_time = 0.0
        return round(node_count * (build_time + run_time) / 3600, 2)

    # cross モード（デフォルト）
    return round(node_count * run_time / 3600, 2)


def extract_timestamp_from_filename(filename: str) -> datetime | None:
    """
    ファイル名から YYYYMMDD_HHMMSS パターンのタイムスタンプを抽出する。
    既存の results_loader.py と同じ正規表現パターンを使用。

    Returns: datetime or None
    """
    match = re.search(r"\d{8}_\d{6}", filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def get_fiscal_year(dt: datetime) -> int:
    """
    日付から会計年度を返す。
    1〜3月 → 前年の会計年度、4〜12月 → その年の会計年度
    """
    if dt.month <= 3:
        return dt.year - 1
    return dt.year


def get_fiscal_month_index(dt: datetime) -> int:
    """
    会計年度内の月インデックス（0〜11）を返す。
    4月=0, 5月=1, ..., 3月=11
    """
    return (dt.month - 4) % 12


def get_half(dt: datetime) -> str:
    """
    上期（first）か下期（second）かを返す。
    4〜9月=first, 10〜3月=second
    """
    if 4 <= dt.month <= 9:
        return "first"
    return "second"


def _generate_period_labels(fiscal_year: int, period_type: str) -> list[str]:
    """
    期間タイプに応じた期間ラベルリストを生成する。

    - monthly: 12個 "YYYY年M月"（4月〜翌3月）
    - semi_annual: 2個 "上期（4月〜9月）", "下期（10月〜3月）"
    - fiscal_year: 1個 "FY{year}"
    """
    if period_type == "monthly":
        labels = []
        for i in range(12):
            month = (4 + i - 1) % 12 + 1  # 4,5,...,12,1,2,3
            year = fiscal_year if month >= 4 else fiscal_year + 1
            labels.append(f"{year}年{month}月")
        return labels
    elif period_type == "semi_annual":
        return ["上期（4月〜9月）", "下期（10月〜3月）"]
    else:  # fiscal_year
        return [f"FY{fiscal_year}"]


def _get_period_key(dt: datetime, period_type: str) -> str | None:
    """
    日付と期間タイプから対応する期間ラベルキーを返す。
    """
    if period_type == "monthly":
        return f"{dt.year}年{dt.month}月"
    elif period_type == "semi_annual":
        half = get_half(dt)
        if half == "first":
            return "上期（4月〜9月）"
        else:
            return "下期（10月〜3月）"
    else:  # fiscal_year
        fy = get_fiscal_year(dt)
        return f"FY{fy}"


def aggregate_node_hours(
    directory: str,
    fiscal_year: int,
    period_type: str,
) -> dict:
    """
    指定ディレクトリの全JSONファイルを読み込み、ノード時間をクロス集計する。
    confidentialフィルタなし（admin専用ページのため全データ対象）。

    Args:
        directory: JSONファイルのあるディレクトリパス
        fiscal_year: 対象会計年度
        period_type: "monthly" | "semi_annual" | "fiscal_year"

    Returns: {
        "apps": [...],
        "systems": [...],
        "periods": [...],
        "table": {app: {system: {period: float}}},
        "row_totals": {app: {period: float}},
        "col_totals": {system: {period: float}},
        "grand_totals": {period: float},
        "available_fiscal_years": [2024, 2025, ...],
    }
    """
    periods = _generate_period_labels(fiscal_year, period_type)

    # 全JSONファイルを走査
    apps_set: set[str] = set()
    systems_set: set[str] = set()
    all_fiscal_years: set[int] = set()

    # table[app][system][period] = float
    table: dict[str, dict[str, dict[str, float]]] = {}

    try:
        files = os.listdir(directory)
    except OSError:
        files = []

    json_files = [f for f in files if f.endswith(".json")]

    for json_file in json_files:
        # タイムスタンプ抽出
        ts = extract_timestamp_from_filename(json_file)
        if ts is None:
            continue

        file_fy = get_fiscal_year(ts)
        all_fiscal_years.add(file_fy)

        # 対象会計年度でなければスキップ
        if file_fy != fiscal_year:
            continue

        # 期間キーを取得
        period_key = _get_period_key(ts, period_type)
        if period_key not in periods:
            continue

        # JSONファイル読み込み
        filepath = os.path.join(directory, json_file)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        app = data.get("code", "")
        system = data.get("system", "")
        if not app or not system:
            continue

        node_hours = compute_node_hours(data)

        apps_set.add(app)
        systems_set.add(system)

        # テーブルに加算
        if app not in table:
            table[app] = {}
        if system not in table[app]:
            table[app][system] = {}
        table[app][system][period_key] = table[app][system].get(period_key, 0.0) + node_hours

    # ソート
    apps = sorted(apps_set)
    systems = sorted(systems_set)

    # 全app×system×periodのセルを初期化（存在しないセルは0.0）
    for app in apps:
        if app not in table:
            table[app] = {}
        for system in systems:
            if system not in table[app]:
                table[app][system] = {}
            for period in periods:
                if period not in table[app][system]:
                    table[app][system][period] = 0.0

    # row_totals: 各appの期間別合計（全systemの合計）
    row_totals: dict[str, dict[str, float]] = {}
    for app in apps:
        row_totals[app] = {}
        for period in periods:
            total = sum(table[app][system][period] for system in systems)
            row_totals[app][period] = round(total, 2)

    # col_totals: 各systemの期間別合計（全appの合計）
    col_totals: dict[str, dict[str, float]] = {}
    for system in systems:
        col_totals[system] = {}
        for period in periods:
            total = sum(table[app][system][period] for app in apps)
            col_totals[system][period] = round(total, 2)

    # grand_totals: 期間別の総合計
    grand_totals: dict[str, float] = {}
    for period in periods:
        total = sum(row_totals[app][period] for app in apps)
        grand_totals[period] = round(total, 2)

    # セル値も丸める
    for app in apps:
        for system in systems:
            for period in periods:
                table[app][system][period] = round(table[app][system][period], 2)

    available_fiscal_years = sorted(all_fiscal_years)

    return {
        "apps": apps,
        "systems": systems,
        "periods": periods,
        "table": table,
        "row_totals": row_totals,
        "col_totals": col_totals,
        "grand_totals": grand_totals,
        "available_fiscal_years": available_fiscal_years,
    }
