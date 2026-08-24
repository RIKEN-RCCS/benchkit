"""Static checks for environment snapshot CI integration."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_matrix_generator_collects_snapshots_in_common_wrappers():
    matrix_generate = (REPO_ROOT / "scripts" / "matrix_generate.sh").read_text(
        encoding="utf-8"
    )

    assert "BK_SNAPSHOT_STAGE=build bash scripts/collect_environment_snapshot.sh" in matrix_generate
    assert "BK_SNAPSHOT_STAGE=run bash scripts/collect_environment_snapshot.sh" in matrix_generate
    assert (
        "BK_SNAPSHOT_STAGE=build_run bash scripts/collect_environment_snapshot.sh"
        in matrix_generate
    )
    assert "export BK_BENCHKIT_ROOT=" in matrix_generate
    assert "scripts/build_tool_wrappers" in matrix_generate


def test_send_results_process_does_not_collect_send_stage_snapshot():
    process_script = (
        REPO_ROOT / "scripts" / "result_server" / "process_and_send_results.sh"
    ).read_text(encoding="utf-8")

    assert "collect_environment_snapshot.sh" not in process_script
