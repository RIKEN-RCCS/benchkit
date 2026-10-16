import csv
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_INFO_CSV = REPO_ROOT / "config" / "system_info.csv"

COMPACT_MEMORY_UNIT_RE = re.compile(r"\d(?:\.\d+)?(?:GB|GiB|TB|TiB)\b")


def _load_system_info_rows():
    with SYSTEM_INFO_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_system_info_required_fields_and_unique_system_ids():
    rows = _load_system_info_rows()
    assert rows
    required = {"system", "name", "cpu_name", "cpu_per_node", "cpu_cores",
                "gpu_name", "gpu_per_node", "memory", "display_order"}
    for row in rows:
        assert required <= row.keys()
        assert all(row[key] is not None and row[key].strip() for key in required)
        int(row["display_order"])
    systems = [row["system"].strip() for row in rows]
    assert len(systems) == len(set(systems))


def test_system_info_loader_sorts_sparse_orders_and_preserves_names(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "result_server"))
    from utils import system_info

    path = tmp_path / "system_info.csv"
    rows = [
        {"system": "Later", "display_order": "40", "gpu_name": "GPU SXM5 144 GB (HBM3e)"},
        {"system": "First", "display_order": "10", "gpu_name": "GPU PCIe 96 GB (HBM3)"},
        {"system": "SameOrder", "display_order": "10", "gpu_name": "-"},
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["system", "display_order", "gpu_name"])
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(system_info, "SYSTEM_INFO_CSV", str(path))
    info, order = system_info._load_csv()
    assert order == ["First", "SameOrder", "Later"]
    for row in rows:
        assert info[row["system"]]["gpu_name"] == row["gpu_name"]
    monkeypatch.setattr(system_info, "_SYSTEM_INFO", info)
    monkeypatch.setattr(system_info, "_SYSTEM_ORDER", order)
    assert list(system_info.get_all_systems_info()) == order


def test_system_info_uses_readable_memory_unit_spacing():
    rows = _load_system_info_rows()

    for row in rows:
        for column in ("gpu_name", "memory"):
            value = row[column]
            assert not COMPACT_MEMORY_UNIT_RE.search(value), (
                f"{row['system']} {column} should use readable unit spacing: {value}"
            )


def test_system_info_has_no_html_markup():
    rows = _load_system_info_rows()

    for row in rows:
        for column in ("name", "cpu_name", "gpu_name", "memory"):
            value = row[column]
            assert "<" not in value and ">" not in value, (
                f"{row['system']} {column} should be plain text: {value}"
            )


def test_system_info_uses_spaced_vector_type_names():
    rows = _load_system_info_rows()

    for row in rows:
        gpu_name = row["gpu_name"]
        assert "Type20" not in gpu_name and "Type30" not in gpu_name, (
            f"{row['system']} gpu_name should spell VE type with a space: {gpu_name}"
        )
