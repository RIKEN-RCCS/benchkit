import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.app_support_matrix import load_app_system_support_matrix


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_load_app_system_support_matrix(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [
            ["Fugaku", "cross", "", "", "FJ", "small"],
            ["RC_GENOA", "native", "", "", "SLURM_RC", "genoa"],
        ],
    )

    qws_dir = programs_dir / "qws"
    qws_dir.mkdir()
    _write_csv(
        qws_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [
            ["Fugaku", "yes", "1", "4", "12", "0:10:00"],
            ["RC_GENOA", "no", "1", "1", "96", "0:10:00"],
        ],
    )

    genesis_dir = programs_dir / "genesis"
    genesis_dir.mkdir()
    _write_csv(
        genesis_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [
            ["RC_GENOA", "yes", "1", "1", "1", "0:10:00"],
        ],
    )

    systems, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    assert systems == ["Fugaku", "RC_GENOA"]
    assert [row["app"] for row in rows] == ["genesis", "qws"]
    assert rows[0]["systems"]["Fugaku"]["status"] == "not_listed"
    assert rows[0]["systems"]["RC_GENOA"]["status"] == "enabled"
    assert rows[1]["systems"]["Fugaku"]["status"] == "enabled"
    assert rows[1]["systems"]["RC_GENOA"]["status"] == "configured_off"
