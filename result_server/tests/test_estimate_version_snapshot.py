import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.estimate_version_snapshot import read_estimation_version_snapshot


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "test")
    path = tmp_path / "programs/sample/estimate.metadata.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"version":"first"}')
    package = tmp_path / "scripts/estimation/packages/scaling.metadata.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"name":"scaling","version":"package-a"}')
    commit(tmp_path)
    return tmp_path


def test_resolves_once_and_reads_committed_not_dirty_content(repo):
    sha = git(repo, "rev-parse", "HEAD")
    path = repo / "programs/sample/estimate.metadata.json"
    path.write_text('{"version":"dirty"}')
    snapshot = read_estimation_version_snapshot(repo, "refs/heads/test", "sample",
                                                packages=["scaling"])
    assert snapshot["commit"] == sha
    assert snapshot["app"] == {"version": "first"}
    assert snapshot["packages"]["scaling"]["version"] == "package-a"
    assert not snapshot["unknowns"]
    commit(repo)
    pinned = read_estimation_version_snapshot(repo, sha, "sample")
    assert pinned["app"] == {"version": "first"}


@pytest.mark.parametrize("content,reason", [
    ('{"version":"a","version":"b"}', "duplicate_key"),
    ('{"version":null}', "missing_version"),
    ('[]', "invalid_declaration"),
    ('not json', "unreadable_declaration"),
    ('{"version":"' + 'x' * (128 * 1024) + '"}', "oversized_declaration"),
], ids=["duplicate", "missing-version", "not-object", "not-json", "oversized"])
def test_invalid_declarations_stay_unknown(repo, content, reason):
    (repo / "programs/sample/estimate.metadata.json").write_text(content)
    sha = commit(repo)
    snapshot = read_estimation_version_snapshot(repo, sha, "sample")
    assert snapshot["app"] is None
    assert snapshot["unknowns"][0]["reason"] == reason


def test_symlink_and_missing_or_misnamed_packages(repo):
    path = repo / "programs/sample/estimate.metadata.json"
    path.unlink()
    path.symlink_to("../../../outside.json")
    (repo / "scripts/estimation/packages/scaling.metadata.json").write_text(
        '{"name":"other","version":"a"}')
    sha = commit(repo)
    result = read_estimation_version_snapshot(repo, sha, "sample",
                                              packages=["scaling"], section_packages=["absent"])
    assert {item["reason"] for item in result["unknowns"]} == {
        "unsupported_declaration_type", "missing_declaration", "declaration_name_mismatch",
    }


def test_unavailable_ref_is_not_the_current_checkout(repo):
    result = read_estimation_version_snapshot(repo, "refs/heads/absent", "sample")
    assert result["commit"] is None and result["app"] is None
    assert result["unknowns"] == [{"reason": "unavailable_ref"}]


@pytest.mark.parametrize("ref,code,packages", [
    ("HEAD", "sample", []), ("--help", "sample", []),
    ("refs/heads/test", "../sample", []),
    ("refs/heads/test", "sample", ["../scaling"]),
    ("refs/heads/test", "sample", "scaling"),
])
def test_invalid_identifiers_are_rejected(repo, ref, code, packages):
    with pytest.raises(ValueError):
        read_estimation_version_snapshot(repo, ref, code, packages=packages)


def test_declaration_read_does_not_execute_shell(repo):
    (repo / "programs/sample/estimate.sh").write_text(f'touch "{repo / "EXECUTED"}"\nexit 1\n')
    sha = commit(repo)
    assert read_estimation_version_snapshot(repo, sha, "sample")["app"]["version"] == "first"
    assert not (repo / "EXECUTED").exists()


def test_migrated_metadata_matches_existing_runtime_functions(tmp_path):
    root = Path(__file__).resolve().parents[2]
    git(tmp_path, "init", "-q", "-b", "test")
    app_path = Path("programs/genesis/estimate.metadata.json")
    (tmp_path / app_path).parent.mkdir(parents=True)
    (tmp_path / app_path).write_bytes((root / app_path).read_bytes())
    selected = {}
    for group, names in {
        "packages": ["weakscaling", "instrumented_app_sections_dummy"],
        "section_packages": ["identity", "gpu_kernel_ensemble_average", "gpu_kernel_lightgbm_v10",
                             "gpu_kernel_mlp_v15", "gpu_kernel_mlp_v21", "gpu_kernel_mlp_v41"],
    }.items():
        selected[group] = names
        for name in names:
            path = root / f"scripts/estimation/{group}/{name}"
            function = "bk_estimation_package_metadata" if group == "packages" else f"bk_section_package_metadata_{name}"
            output = subprocess.check_output(
                ["bash", "-c", 'source "$1"; "$2"', "test", str(path) + ".sh", function],
                cwd=root, text=True,
            )
            assert json.loads(output) == json.loads(Path(str(path) + ".metadata.json").read_text())
            relative = path.relative_to(root).with_suffix(".metadata.json")
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / relative).write_text(output)
    sha = commit(tmp_path)
    snapshot = read_estimation_version_snapshot(tmp_path, sha, "genesis", **selected)
    assert not snapshot["unknowns"]
    assert snapshot["app"] == json.loads((root / app_path).read_text())


def test_partial_clone_cannot_trigger_lazy_network_fetch(repo):
    git(repo, "config", "remote.origin.promisor", "true")
    result = read_estimation_version_snapshot(repo, "refs/heads/test", "sample")
    assert result["commit"] is None
    assert result["unknowns"] == [{"reason": "partial_clone_not_supported"}]


def test_git_environment_cannot_redirect_the_repository(repo, monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/nonexistent")
    assert read_estimation_version_snapshot(repo, "refs/heads/test", "sample")["app"] == {"version": "first"}
