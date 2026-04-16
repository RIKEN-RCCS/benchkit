import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.site_diagnostics import build_site_diagnostics


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_build_site_diagnostics(tmp_path):
    config_dir = tmp_path / "config"
    programs_dir = tmp_path / "programs"
    config_dir.mkdir()
    programs_dir.mkdir()

    _write_csv(
        config_dir / "system.csv",
        ["system", "mode", "tag_build", "tag_run", "queue", "queue_group"],
        [
            ["Fugaku", "cross", "", "", "FJ", "small"],
            ["RC_TEST", "native", "", "", "SLURM_UNKNOWN", "debug"],
            ["RC_PARTIAL", "native", "", "", "none", "small"],
        ],
    )
    _write_csv(
        config_dir / "queue.csv",
        ["queue", "submit_cmd", "template"],
        [
            ["FJ", "pjsub", "template"],
            ["none", "none", "none"],
        ],
    )
    _write_csv(
        config_dir / "system_info.csv",
        ["system", "name", "cpu_name", "cpu_per_node", "cpu_cores", "gpu_name", "gpu_per_node", "memory", "display_order"],
        [
            ["Fugaku", "Fugaku", "A64FX", "1", "48", "-", "-", "32GB", "1"],
            ["RC_PARTIAL", "RC_PARTIAL", "CPU", "1", "16", "-", "-", "64GB", "2"],
        ],
    )

    qws_dir = programs_dir / "qws"
    qws_dir.mkdir()
    (qws_dir / "build.sh").write_text(
        "case \"$system\" in\nFugaku|RC_PARTIAL)\n  echo build\n  ;;\nesac\n",
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
            ["RC_PARTIAL", "yes", "1", "1", "16", "0:10:00"],
            ["RC_TEST", "no", "1", "1", "16", "0:10:00"],
        ],
    )
    (qws_dir / "estimate.sh").write_text("#!/bin/bash\n", encoding="utf-8")

    genesis_dir = programs_dir / "genesis"
    genesis_dir.mkdir()
    (genesis_dir / "build.sh").write_text("echo build\n", encoding="utf-8")
    _write_csv(
        genesis_dir / "list.csv",
        ["system", "enable", "nodes", "numproc_node", "nthreads", "elapse"],
        [
            ["UNKNOWN_SYSTEM", "yes", "1", "1", "16", "0:10:00"],
        ],
    )

    diagnostics = build_site_diagnostics(
        system_csv_path=str(config_dir / "system.csv"),
        queue_csv_path=str(config_dir / "queue.csv"),
        system_info_csv_path=str(config_dir / "system_info.csv"),
        programs_dir=str(programs_dir),
    )

    assert diagnostics["registered_system_count"] == 3
    assert diagnostics["application_count"] == 2
    assert diagnostics["application_directory_count"] == 2
    assert diagnostics["missing_system_info"] == ["RC_TEST"]
    assert diagnostics["missing_queue_definitions"] == [
        {"system": "RC_TEST", "queue": "SLURM_UNKNOWN"}
    ]
    assert diagnostics["unused_systems"] == ["RC_TEST", "RC_PARTIAL"]
    assert diagnostics["partial_support"] == [
        {
            "app": "qws",
            "system": "RC_PARTIAL",
            "build_supported": True,
            "run_supported": False,
            "enabled_rows": 1,
        }
    ]
    assert diagnostics["apps_missing_files"] == [
        {
            "app": "genesis",
            "missing_files": ["run.sh"],
        }
    ]
    assert diagnostics["apps_with_estimate_count"] == 1
    assert diagnostics["apps_without_estimate"] == ["genesis"]
    assert diagnostics["unknown_listed_systems"] == [
        {
            "app": "genesis",
            "system": "UNKNOWN_SYSTEM",
            "enabled_rows": 1,
            "disabled_rows": 0,
        }
    ]
