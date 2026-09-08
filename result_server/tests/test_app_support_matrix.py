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
            ["DemoSystem", "cross", "", "", "FJ", "small"],
            ["CpuSystem", "native", "", "", "SLURM_RC", "genoa"],
        ],
    )

    demoapp_dir = programs_dir / "demoapp"
    demoapp_dir.mkdir()
    (demoapp_dir / "build.sh").write_text(
        "case \"$system\" in\nDemoSystem|CpuSystem)\n  echo build\n  ;;\nesac\n",
        encoding="utf-8",
    )
    (demoapp_dir / "run.sh").write_text(
        "case \"$system\" in\nDemoSystem)\n  echo run\n  ;;\nesac\n",
        encoding="utf-8",
    )
    _write_csv(
        demoapp_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [
            ["DemoSystem", "yes", "1", "4", "12", "0:10:00"],
            ["CpuSystem", "no", "1", "1", "96", "0:10:00"],
        ],
    )

    auxapp_dir = programs_dir / "auxapp"
    auxapp_dir.mkdir()
    (auxapp_dir / "build.sh").write_text("echo build\n", encoding="utf-8")
    (auxapp_dir / "run.sh").write_text("echo run\n", encoding="utf-8")
    _write_csv(
        auxapp_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [
            ["CpuSystem", "yes", "1", "1", "1", "0:10:00"],
        ],
    )

    systems, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    assert systems == ["DemoSystem", "CpuSystem"]
    assert [row["app"] for row in rows] == ["auxapp", "demoapp"]
    assert rows[0]["systems"]["DemoSystem"]["status"] == "not_listed"
    assert rows[0]["systems"]["CpuSystem"]["status"] == "enabled_partial"
    assert rows[0]["systems"]["CpuSystem"]["build_supported"] is False
    assert rows[0]["systems"]["CpuSystem"]["run_supported"] is False
    assert rows[1]["systems"]["DemoSystem"]["status"] == "enabled"
    assert rows[1]["systems"]["DemoSystem"]["build_supported"] is True
    assert rows[1]["systems"]["DemoSystem"]["run_supported"] is True
    assert rows[1]["systems"]["CpuSystem"]["status"] == "configured_off"


def test_support_matrix_ignores_comment_only_mentions(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [["CpuSystem", "native", "", "", "SLURM_RC", "genoa"]],
    )

    app_dir = programs_dir / "sample"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text("# TODO: support CpuSystem later\n", encoding="utf-8")
    (app_dir / "run.sh").write_text("echo run\n", encoding="utf-8")
    _write_csv(
        app_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [["CpuSystem", "yes", "1", "1", "1", "0:10:00"]],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    assert rows[0]["systems"]["CpuSystem"]["status"] == "enabled_partial"
    assert rows[0]["systems"]["CpuSystem"]["build_supported"] is False
    assert rows[0]["systems"]["CpuSystem"]["run_supported"] is False


def test_support_matrix_handles_nested_case_blocks(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [
            ["DemoSystem", "cross", "", "", "FJ", "small"],
            ["GpuSystem", "native", "", "", "SLURM_RC", "gh200"],
            ["PeerSystem", "cross", "", "", "SLURM", "small"],
        ],
    )

    app_dir = programs_dir / "demoapp"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text("echo build\n", encoding="utf-8")
    (app_dir / "run.sh").write_text(
        """case "$system" in
    DemoSystem|DemoSystemCN)
        case "$nodes" in
            1)
                echo run
                ;;
        esac
        ;;
    GpuSystem)
        echo gh200
        ;;
    PeerSystem|PeerSystemC)
        echo miyabi
        ;;
esac
""",
        encoding="utf-8",
    )
    _write_csv(
        app_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [
            ["DemoSystem", "yes", "1", "4", "12", "0:10:00"],
            ["GpuSystem", "yes", "1", "1", "72", "0:10:00"],
            ["PeerSystem", "yes", "1", "1", "72", "0:10:00"],
        ],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    systems = rows[0]["systems"]
    assert systems["DemoSystem"]["run_supported"] is True
    assert systems["GpuSystem"]["run_supported"] is True
    assert systems["PeerSystem"]["run_supported"] is True


def test_support_matrix_handles_space_before_case_paren(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [["PeerSystem", "cross", "", "", "SLURM", "small"]],
    )

    app_dir = programs_dir / "LQCD_dw_solver"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text("echo build\n", encoding="utf-8")
    (app_dir / "run.sh").write_text(
        """case "$system" in
  PeerSystem )
      echo run
      ;;
esac
""",
        encoding="utf-8",
    )
    _write_csv(
        app_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [["PeerSystem", "yes", "1", "1", "2", "0:10:00"]],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    assert rows[0]["systems"]["PeerSystem"]["run_supported"] is True


def test_support_matrix_handles_prefix_wildcards(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [
            ["DemoSystem", "cross", "", "", "FJ", "small"],
            ["DemoSystemCN", "native", "", "", "FJ", "small"],
            ["PeerSystem", "cross", "", "", "SLURM", "small"],
            ["PeerSystemC", "cross", "", "", "SLURM", "small"],
        ],
    )

    app_dir = programs_dir / "LQCD_dw_solver"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text(
        """case "$system" in
  DemoSystem*|PeerSystem*)
      echo prep
      ;;
esac
""",
        encoding="utf-8",
    )
    (app_dir / "run.sh").write_text("echo run\n", encoding="utf-8")
    _write_csv(
        app_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [
            ["DemoSystem", "yes", "1", "1", "12", "0:10:00"],
            ["DemoSystemCN", "yes", "1", "1", "12", "0:10:00"],
            ["PeerSystem", "yes", "1", "1", "2", "0:10:00"],
            ["PeerSystemC", "yes", "1", "1", "56", "0:10:00"],
        ],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    systems = rows[0]["systems"]
    assert systems["DemoSystem"]["build_supported"] is True
    assert systems["DemoSystemCN"]["build_supported"] is True
    assert systems["PeerSystem"]["build_supported"] is True
    assert systems["PeerSystemC"]["build_supported"] is True
