import csv
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_INFO_CSV = REPO_ROOT / "config" / "system_info.csv"

COMPACT_MEMORY_UNIT_RE = re.compile(r"\d(?:\.\d+)?(?:GB|GiB|TB|TiB)\b")
MEMORY_CAPACITY_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:GB|GiB|TB|TiB)\b")
GPU_FORM_FACTOR_RE = re.compile(r"\b(?:PCIe|SXM\d*)\b")


def _load_system_info_rows():
    with SYSTEM_INFO_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_system_info_display_order_is_consecutive():
    rows = _load_system_info_rows()

    display_order = [int(row["display_order"]) for row in rows]

    assert display_order == list(range(1, len(rows) + 1))


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


def test_system_info_cpu_gpu_names_avoid_parenthetical_codenames():
    rows = _load_system_info_rows()

    for row in rows:
        for column in ("cpu_name", "gpu_name"):
            value = row[column]
            assert "(" not in value and ")" not in value, (
                f"{row['system']} {column} should use vendor and model only: {value}"
            )


def test_system_info_gpu_names_avoid_form_factor_and_memory_capacity():
    rows = _load_system_info_rows()

    for row in rows:
        value = row["gpu_name"]
        assert not GPU_FORM_FACTOR_RE.search(value), (
            f"{row['system']} gpu_name should omit interconnect/form factor details: {value}"
        )
        assert not MEMORY_CAPACITY_RE.search(value), (
            f"{row['system']} gpu_name should omit memory capacity details: {value}"
        )


def test_system_info_uses_spaced_vector_type_names():
    rows = _load_system_info_rows()

    for row in rows:
        gpu_name = row["gpu_name"]
        assert "Type20" not in gpu_name and "Type30" not in gpu_name, (
            f"{row['system']} gpu_name should spell VE type with a space: {gpu_name}"
        )
