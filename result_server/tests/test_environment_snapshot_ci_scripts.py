"""Exercise snapshot/cache handoffs rather than generator source spelling."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def run(root, env, *args):
    result = subprocess.run(args, cwd=root, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def write_script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -euo pipefail\n" + body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def project(tmp_path):
    # Copy scripts so isolated probes cannot modify the checkout.
    shutil.copytree(
        REPO_ROOT / "scripts", tmp_path / "scripts",
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    tools = tmp_path / "tools"
    write_script(tools / "make", '''
if [ "${1:-}" = --version ]; then
    echo 'GNU Make fixture'
else
    printf '%s\\n' "$*" >> "$TEST_MAKE_LOG"
fi
''')
    # Node/scheduler discovery is unrelated to the environment handoff contract.
    write_script(tmp_path / "scripts/collect_node_status_snapshot.sh", ":\n")
    # Keep user/CI overrides, exported module functions, and credentials out of
    # the fixture environment and failure reports.
    env = {
        key: os.environ[key] for key in ("HOME", "LANG", "LC_ALL", "TMPDIR")
        if key in os.environ
    }
    env.update(
        PATH=f"{tools}:/usr/bin:/bin", TEST_MAKE_LOG=str(tmp_path / "make.log"),
        BK_SNAPSHOT_TOOL_COMMANDS="bash make", BK_SNAPSHOT_ENV_VARS="BK_SYSTEM",
        BK_BUILD_CACHE_ENABLED="false",
    )
    return tmp_path, env


def generated_jobs(text):
    """Read stage and shell lists from the generator's simple YAML format.

    This is not a YAML validator. Keep extraction independent of job names and
    command spelling; fail rather than silently ignore unsupported script items.
    """
    jobs = []
    job = None
    field = None
    for line in text.splitlines():
        if re.match(r"^[^ #][^:]*:$", line):
            job = {"name": line[:-1], "before_script": [], "script": []}
            jobs.append(job)
            field = None
        elif job is not None:
            match = re.match(r"^  ([a-z_]+):\s*(.*)$", line)
            if match:
                field, value = match.groups()
                if field == "stage":
                    job[field] = value
                elif field == "cache":
                    job[field] = value
            elif field in ("before_script", "script") and line.strip():
                assert line.startswith("    - "), f"Unsupported script item: {line}"
                command = line[6:]
                assert command not in ("|", ">"), "Multiline script extraction needs support"
                job[field].append(command)
    return [job for job in jobs if "stage" in job]


@pytest.mark.parametrize("mode,system", [("cross", "CrossFixture"), ("native", "NativeFixture")])
def test_generated_jobs_collect_stage_snapshots_and_use_build_wrapper(project, mode, system):
    root, env = project
    (root / "config").mkdir()
    (root / "config/system.csv").write_text(
        "system,mode,tag_build,tag_run,queue,queue_group\n"
        f"{system},{mode},build-fixture,run-fixture,NONE,test\n"
    )
    (root / "config/system_info.csv").write_text("system,cpu_per_node,gpu_per_node\n")
    (root / "config/queue.csv").write_text('queue,submit_cmd,template\nNONE,none,"none"\n')
    app = root / "programs/demo"
    app.mkdir(parents=True)
    # Multiple rows check every emitted job without hard-coding wrapper counts.
    resources = [(1, 2, 3), (2, 1, 4)]
    (app / "list.csv").write_text(
        "system,enable,nodes,numproc_node,nthreads,elapse\n"
        + "".join(f"{system},yes,{nodes},{ranks},{threads},0:01:00\n"
                  for nodes, ranks, threads in resources)
    )
    write_script(app / "build.sh", '''
mkdir -p artifacts results
printf '%s\\n' "$1" "${BK_SYSTEM:-}" "${BK_BENCHKIT_ROOT:-}" "$(command -v make)" > results/build_handoff
make fixture-build
printf 'built\\n' > artifacts/demo
''')
    write_script(app / "run.sh", '''
test -f artifacts/demo
printf '%s\\n' "$@" > results/run_handoff
''')
    run(root, env, "bash", "scripts/matrix_generate.sh", "code=demo")
    jobs = generated_jobs((root / ".gitlab-ci.generated.yml").read_text())
    producers = [job for job in jobs if job["stage"] in ("build", "run", "build_run")]
    assert {job["stage"] for job in producers} == ({"build", "run"} if mode == "cross" else {"build_run"})
    assert sum(job["stage"] in ("run", "build_run") for job in producers) == len(resources)
    run_arguments = set()
    for job in producers:
        assert "cache" not in job, "Build cache must stay runner-local, not a GitLab cache"
        # Retain build artifacts for cross runs; remove evidence from the previous
        # job so a missing handoff cannot pass using stale snapshots or metadata.
        shutil.rmtree(root / "results", ignore_errors=True)
        commands = job["before_script"] + job["script"]
        assert commands, job["name"]
        run(root, env, "bash", "-e", "-c", "\n".join(commands))
        stage = job["stage"]
        snapshot = json.loads((root / f"results/environment_snapshot_{stage}.json").read_text())
        assert snapshot["stage"] == stage
        assert snapshot["system"]["name"] == system
        if stage in ("build", "build_run"):
            assert (root / "results/build_handoff").read_text().splitlines() == [
                system, system, str(root), str(root / "scripts/build_tool_wrappers/make"),
            ]
            actual = json.loads((root / "results/environment_snapshot_build_actual.json").read_text())
            assert actual["stage"] == "build_actual"
            assert actual["system"]["name"] == system
            assert actual["toolchain"]["commands"]["make"]["path"] == str(root / "tools/make")
            # Produced by the real cache helper, even with caching disabled.
            status = (root / "results/build_cache.env").read_text().splitlines()
            assert "BK_BUILD_CACHE_STATUS=disabled" in status
        if stage in ("run", "build_run"):
            run_arguments.add(tuple((root / "results/run_handoff").read_text().splitlines()))
    assert run_arguments == {(system, *map(str, row)) for row in resources}


def test_genesis_rikyu_container_build_preserves_wrapper_environment(project):
    root, env = project
    shutil.copytree(REPO_ROOT / "programs/genesis", root / "programs/genesis")
    source = root / "genesis"
    source.mkdir()
    # A local source checkout avoids downloads; only compilation is simulated.
    run(root, env, "git", "init", "--initial-branch=main", str(source))
    write_script(source / "bootstrap", ":\n")
    write_script(source / "configure", "mkdir -p bin\nprintf 'fixture executable\\n' > bin/spdyn\n")
    write_script(root / "tools/fixture-fc", "echo 'Fortran compiler fixture'\n")
    image = root / "fixture.sif"
    image.write_text("fixture container\n")
    apptainer = root / "tools/apptainer"
    write_script(apptainer, '''
[ "$1" = exec ]
shift
# A container can reset PATH and need explicit BK variables. Do not inherit
# these from the caller, otherwise missing --env options would go unnoticed.
export PATH="$TEST_CONTAINER_PATH"
unset BK_BENCHKIT_ROOT BK_SYSTEM
while [ "$#" -gt 0 ]; do
    case "$1" in
        --nv) shift ;;
        --bind) shift 2 ;;
        --pwd) cd "$2"; shift 2 ;;
        --env) export "$2"; shift 2 ;;
        *) shift; break ;;
    esac
done
printf '%s\\n' "${BK_BENCHKIT_ROOT:-}" "${BK_SYSTEM:-}" > "$TEST_CONTAINER_HANDOFF"
"$@"
''')
    env.update(
        TEST_CONTAINER_PATH=env["PATH"],
        TEST_CONTAINER_HANDOFF=str(root / "container_handoff"),
        GENESIS_REPO_URL=str(source / ".git"), GENESIS_RIKYU_SIF=str(image),
        GENESIS_RIKYU_APPTAINER=str(apptainer), CUDA_HOME=str(root / "cuda"),
        GENESIS_RIKYU_FC="fixture-fc",
        # Use a distinct recording identity to verify forwarding, not a fallback
        # to the positional system argument inside the container.
        BK_SYSTEM="ContainerFixture", BK_BENCHKIT_ROOT=str(root),
    )
    run(root, env, "bash", "programs/genesis/build.sh", "RIKYU")
    assert (root / "container_handoff").read_text().splitlines() == [str(root), "ContainerFixture"]
    assert (root / "artifacts/spdyn").read_text() == "fixture executable\n"
    assert "install" in (root / "make.log").read_text().splitlines()
    snapshot = json.loads((root / "results/environment_snapshot_build_actual.json").read_text())
    assert snapshot["stage"] == "build_actual"
    assert snapshot["system"]["name"] == "ContainerFixture"
    assert snapshot["toolchain"]["commands"]["make"]["path"] == str(root / "tools/make")
