import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


CHECKER = Path(__file__).resolve().parents[2] / "scripts/check_estimation_version.py"
APP = "genesis"
SCRIPT = f"programs/{APP}/estimate.sh"
METADATA = f"programs/{APP}/estimate.metadata.json"
spec = importlib.util.spec_from_file_location("estimation_version_reminder", CHECKER)
reminder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reminder)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "fixture")
    app = tmp_path / "programs/genesis"
    app.mkdir(parents=True)
    (app / "estimate.sh").write_text("#!/bin/bash\nprintf unchanged\n")
    (app / "estimate.metadata.json").write_text('{"version":"1"}\n')
    commit(tmp_path)
    return tmp_path


@pytest.mark.parametrize("script,metadata,status", [
    (None, None, "unchanged"),
    ("#!/bin/bash\nprintf changed\n", None, "review"),
    ("# comment only\n", None, "review"),
    ("\n", None, "review"),
    ("changed\n", '{"version":"2"}', "version_changed"),
    (None, '{"version":"method-next"}', "version_changed"),
    (None, '{\n  "version": "1", "description": "format only"\n}', "unchanged"),
])
def test_comparison_states(repo, script, metadata, status):
    if script is not None:
        (repo / SCRIPT).write_text(script)
    if metadata is not None:
        (repo / METADATA).write_text(metadata)
    assert reminder.compare(repo, APP)["status"] == status


@pytest.mark.parametrize("metadata", [
    "{", "[]", "null", "{}", '{"version":null}', '{"version":1}',
    '{"version":""}', '{"version":"  "}', '{"version":"1","version":"2"}',
])
def test_unknown_version_is_not_reported_as_updated(repo, metadata):
    (repo / METADATA).write_text(metadata)
    result = reminder.compare(repo, APP)
    assert result["status"] == "unknown"
    assert result["working_version"] is None
    assert result["problems"]


@pytest.mark.parametrize("path", [SCRIPT, METADATA])
def test_missing_file_is_reported(repo, path):
    (repo / path).unlink()
    assert reminder.compare(repo, APP)["status"] == "unknown"


@pytest.mark.parametrize("old_metadata", ["{}", None])
def test_old_missing_or_invalid_version_is_unknown(repo, old_metadata):
    if old_metadata is None:
        (repo / METADATA).unlink()
    else:
        (repo / METADATA).write_text(old_metadata)
    base = commit(repo)
    (repo / METADATA).write_text('{"version":"2"}')
    assert reminder.compare(repo, APP, base)["status"] == "unknown"


def test_only_the_two_selected_application_files_are_checked(repo):
    (repo / "programs/genesis/section.sh").write_text("changed observation\n")
    package = repo / "scripts/estimation/section_packages/ensemble.metadata.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"new-package"}')
    assert reminder.compare(repo, APP)["status"] == "unchanged"


def test_staged_and_unstaged_content_are_both_included(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / SCRIPT).write_text("staged\n")
    git(repo, "add", SCRIPT)
    assert reminder.compare(repo, APP, base)["status"] == "review"
    (repo / METADATA).write_text('{"version":"2"}')
    assert reminder.compare(repo, APP, "refs/heads/fixture")["status"] == "version_changed"


def test_linked_worktree(repo, tmp_path):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "--detach", str(linked), "HEAD")
    (linked / SCRIPT).write_text("changed in worktree\n")
    assert reminder.compare(linked, APP)["status"] == "review"


def test_partial_clone_is_rejected_without_fetch(repo):
    git(repo, "config", "remote.origin.promisor", "true")
    git(repo, "config", "remote.origin.url", "https://unused.example.invalid/repo")
    with pytest.raises(ValueError, match="no objects will be fetched"):
        reminder.compare(repo, APP)


@pytest.mark.parametrize("path", [SCRIPT, METADATA])
def test_symlinks_are_not_followed(repo, path, tmp_path):
    target = tmp_path / "outside.json"
    target.write_text('{"version":"2"}')
    (repo / path).unlink()
    (repo / path).symlink_to(target)
    assert reminder.compare(repo, APP)["status"] == "unknown"


def test_cli_is_informational_and_does_not_run_or_modify_files(repo):
    checker = repo / "scripts/check_estimation_version.py"
    checker.parent.mkdir(parents=True)
    shutil.copyfile(CHECKER, checker)
    (repo / SCRIPT).write_text("#!/bin/bash\ntouch ESTIMATION_MUST_NOT_RUN\n")
    before_status = git(repo, "status", "--porcelain")
    before_refs = git(repo, "show-ref")
    before = {p: (repo / p).read_bytes() for p in (SCRIPT, METADATA)}
    result = subprocess.run([sys.executable, str(checker), "--app", APP], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Check whether a version update is needed" in result.stdout
    assert git(repo, "status", "--porcelain") == before_status
    assert git(repo, "show-ref") == before_refs
    assert not (repo / "ESTIMATION_MUST_NOT_RUN").exists()
    assert before == {p: (repo / p).read_bytes() for p in before}
    (repo / METADATA).write_text("not JSON")
    unknown = subprocess.run([sys.executable, str(checker), "--app", APP], capture_output=True, text=True)
    assert unknown.returncode == 0
    assert "cannot check the method version" in unknown.stdout


def test_unavailable_base_is_a_comparison_error(repo):
    with pytest.raises(ValueError, match="local Git"):
        reminder.compare(repo, APP, "refs/heads/not-present")


def test_application_selection_reads_only_that_pair(repo, monkeypatch):
    other = repo / "programs/other_app"
    other.mkdir()
    (other / "estimate.sh").write_text("other implementation\n")
    (other / "estimate.metadata.json").write_text('{"version":"other-version"}')
    commit(repo)
    (other / "estimate.sh").write_text("changed other implementation\n")
    reads = []
    original = reminder.working_file

    def read(repository, path):
        reads.append(path)
        return original(repository, path)

    monkeypatch.setattr(reminder, "working_file", read)
    assert reminder.compare(repo, APP)["status"] == "unchanged"
    assert reads == [SCRIPT, METADATA]
    assert reminder.compare(repo, "other_app")["status"] == "review"


@pytest.mark.parametrize("app", ["", ".", "..", "../genesis", "genesis/other", "-x", "genesis\n"])
def test_invalid_application_is_rejected_before_reading(repo, app, monkeypatch):
    def unexpected_git(*args, **kwargs):
        pytest.fail("invalid application must be rejected before Git/file access")

    monkeypatch.setattr(reminder, "git", unexpected_git)
    with pytest.raises(ValueError, match="invalid application name"):
        reminder.compare(repo, app)


def test_cli_requires_an_explicit_application(repo):
    checker = repo / "scripts/check_estimation_version.py"
    checker.parent.mkdir()
    shutil.copyfile(CHECKER, checker)
    before = git(repo, "status", "--porcelain")
    result = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "--app" in result.stderr
    assert git(repo, "status", "--porcelain") == before
