"""Execution route validation and matrix handoff using synthetic site data."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("execution_routes", ROOT / "scripts/execution_routes.py")
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)


@pytest.fixture
def config():
    return {
        "version": 1,
        "target": {"server_url": "https://gitlab.example.org", "project_path": "group/project"},
        "routes": [{
            "id": "research", "systems": ["Fugaku", "FugakuCN"],
            "build_tag": "research-build", "run_tag": "research-run",
            "allocation_project_id": "budget-example",
        }],
    }


@pytest.fixture
def env():
    return {"CI_SERVER_URL": "https://gitlab.example.org", "CI_PROJECT_PATH": "group/project"}


SYSTEMS = {"Fugaku": "cross", "FugakuCN": "native", "Legacy": "native"}


def test_route_groups_share_complete_binding(config, env):
    original = copy.deepcopy(config)
    resolved = routes.resolve_routes(config, SYSTEMS, env)
    assert set(resolved) == {"Fugaku", "FugakuCN"}
    assert resolved["Fugaku"] == resolved["FugakuCN"]
    assert resolved["Fugaku"]["id_token_audience"] == env["CI_SERVER_URL"]
    assert config == original


@pytest.mark.parametrize("field", ["CI_SERVER_URL", "CI_PROJECT_PATH"])
def test_target_mismatch_is_not_a_fallback(config, env, field):
    env[field] = "different"
    with pytest.raises(routes.RouteError, match="do not match"):
        routes.resolve_routes(config, SYSTEMS, env)


@pytest.mark.parametrize("field", ["id", "systems", "build_tag", "run_tag", "allocation_project_id"])
def test_partial_route_is_rejected(config, env, field):
    del config["routes"][0][field]
    with pytest.raises(routes.RouteError):
        routes.resolve_routes(config, SYSTEMS, env)


@pytest.mark.parametrize("field", ["id", "build_tag", "run_tag", "allocation_project_id", "id_token_audience"])
@pytest.mark.parametrize("value", [None, "bad\nvalue", 'bad"value', "$VARIABLE"])
def test_route_values_cannot_inject_yaml_or_expand_variables(config, env, field, value):
    config["routes"][0][field] = value
    with pytest.raises(routes.RouteError):
        routes.resolve_routes(config, SYSTEMS, env)


def test_native_route_does_not_require_build_tag(config, env):
    config["routes"][0]["systems"] = ["FugakuCN"]
    del config["routes"][0]["build_tag"]
    assert routes.resolve_routes(config, SYSTEMS, env)["FugakuCN"]["build_tag"] == ""


def test_route_can_explicitly_omit_allocation(config, env):
    config["routes"][0]["allocation_project_id"] = ""
    assert all(item["allocation_project_id"] == "" for item in routes.resolve_routes(config, SYSTEMS, env).values())


def test_allocation_free_route_generates_empty_binding_without_scheduler_option(project):
    directory, _ = project
    path = directory / "routes.json"
    config = json.loads(path.read_text())
    config["routes"][0].update(systems=["Legacy"], allocation_project_id="", build_tag="")
    path.write_text(json.dumps(config))
    result = generate(project, "Legacy")
    assert result.returncode == 0, result.stderr
    generated = (directory / ".gitlab-ci.generated.yml").read_text()
    assert 'BK_ROUTE_ALLOCATION_PROJECT_ID: ""' in generated
    assert 'SCHEDULER_PARAMETERS: "none"' in generated
    assert 'tags: ["research-run"]' in generated
    for overrides in ({"BK_ALLOCATION_PROJECT_ID": "unexpected"}, {"BK_SCHEDULER_EXTRA_ARGS": "--account=unexpected"}):
        assert generate(project, "Legacy", **overrides).returncode != 0


@pytest.mark.parametrize("name", ["Fugaku", "Unknown"])
def test_duplicate_or_unknown_system_is_rejected(config, env, name):
    config["routes"][0]["systems"].append(name)
    with pytest.raises(routes.RouteError):
        routes.resolve_routes(config, SYSTEMS, env)


def test_duplicate_route_id_and_unknown_fields_are_rejected(config, env):
    config["routes"].append(copy.deepcopy(config["routes"][0]))
    with pytest.raises(routes.RouteError, match="duplicate"):
        routes.resolve_routes(config, SYSTEMS, env)
    config["routes"].pop()
    config["routes"][0]["run_tags"] = ["typo"]
    with pytest.raises(routes.RouteError, match="unknown"):
        routes.resolve_routes(config, SYSTEMS, env)


@pytest.fixture
def project(tmp_path, config, env):
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "programs/demo").mkdir(parents=True)
    (tmp_path / "config/system.csv").write_text(
        "system,mode,tag_build,tag_run,queue,queue_group\n"
        "Fugaku,cross,legacy-build,legacy-run,FJ,test\n"
        "FugakuCN,native,,legacy-run,FJ,test\n"
        "Legacy,native,,legacy-run,NONE,test\n"
    )
    (tmp_path / "config/system_info.csv").write_text("system,cpu_per_node,gpu_per_node\n")
    (tmp_path / "config/queue.csv").write_text(
        'queue,submit_cmd,template\nFJ,pjsub,"${scheduler_extra_args} -L node=${nodes}"\n'
        'NONE,none,"none"\n'
    )
    (tmp_path / "programs/demo/list.csv").write_text(
        "system,enable,nodes,numproc_node,nthreads,elapse\n"
        "Fugaku,yes,1,2,3,0:05:00\nFugakuCN,yes,1,2,3,0:05:00\n"
        "Legacy,yes,1,2,3,0:05:00\n"
    )
    file = tmp_path / "routes.json"
    file.write_text(json.dumps(config))
    clean = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("BK_", "CI_")) and key != "SCHEDULER_PARAMETERS"
    }
    clean.update(env, BK_EXECUTION_ROUTES_FILE=str(file))
    return tmp_path, clean


def generate(project, system="", **overrides):
    directory, env = project
    result = subprocess.run(
        ["bash", "scripts/matrix_generate.sh", "code=demo", "system=" + system],
        cwd=directory, env={**env, **overrides}, text=True, capture_output=True,
    )
    return result


def test_matrix_uses_route_tags_budget_and_audience_without_logging_values(project):
    result = generate(project)
    assert result.returncode == 0, result.stderr
    text = (project[0] / ".gitlab-ci.generated.yml").read_text()
    assert 'tags: ["research-build"]' in text
    assert text.count('tags: ["research-run"]') == 2
    assert 'tags: ["legacy-run"]' in text
    assert text.count('SCHEDULER_PARAMETERS: "-g budget-example -L node=1"') == 2
    assert text.count('BK_ROUTE_ALLOCATION_PROJECT_ID: "budget-example"') == 3
    assert text.count('export BK_ALLOCATION_PROJECT_ID="$BK_ROUTE_ALLOCATION_PROJECT_ID"') == 3
    assert text.count('aud: "https://gitlab.example.org"') == 2
    assert 'aud: "$CI_SERVER_URL"' in text
    for value in ("budget-example", "research-build", "research-run"):
        assert value not in result.stdout + result.stderr


@pytest.mark.parametrize("allocation", ["", "budget-example"])
def test_empty_or_matching_pipeline_allocation_is_accepted(project, allocation):
    assert generate(project, "Fugaku", BK_ALLOCATION_PROJECT_ID=allocation).returncode == 0


@pytest.mark.parametrize("system,mode,queue", [
    ("Flow2_Type1", "cross", "PBS_FLOW2_CPU"),
    ("Flow2_Type2", "native", "PBS_FLOW2_GPU"),
])
def test_flow2_route_passes_project_group_to_scheduler(project, system, mode, queue):
    directory, _ = project
    # Use the site templates, but keep application resource choices synthetic.
    (directory / "config/queue.csv").write_text((ROOT / "config/queue.csv").read_text())
    additions = {
        "config/system.csv": f"{system},{mode},legacy-build,legacy-run,{queue},test-single\n",
        "programs/demo/list.csv": f"{system},yes,1,2,3,0:05:00\n",
    }
    for name, text in additions.items():
        path = directory / name
        path.write_text(path.read_text() + text)
    path = directory / "routes.json"
    config = json.loads(path.read_text())
    config["routes"][0]["systems"] = [system]
    path.write_text(json.dumps(config))

    result = generate(project, system)
    assert result.returncode == 0, result.stderr
    generated = (directory / ".gitlab-ci.generated.yml").read_text()
    assert (
        'SCHEDULER_PARAMETERS: "-q test-single -W group_list=budget-example '
        '-l select=1:mpiprocs=2:ompthreads=3 -l walltime=0:05:00"'
    ) in generated
    assert "ncpus=" not in generated
    assert "ngpus=" not in generated
    assert 'tags: ["research-run"]' in generated
    assert 'BK_ROUTE_ALLOCATION_PROJECT_ID: "budget-example"' in generated
    assert "budget-example" not in result.stdout + result.stderr
    for overrides in (
        {"BK_ALLOCATION_PROJECT_ID": "different-budget"},
        {"BK_SCHEDULER_EXTRA_ARGS": "-W group_list=different-budget"},
    ):
        result = generate(project, system, **overrides)
        assert result.returncode != 0
        assert "different-budget" not in result.stdout + result.stderr


def test_generated_setup_records_resolved_budget_in_snapshot(project):
    assert generate(project, "Fugaku", BK_ALLOCATION_PROJECT_ID="").returncode == 0
    text = (project[0] / ".gitlab-ci.generated.yml").read_text()
    setup = next(line.strip()[2:] for line in text.splitlines() if "- export BK_ALLOCATION_PROJECT_ID=" in line)
    result = subprocess.run(
        ["bash", "-c", setup + '\nBK_SYSTEM=Fugaku bash scripts/collect_environment_snapshot.sh snapshot.json'],
        cwd=project[0], env={**project[1], "BK_ALLOCATION_PROJECT_ID": "", "BK_ROUTE_ALLOCATION_PROJECT_ID": "budget-example"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((project[0] / "snapshot.json").read_text())["system"]["allocation_project_id"] == "budget-example"


@pytest.mark.parametrize("overrides", [
    {"BK_ALLOCATION_PROJECT_ID": "different-budget"},
    {"BK_SCHEDULER_EXTRA_ARGS": "-g different-budget"},
    {"BK_SCHEDULER_EXTRA_ARGS_Fugaku": "-g different-budget"},
    {"SCHEDULER_PARAMETERS": "-g different-budget"},
    {"BK_ROUTE_ALLOCATION_PROJECT_ID": "different-budget"},
])
def test_conflicting_overrides_stop_generation_without_echoing_values(project, overrides):
    result = generate(project, "Fugaku", **overrides)
    assert result.returncode != 0
    assert "different-budget" not in result.stdout + result.stderr


def test_unconfigured_system_and_absent_file_setting_keep_csv_tags(project):
    assert generate(project, "Legacy", BK_ALLOCATION_PROJECT_ID="other").returncode == 0
    del project[1]["BK_EXECUTION_ROUTES_FILE"]
    assert generate(project, "Fugaku").returncode == 0
    text = (project[0] / ".gitlab-ci.generated.yml").read_text()
    assert 'tags: ["legacy-build"]' in text
    assert 'tags: ["legacy-run"]' in text
    assert "BK_ROUTE_ALLOCATION_PROJECT_ID" not in text


def test_selected_routes_can_use_distinct_budgets(project, config):
    second = copy.deepcopy(config["routes"][0])
    config["routes"][0]["systems"] = ["Fugaku"]
    second.update(id="other", systems=["FugakuCN"], allocation_project_id="budget-other", run_tag="other-run")
    config["routes"].append(second)
    (project[0] / "routes.json").write_text(json.dumps(config))
    assert generate(project).returncode == 0
    text = (project[0] / ".gitlab-ci.generated.yml").read_text()
    assert 'SCHEDULER_PARAMETERS: "-g budget-example -L node=1"' in text
    assert 'SCHEDULER_PARAMETERS: "-g budget-other -L node=1"' in text
    assert generate(project, BK_ALLOCATION_PROJECT_ID="budget-example").returncode != 0
    assert generate(project, "Fugaku", BK_ALLOCATION_PROJECT_ID="budget-example").returncode == 0


def test_route_with_no_allocation_adapter_is_rejected(project, config):
    config["routes"][0]["systems"] = ["Legacy"]
    (project[0] / "routes.json").write_text(json.dumps(config))
    result = generate(project, "Legacy")
    assert result.returncode != 0
    assert "allocation is unsupported" in result.stderr


@pytest.mark.parametrize("content", ["not-json", '{"version":1,"version":1}', "{}"])
def test_invalid_config_never_falls_back(project, content):
    (project[0] / "routes.json").write_text(content)
    result = generate(project)
    assert result.returncode != 0
    assert content not in result.stderr


def test_missing_file_never_falls_back(project):
    (project[0] / "routes.json").unlink()
    assert generate(project).returncode != 0


def test_queue_must_accept_allocation_arguments(project):
    (project[0] / "config/queue.csv").write_text('queue,submit_cmd,template\nFJ,pjsub,"-L node=${nodes}"\n')
    assert generate(project, "Fugaku").returncode != 0


def test_explicit_audience_and_check_mode(project, config):
    config["routes"][0]["id_token_audience"] = "https://runner.example.org"
    (project[0] / "routes.json").write_text(json.dumps(config))
    assert generate(project, "Fugaku").returncode == 0
    assert 'aud: "https://runner.example.org"' in (project[0] / ".gitlab-ci.generated.yml").read_text()
    result = subprocess.run(
        ["python3", "scripts/execution_routes.py", "--check"], cwd=project[0], env=project[1],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "budget-example" not in result.stdout + result.stderr


@pytest.fixture
def snapshot(config):
    route = copy.deepcopy(config["routes"][0])
    route["systems"] = ["Fugaku"]
    return dict(version=1, registry_revision=3, budget_id="budget", destination_id=route["id"],
                target=config["target"], route=route)


@pytest.mark.parametrize("selected", ["", "Legacy", "Fugaku,Legacy", "*"])
def test_snapshot_cannot_expand_or_switch_selected_system(project, snapshot, selected):
    project[1].pop("BK_EXECUTION_ROUTES_FILE")
    result = generate(project, selected, BK_EXECUTION_ROUTE_SNAPSHOT=json.dumps(snapshot))
    assert result.returncode != 0
    assert not (project[0] / ".gitlab-ci.generated.yml").exists()


@pytest.mark.parametrize("field", ["CI_SERVER_URL", "CI_PROJECT_PATH"])
def test_snapshot_rejects_different_ci_target(project, snapshot, field):
    project[1].pop("BK_EXECUTION_ROUTES_FILE")
    result = generate(project, "Fugaku", BK_EXECUTION_ROUTE_SNAPSHOT=json.dumps(snapshot), **{field: "different"})
    assert result.returncode != 0


def test_snapshot_cannot_be_combined_with_file_routes(project, snapshot):
    assert generate(project, "Fugaku", BK_EXECUTION_ROUTE_SNAPSHOT=json.dumps(snapshot)).returncode != 0


@pytest.mark.parametrize("raw", ["", "not-json", "{}", '{"version":1,"version":1}', "x" * (1024 * 1024 + 1)])
def test_invalid_snapshot_never_falls_back(project, raw):
    with pytest.raises((routes.RouteError, ValueError)):
        routes.load_snapshot(raw, project[0] / "config/system.csv", project[1], "Fugaku")


@pytest.mark.parametrize("change", [{"registry_revision": True}, {"registry_revision": -1},
                                    {"destination_id": "other"}, {"version": 2}, {"token": "DO_NOT_EXPORT"}])
def test_snapshot_envelope_is_validated(project, snapshot, change):
    snapshot.update(change)
    project[1].pop("BK_EXECUTION_ROUTES_FILE")
    result = generate(project, "Fugaku", BK_EXECUTION_ROUTE_SNAPSHOT=json.dumps(snapshot))
    assert result.returncode != 0
    assert "DO_NOT_EXPORT" not in result.stdout + result.stderr
