"""Mock acquisition only: no network, real uv, container, or training."""

from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "programs/omnilearned/build.sh"
DIGEST = "28d4385f9f9d1d1c7654d85b3855e0e2615b2f6cc13136a2edff858bbdc16ff1"


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
    path.chmod(0o700)


@pytest.mark.parametrize("mode", ["success", "mismatch", "hash_failure", "download_failure", "extract_failure", "uv_failure", "missing_python"])
def test_build_checks_archive_before_extraction_and_execution(tmp_path, mode):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    # Use the real shared hash verifier; only the hash command is mocked.
    (scripts / "bk_functions.sh").write_text(
        'source "$TEST_ROOT/scripts/common/source.sh"\n'
        'bk_fetch_source() { mkdir -p OmniLearned/src/omnilearned; '
        'printf "Train pass wall\\n" > OmniLearned/src/omnilearned/train.py; }\n')
    tools = tmp_path / "tools"
    log = tmp_path / "calls"
    executable(tools / "git", 'echo git >> "$CALL_LOG"\n')
    executable(tools / "curl", '''
echo curl >> "$CALL_LOG"
[[ "$*" == *releases/download/0.13.4/uv-x86_64-unknown-linux-musl.tar.gz* ]]
[[ "$3" == --output ]]
[[ "$MODE" != download_failure ]] || exit 22
printf 'synthetic archive' > "$4"
printf '%s' "$4" > "$ARCHIVE_PATH"
''')
    executable(tools / "sha256sum", '''
echo hash >> "$CALL_LOG"
[[ "$1" == "$(/usr/bin/cat "$ARCHIVE_PATH")" ]]
[[ "$(/usr/bin/cat "$1")" == 'synthetic archive' ]]
[[ "$MODE" != hash_failure ]] || exit 1
if [[ "$MODE" == mismatch ]]; then
  printf '%064d  %s\\n' 0 "$1"
else
  printf '%s  %s\\n' "$EXPECTED_DIGEST" "$1"
fi
''')
    # A stale executable must not be used if the new archive fails validation.
    uv = tmp_path / "artifacts/uv-x86_64-unknown-linux-musl/uv"
    executable(uv, '''
echo stale_uv >> "$CALL_LOG"
exit 98
''')
    stale_contents = uv.read_bytes()
    new_uv = tmp_path / "fixture/new-uv"
    executable(new_uv, '''
echo new_uv >> "$CALL_LOG"
printf '%s\\n' "$@" > "$UV_ARGS"
[[ "$UV_PYTHON_DOWNLOADS" == never ]]
[[ "$UV_PYTHON" == "$EXPECTED_PYTHON" ]]
if [[ "$MODE" == missing_python ]]; then
  echo 'No suitable Python interpreter found; Python downloads are disabled' >&2
  exit 2
fi
[[ "$MODE" != uv_failure ]] || exit 9
''')
    executable(tools / "tar", '''
echo tar >> "$CALL_LOG"
[[ "$1" == xzf && "$3" == -C ]]
[[ "$2" == "$(/usr/bin/cat "$ARCHIVE_PATH")" ]]
[[ "$4" == "$EXPECTED_ARTIFACT_DIR" ]]
[[ "$MODE" != extract_failure ]] || exit 2
mkdir -p "$4/uv-x86_64-unknown-linux-musl"
cp "$NEW_UV" "$4/uv-x86_64-unknown-linux-musl/uv"
chmod 700 "$4/uv-x86_64-unknown-linux-musl/uv"
''')
    for command in ("wget", "ssh", "singularity", "apptainer", "python3", "pip"):
        executable(tools / command, 'echo forbidden >> "$CALL_LOG"\nexit 99\n')
    image = tmp_path / "synthetic.sif"
    image.write_bytes(b"not a SIF")
    args = tmp_path / "uv-args"
    env = {"PATH": str(tools) + ":/usr/bin:/bin", "HOME": str(tmp_path),
           "TEST_ROOT": str(ROOT), "CALL_LOG": str(log), "MODE": mode,
           "EXPECTED_DIGEST": DIGEST, "UV_ARGS": str(args),
           "ARCHIVE_PATH": str(tmp_path / "downloaded-archive"),
           "EXPECTED_ARTIFACT_DIR": str(tmp_path / "artifacts"), "NEW_UV": str(new_uv),
           "BK_OMNILEARNED_SIF": str(image),
           "UV_PYTHON_DOWNLOADS": "automatic",
           "UV_PYTHON": str(tmp_path / "existing-python"),
           "EXPECTED_PYTHON": str(tmp_path / "existing-python")}
    result = subprocess.run(["bash", str(BUILD), "Fugaku"], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=10)
    calls = log.read_text().splitlines()
    assert "forbidden" not in calls
    assert "stale_uv" not in calls
    assert (result.returncode == 0) == (mode == "success"), result.stderr
    if mode in ("mismatch", "hash_failure", "download_failure"):
        assert "tar" not in calls
        assert "new_uv" not in calls
        assert uv.read_bytes() == stale_contents
    elif mode == "extract_failure":
        assert calls[-1] == "tar"
        assert "new_uv" not in calls
        assert uv.read_bytes() == stale_contents
    else:
        assert calls.index("curl") < calls.index("hash") < calls.index("tar") < calls.index("new_uv")
        assert uv.read_bytes() == new_uv.read_bytes()
        assert args.read_text().splitlines() == [
            "pip", "install", "--no-python-downloads", "--target", str(tmp_path / "artifacts/pydeps"),
            "--python-platform", "aarch64-manylinux_2_28", "--python-version", "3.10",
            "--no-deps", "--no-build", "-r", str(BUILD.parent / "fugaku-requirements.txt"),
        ]
    archives = list((tmp_path / "artifacts").glob("uv-0.13.4.*.tar.gz"))
    assert len(archives) == (1 if mode in ("download_failure", "mismatch", "hash_failure", "extract_failure") else 0)
    if mode == "mismatch":
        assert "sha256 mismatch" in result.stderr
    if mode in ("uv_failure", "missing_python"):
        assert result.returncode == (2 if mode == "missing_python" else 9)
        assert not (tmp_path / "OmniLearned/src/omnilearned/_version.py").exists()
        assert not list(tmp_path.glob("artifacts/top_medium_pretrain*.yaml"))
    if mode == "missing_python":
        assert "Python downloads are disabled" in result.stderr
