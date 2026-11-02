"""Local Git and synthetic dependencies/launchers; no downloads or training."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "programs/omnilearned"


def command(args, *, cwd, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                          timeout=45, check=check)


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
    path.chmod(0o755)


@pytest.fixture
def fixture(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    command(["git", "init", "-qb", "main"], cwd=origin)
    # Reconstruct only the old hunk contexts, not the real upstream program.
    lines = ["# synthetic training source\n"] * 420
    offset = None
    for line in (APP / "patches/train_pass_timer.patch").read_text().splitlines(True):
        match = re.match(r"@@ -(\d+)", line)
        if match:
            offset = int(match[1]) - 1
        elif offset is not None and line.startswith((" ", "-")):
            lines[offset] = line[1:]
            offset += 1
    source = origin / "src/omnilearned"
    source.mkdir(parents=True)
    (source / "train.py").write_text("".join(lines))
    (source / "__init__.py").write_text("MARKER = 'synthetic adopted source'\n")
    command(["git", "add", "."], cwd=origin)
    command(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
             "commit", "-qm", "synthetic source"], cwd=origin)
    sha = command(["git", "rev-parse", "HEAD"], cwd=origin).stdout.strip()
    tools = tmp_path / "tools"
    tools.mkdir()
    work = tmp_path / "build"
    work.mkdir()
    (work / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    (work / "programs").symlink_to(ROOT / "programs", target_is_directory=True)
    trace = tmp_path / "trace"
    launcher = tmp_path / "launcher"
    executable(launcher, '''
[[ "$1 $2" == '-m torch.distributed.run' ]] || exit 88
"$REAL_PYTHON" -B -c 'import omnilearned; from pathlib import Path; import os; p=Path(omnilearned.__file__); assert ".runtime." in str(p); assert omnilearned.MARKER == "synthetic adopted source"; assert "Train pass wall" in p.with_name("train.py").read_text(); Path(os.environ["IMPORT_TRACE"]).write_text(str(p))'
[[ "${LAUNCH_FAILURE:-0}" == 0 ]] || exit "$LAUNCH_FAILURE"
echo 'Train pass wall: 2.0 sec'
echo 'Training Complete'
''')
    executable(tools / "git", '''
if [[ "$1" == clone && "$2" == --no-checkout ]]; then
  [[ "${FAIL_CLONE:-0}" == 0 ]] || exit 21
  exec "$REAL_GIT" clone --no-checkout -- "$LOCAL_ORIGIN" "${@: -1}"
fi
if [[ "$1" == clone ]]; then
  target="${@: -1}"
  mkdir -p "$target/fugaku"
  printf '#!/bin/bash\\nexit 0\\n' > "$target/fugaku/pf-setup"
  chmod +x "$target/fugaku/pf-setup"
  exit 0
fi
if [[ "$1" == -C && "$2" == */pytorch-fugaku ]]; then exit 0; fi
exec "$REAL_GIT" "$@"
''')
    executable(tools / "python3", '''
if [[ "${1:-}" == -m && "${2:-}" == venv ]]; then
  mkdir -p "$3/bin"
  cp "$FAKE_LAUNCHER" "$3/bin/python"
  printf '#!/bin/bash\\nset -e\\nprintf "pip %%s\\n" "$*" >> "$TRACE"\\n[[ "${FAIL_PIP:-0}" == 0 ]] || exit 29\\n' > "$3/bin/pip"
  chmod +x "$3/bin/pip"
else
  exec "$REAL_PYTHON" -B "$@"
fi
''')
    executable(tools / "curl", '''
[[ "$1" == -sSfL && "$3" == --output ]]
printf 'fake uv archive' > "$4"
''')
    executable(tools / "sha256sum", '''
if [[ "${1:-}" == *uv-0.13.4.*.tar.gz ]]; then
  printf '%s  %s\\n' 28d4385f9f9d1d1c7654d85b3855e0e2615b2f6cc13136a2edff858bbdc16ff1 "$1"
else
  exec "$REAL_SHA256" "$@"
fi
''')
    executable(tools / "tar", '''
[[ "$1" == xzf && "$3" == -C ]]
mkdir -p "$4/uv-x86_64-unknown-linux-musl"
printf '#!/bin/bash\\nset -e\\n[[ "$UV_PYTHON_DOWNLOADS" == never ]]\\nprintf "uv %%s\\n" "$*" >> "$TRACE"\\n' > "$4/uv-x86_64-unknown-linux-musl/uv"
chmod +x "$4/uv-x86_64-unknown-linux-musl/uv"
''')
    executable(tools / "mpiexec", r'''
[[ "$PYTHONPATH" == /work/artifacts/pydeps:/work/.runtime.*/payload/src ]]
export PYTHONPATH="${PYTHONPATH//\/work\//$PWD/}"
"$FAKE_LAUNCHER" -m torch.distributed.run > train.log 2>&1
''')
    executable(tools / "scontrol", "printf 'synthetic-node\\n'\n")
    executable(tools / "srun", '''
[[ "$1 $2" == '--ntasks=2 --ntasks-per-node=1' ]]
shift 2
exec "$@"
''')
    for name in ("wget", "ssh", "singularity", "apptainer", "sbatch", "pjsub"):
        executable(tools / name, "exit 99\n")
    data = tmp_path / "input/top/train"
    data.mkdir(parents=True)
    (data / "fixture.h5").write_bytes(b"synthetic input")
    image = tmp_path / "fake.sif"
    image.write_bytes(b"synthetic image, never executed")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BK_", "_BK_", "PYTHON"))}
    env.update(PATH=str(tools) + os.pathsep + os.environ["PATH"], HOME=str(tmp_path),
               LOCAL_ORIGIN=str(origin), REAL_GIT=shutil.which("git"),
               REAL_SHA256=shutil.which("sha256sum"), REAL_PYTHON=sys.executable,
               FAKE_LAUNCHER=str(launcher), TRACE=str(trace),
               IMPORT_TRACE=str(tmp_path / "imported"), BK_FETCH_EXPECTED_COMMIT=sha,
               BK_OMNILEARNED_DATA=str(data.parent.parent), BK_OMNILEARNED_SIF=str(image),
               BK_BUILD_CACHE_DIR=str(tmp_path / "cache"), BK_BUILD_CACHE_ENV_KEY="synthetic",
               SLURM_JOB_NODELIST="synthetic-node", SLURM_NODEID="0")
    return work, origin, sha, env


def build(work, env, system="RIKYU", cache=False):
    script = (["scripts/build_with_cache.sh", "omnilearned", system, "programs/omnilearned"]
              if cache else [str(APP / "build.sh"), system])
    return command(["bash", *script], cwd=work, env=env, check=False)


@pytest.mark.parametrize("system,nodes", [("RIKYU", 1), ("RIKYU", 2), ("RC_GH200", 1),
                                        ("RC_GENOA", 1), ("RC_DGXSP", 1), ("Fugaku", 1)])
def test_fresh_source_patch_and_offline_runtime(fixture, system, nodes):
    work, origin, sha, env = fixture
    old = work / "OmniLearned"
    old.mkdir()
    (old / "sentinel").write_text("old checkout is untouched")
    result = build(work, env, system)
    assert result.returncode == 0, result.stdout + result.stderr
    package = work / "artifacts/runtime"
    record = json.loads((package / "build.json").read_text())
    adjustment, = record["adjustments"]
    assert adjustment["status"] == "applied"
    assert adjustment["before_sha256"] != adjustment["after_sha256"]
    assert hashlib.sha256((package / "payload/src/omnilearned/train.py").read_bytes()).hexdigest() == adjustment["after_sha256"]
    metadata = dict(line.split("=", 1) for line in (package / "source_info.env").read_text().splitlines())
    assert base64.b64decode(metadata["BK_SOURCE_RESOLVED_COMMIT_B64"]).decode() == sha
    assert base64.b64decode(metadata["BK_REPO_URL_B64"]).decode() == "https://github.com/ViniciusMikuni/OmniLearned.git"
    assert not (package / "payload/.git").exists()
    if system == "Fugaku":
        assert (package / "payload/src/omnilearned/_version.py").is_file()
    # Remove the entire acquisition workspace and origin before running.
    for path in work.glob(".source-build.*"):
        shutil.rmtree(path)
    origin.rename(origin.with_name("unavailable"))
    result = command(["bash", str(ROOT / "scripts/run_benchmark.sh"), str(APP / "run.sh"),
                      system, str(nodes), "1", "2"], cwd=work, env=env, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (old / "sentinel").read_text() == "old checkout is untouched"
    assert ".runtime." in Path(env["IMPORT_TRACE"]).read_text()
    assert "FOM:" in (work / "results/result").read_text()
    assert json.loads((work / "results/build_provenance.json").read_text()) == record


@pytest.mark.parametrize("failure", ["clone", "patch", "pip"])
def test_failed_build_does_not_publish_previous_runtime(fixture, failure):
    work, origin, sha, env = fixture
    assert build(work, env).returncode == 0
    if failure == "patch":
        (origin / "src/omnilearned/train.py").write_text("Train pass wall is not a patch\n")
        command(["git", "add", "."], cwd=origin)
        command(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "incompatible"], cwd=origin)
        env["BK_FETCH_EXPECTED_COMMIT"] = command(["git", "rev-parse", "HEAD"], cwd=origin).stdout.strip()
    else:
        env["FAIL_" + failure.upper()] = "1"
    result = build(work, env)
    assert result.returncode != 0
    assert not (work / "artifacts/runtime").exists()
    if failure == "patch":
        record = json.loads((work / "results/build_provenance.json").read_text())
        assert record["adjustments"][0]["status"] == "failed"


@pytest.mark.parametrize("change", ["changed", "missing", "link"])
def test_runtime_rejects_untrusted_source_before_launcher(fixture, change):
    work, _, _, env = fixture
    assert build(work, env).returncode == 0
    path = work / "artifacts/runtime/payload/src/omnilearned/train.py"
    if change == "changed":
        path.write_text("changed")
    else:
        path.unlink()
        if change == "link":
            path.symlink_to(work / "OmniLearned/train.py")
    result = command(["bash", str(ROOT / "scripts/run_benchmark.sh"), str(APP / "run.sh"),
                      "RIKYU", "1", "1", "2"], cwd=work, env=env, check=False)
    assert result.returncode != 0
    assert not Path(env["IMPORT_TRACE"]).exists()
    assert (work / "results/result").read_text() == ""


def test_cached_source_runs_in_a_different_workspace(fixture):
    work, origin, _, env = fixture
    env["BK_BUILD_CACHE_ALLOW_HOST_ENV_CACHE"] = "true"
    result = build(work, env, cache=True)
    assert result.returncode == 0, result.stdout + result.stderr
    trace = Path(env["TRACE"]).read_text()
    other = work.parent / "restored"
    other.mkdir()
    for directory in ("scripts", "programs"):
        (other / directory).symlink_to(ROOT / directory, target_is_directory=True)
    result = build(other, env, cache=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BK_BUILD_CACHE_STATUS=hit" in (other / "results/build_cache.env").read_text()
    assert Path(env["TRACE"]).read_text() == trace
    assert not list(other.glob(".source-build.*"))
    shutil.rmtree(work)
    origin.rename(origin.with_name("unavailable"))
    result = command(["bash", str(ROOT / "scripts/run_benchmark.sh"), str(APP / "run.sh"),
                      "RIKYU", "1", "1", "2"], cwd=other, env=env, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(other) in Path(env["IMPORT_TRACE"]).read_text()
    result = command(["bash", str(ROOT / "scripts/result.sh"), "omnilearned", "RIKYU",
                      "native", "1", "2", "3"], cwd=other, env=env, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads((other / "results/result0.json").read_text())
    assert record["source_info"]["build"]["adjustments"][0]["status"] == "applied"
    assert "source_diff" not in record["source_info"]["build"]["adjustments"][0]
