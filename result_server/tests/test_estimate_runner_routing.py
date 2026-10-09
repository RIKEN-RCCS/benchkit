"""Normal and UUID estimation share runner routing without a JSON runtime."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("tag", [None, "", "estimate-fixture", 'estimate "quoted"\\path'])
def test_estimation_runner_routing(tmp_path, tag):
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("bash", "cat", "dirname", "awk", "sed", "grep", "tr", "basename"):
        (tools / name).symlink_to(shutil.which(name))
    env = {"PATH": str(tools), "code": "sample",
           "estimate_result_uuid": "11111111-2222-3333-4444-555555555555"}
    if tag is not None:
        env["BK_ESTIMATE_RUNNER_TAG"] = tag

    def run(script, *args):
        result = subprocess.run([str(tools / "bash"), str(script), *args],
                                cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr

    run(ROOT / "scripts/estimation/generate_reestimate_pipeline.sh")
    reestimate = (tmp_path / ".gitlab-ci.estimate.yml").read_text()
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    config = tmp_path / "config"
    config.mkdir()
    (config / "system.csv").write_text(
        "system,mode,tag_build,tag_run,queue,queue_group\n"
        "TestSystem,cross,build-fixture,run-fixture,none,none\n")
    (config / "queue.csv").write_text("queue,submit_cmd,template\nnone,none,none\n")
    (config / "system_info.csv").write_text("system\nTestSystem\n")
    app = tmp_path / "programs/sample"
    app.mkdir(parents=True)
    (app / "list.csv").write_text(
        "system,enable,nodes,numproc_node,nthreads,elapse\n"
        "TestSystem,yes,1,1,1,00:01:00\n")
    for name in ("build.sh", "run.sh", "estimate.sh"):
        (app / name).touch()
    run("scripts/matrix_generate.sh", "code=sample")
    ordinary = (tmp_path / ".gitlab-ci.generated.yml").read_text()
    run("-c", 'source scripts/job_functions.sh; '
        'emit_estimate_job sample sample_send sample_run sample normal-estimate.yml')
    normal_job = (tmp_path / "normal-estimate.yml").read_text()

    # The emitters use JSON arrays/scalars within YAML; decode those exact values.
    def tags(text):
        return [json.loads(line.split(":", 1)[1]) for line in text.splitlines()
                if line.strip().startswith('tags: ["')]

    expected = tag or "fncx-estimate-python"
    assert tags(reestimate) == [[expected]]
    assert tags(normal_job) == [[expected]]
    variable = next(line.split(":", 1)[1] for line in ordinary.splitlines()
                    if line.strip().startswith("BK_ESTIMATE_RUNNER_TAG:"))
    assert json.loads(variable) == expected
    assert reestimate.count("tags: [fncx-curl-jq]") == 2
    assert 'needs: ["fetch_result"]' in reestimate
    assert 'needs: ["estimate_sample"]' in reestimate
