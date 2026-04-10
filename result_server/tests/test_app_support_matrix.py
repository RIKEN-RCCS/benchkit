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
    (qws_dir / "build.sh").write_text(
        "case \"$system\" in\nFugaku|RC_GENOA)\n  echo build\n  ;;\nesac\n",
        encoding="utf-8",
    )
    (qws_dir / "run.sh").write_text(
        "case \"$system\" in\nFugaku)\n  echo run\n  ;;\nesac\n",
        encoding="utf-8",
    )
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
    (genesis_dir / "build.sh").write_text("echo build\n", encoding="utf-8")
    (genesis_dir / "run.sh").write_text("echo run\n", encoding="utf-8")
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
    assert rows[0]["systems"]["RC_GENOA"]["status"] == "enabled_partial"
    assert rows[0]["systems"]["RC_GENOA"]["build_supported"] is False
    assert rows[0]["systems"]["RC_GENOA"]["run_supported"] is False
    assert rows[1]["systems"]["Fugaku"]["status"] == "enabled"
    assert rows[1]["systems"]["Fugaku"]["build_supported"] is True
    assert rows[1]["systems"]["Fugaku"]["run_supported"] is True
    assert rows[1]["systems"]["RC_GENOA"]["status"] == "configured_off"


def test_support_matrix_ignores_comment_only_mentions(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [["RC_GENOA", "native", "", "", "SLURM_RC", "genoa"]],
    )

    app_dir = programs_dir / "sample"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text("# TODO: support RC_GENOA later\n", encoding="utf-8")
    (app_dir / "run.sh").write_text("echo run\n", encoding="utf-8")
    _write_csv(
        app_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [["RC_GENOA", "yes", "1", "1", "1", "0:10:00"]],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    assert rows[0]["systems"]["RC_GENOA"]["status"] == "enabled_partial"
    assert rows[0]["systems"]["RC_GENOA"]["build_supported"] is False
    assert rows[0]["systems"]["RC_GENOA"]["run_supported"] is False


def test_support_matrix_handles_nested_case_blocks(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [
            ["Fugaku", "cross", "", "", "FJ", "small"],
            ["RC_GH200", "native", "", "", "SLURM_RC", "gh200"],
            ["MiyabiG", "cross", "", "", "SLURM", "small"],
        ],
    )

    app_dir = programs_dir / "qws"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text("echo build\n", encoding="utf-8")
    (app_dir / "run.sh").write_text(
        """case "$system" in
    Fugaku|FugakuCN)
        case "$nodes" in
            1)
                echo run
                ;;
        esac
        ;;
    RC_GH200)
        echo gh200
        ;;
    MiyabiG|MiyabiC)
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
            ["Fugaku", "yes", "1", "4", "12", "0:10:00"],
            ["RC_GH200", "yes", "1", "1", "72", "0:10:00"],
            ["MiyabiG", "yes", "1", "1", "72", "0:10:00"],
        ],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    systems = rows[0]["systems"]
    assert systems["Fugaku"]["run_supported"] is True
    assert systems["RC_GH200"]["run_supported"] is True
    assert systems["MiyabiG"]["run_supported"] is True


def test_support_matrix_handles_space_before_case_paren(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [["MiyabiG", "cross", "", "", "SLURM", "small"]],
    )

    app_dir = programs_dir / "LQCD_dw_solver"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text("echo build\n", encoding="utf-8")
    (app_dir / "run.sh").write_text(
        """case "$system" in
  MiyabiG )
      echo run
      ;;
esac
""",
        encoding="utf-8",
    )
    _write_csv(
        app_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [["MiyabiG", "yes", "1", "1", "2", "0:10:00"]],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    assert rows[0]["systems"]["MiyabiG"]["run_supported"] is True


def test_support_matrix_handles_prefix_wildcards(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [
            ["Fugaku", "cross", "", "", "FJ", "small"],
            ["FugakuCN", "native", "", "", "FJ", "small"],
            ["MiyabiG", "cross", "", "", "SLURM", "small"],
            ["MiyabiC", "cross", "", "", "SLURM", "small"],
        ],
    )

    app_dir = programs_dir / "LQCD_dw_solver"
    app_dir.mkdir()
    (app_dir / "build.sh").write_text(
        """case "$system" in
  Fugaku*|Miyabi*)
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
            ["Fugaku", "yes", "1", "1", "12", "0:10:00"],
            ["FugakuCN", "yes", "1", "1", "12", "0:10:00"],
            ["MiyabiG", "yes", "1", "1", "2", "0:10:00"],
            ["MiyabiC", "yes", "1", "1", "56", "0:10:00"],
        ],
    )

    _, rows = load_app_system_support_matrix(
        programs_dir=str(programs_dir),
        system_csv_path=str(config_dir / "system.csv"),
    )

    systems = rows[0]["systems"]
    assert systems["Fugaku"]["build_supported"] is True
    assert systems["FugakuCN"]["build_supported"] is True
    assert systems["MiyabiG"]["build_supported"] is True
    assert systems["MiyabiC"]["build_supported"] is True
