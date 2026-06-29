"""Static checks for source_info handoff scripts."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_result_script_does_not_source_source_info_env():
    result_script = (REPO_ROOT / "scripts" / "result.sh").read_text(encoding="utf-8")

    assert ". results/source_info.env" not in result_script
    assert "source results/source_info.env" not in result_script
    assert "build_source_info_block" in result_script
    assert "jq -n" in result_script


def test_result_script_does_not_source_timing_env():
    result_script = (REPO_ROOT / "scripts" / "result.sh").read_text(encoding="utf-8")

    assert ". results/timing.env" not in result_script
    assert "source results/timing.env" not in result_script
    assert "results/pipeline_timing.json" in result_script


def test_bk_fetch_source_writes_encoded_source_info_values():
    bk_functions = (REPO_ROOT / "scripts" / "bk_functions.sh").read_text(encoding="utf-8")

    assert "BK_SOURCE_INFO_FORMAT=base64-v1" in bk_functions
    assert "BK_REPO_URL_B64" in bk_functions
    assert "BK_FILE_PATH_B64" in bk_functions
    assert 'export BK_REPO_URL="$BK_REPO_URL"' not in bk_functions
    assert 'export BK_FILE_PATH="$BK_FILE_PATH"' not in bk_functions
