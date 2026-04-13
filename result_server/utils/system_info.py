import csv
import os

# system_info.csv のパス（リポジトリルートの config/ を想定）
# 環境変数 SYSTEM_INFO_CSV で上書き可能
_DEFAULT_CSV = os.path.join(
    os.path.dirname(__file__), '..', '..', 'config', 'system_info.csv'
)
SYSTEM_INFO_CSV = os.environ.get('SYSTEM_INFO_CSV', _DEFAULT_CSV)


def _load_csv():
    """CSVファイルからシステム情報を読み込む"""
    info = {}
    order = []
    path = os.path.normpath(SYSTEM_INFO_CSV)

    if not os.path.exists(path):
        return info, order

    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            system = row['system'].strip()
            rows.append((system, row))

        # display_order でソート（数値変換、なければ末尾）
        def sort_key(item):
            try:
                return int(item[1].get('display_order', '999'))
            except (ValueError, TypeError):
                return 999

        rows.sort(key=sort_key)

        for system, row in rows:
            order.append(system)
            info[system] = {
                'name': row.get('name', system).strip(),
                'cpu_name': row.get('cpu_name', '-').strip(),
                'cpu_per_node': row.get('cpu_per_node', '-').strip(),
                'cpu_cores': row.get('cpu_cores', '-').strip(),
                'gpu_name': row.get('gpu_name', '-').strip(),
                'gpu_per_node': row.get('gpu_per_node', '-').strip(),
                'memory': row.get('memory', '-').strip(),
            }

    return info, order


# モジュール読み込み時にCSVをロード
_SYSTEM_INFO, _SYSTEM_ORDER = _load_csv()


def get_system_info(system_name):
    """指定されたシステム名の情報を取得"""
    return _SYSTEM_INFO.get(system_name, {
        'name': system_name,
        'cpu_name': 'Unknown System',
        'cpu_per_node': '-',
        'cpu_cores': '-',
        'gpu_name': '-',
        'gpu_per_node': '-',
        'memory': '-'
    })


def get_all_systems_info():
    """全システム情報を順序付きで取得"""
    ordered = {}
    for name in _SYSTEM_ORDER:
        ordered[name] = _SYSTEM_INFO[name]
    # 順序に含まれていないシステムも追加
    for name, info in _SYSTEM_INFO.items():
        if name not in ordered:
            ordered[name] = info
    return ordered


def summarize_systems_info(systems_info):
    """Return lightweight summary counts for the system list page."""
    total_count = len(systems_info)
    gpu_enabled_count = 0

    for info in systems_info.values():
        gpu_name = (info.get("gpu_name") or "-").strip()
        if gpu_name and gpu_name != "-":
            gpu_enabled_count += 1

    return {
        "total_count": total_count,
        "gpu_enabled_count": gpu_enabled_count,
        "cpu_only_count": total_count - gpu_enabled_count,
    }
