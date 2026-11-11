import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import portal_version


def test_release_note_content_matches_documentation():
    documentation = (Path(__file__).parents[2] / "docs" / "release-notes.md").read_text()
    for release in portal_version.portal_release_notes():
        assert f"## {release['version']} - {release['title']}" in documentation
        assert release["summary"] in documentation.replace("\n", " ")
        for change in release["changes"]:
            assert f"- {change}" in documentation


def test_release_notes_have_unique_versions_and_descending_dates():
    releases = portal_version.portal_release_notes()
    versions = [release["version"] for release in releases]
    dated_releases = [release for release in releases if release["date"]]
    dates = [date.fromisoformat(release["date"]) for release in dated_releases]
    assert len(versions) == len(set(versions))
    assert dates == sorted(dates, reverse=True)
    assert releases[0]["version"] == "v2026.11.11"
    assert releases[0]["date"] == "2026-11-11"
    assert len(dated_releases) == len(releases)
    for release, released_on in zip(dated_releases, dates):
        assert release["version"] == released_on.strftime("v%Y.%m.%d")


def test_dated_changes_version_matches_an_exact_release_tag(monkeypatch, tmp_path):
    release = next(item for item in portal_version.portal_release_notes() if item["date"])
    monkeypatch.setattr(portal_version, "_find_git_root", lambda start_path: tmp_path)

    def fake_run_git(args, git_root):
        assert git_root == tmp_path
        if args == ["rev-parse", "--short=12", "HEAD"]:
            return "123456789abc"
        assert args == ["describe", "--tags", "--exact-match", "HEAD"]
        return release["version"]

    monkeypatch.setattr(portal_version, "_run_git", fake_run_git)
    info = portal_version.portal_version_info(env={})
    assert info == {"label": release["version"], "commit": "123456789abc", "source": "git"}


def test_dated_changes_do_not_override_an_untagged_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(portal_version, "_find_git_root", lambda start_path: tmp_path)

    def fake_run_git(args, git_root):
        if args == ["rev-parse", "--short=12", "HEAD"]:
            return "123456789abc"
        if args == ["describe", "--tags", "--exact-match", "HEAD"]:
            return ""
        assert args == ["describe", "--tags", "--always", "--dirty"]
        return "v2026.10.15-100-g1234567-dirty"

    monkeypatch.setattr(portal_version, "_run_git", fake_run_git)
    info = portal_version.portal_version_info(env={})
    assert info["label"] == "v2026.10.15-100-g1234567-dirty"
    assert info["label"] != portal_version.portal_release_notes()[0]["version"]
    assert info["source"] == "git"


def test_portal_version_prefers_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RESULT_SERVER_VERSION", "vtest")
    monkeypatch.setattr(portal_version, "_find_git_root", lambda start_path: tmp_path)
    monkeypatch.setattr(
        portal_version,
        "_run_git",
        lambda args, git_root: "abc123def456" if args[:1] == ["rev-parse"] else "vold",
    )

    info = portal_version.portal_version_info()

    assert info["label"] == "vtest"
    assert info["commit"] == "abc123def456"
    assert info["source"] == "environment"


def test_portal_version_uses_exact_git_tag(monkeypatch, tmp_path):
    monkeypatch.delenv("RESULT_SERVER_VERSION", raising=False)
    monkeypatch.delenv("BENCHKIT_PORTAL_VERSION", raising=False)
    monkeypatch.setattr(portal_version, "_find_git_root", lambda start_path: tmp_path)

    def fake_run_git(args, git_root):
        if args[:1] == ["rev-parse"]:
            return "123456789abc"
        if args == ["describe", "--tags", "--exact-match", "HEAD"]:
            return "v2026.08.31"
        return "v2026.08.31-1-g1234567"

    monkeypatch.setattr(portal_version, "_run_git", fake_run_git)

    info = portal_version.portal_version_info()

    assert info == {
        "label": "v2026.08.31",
        "commit": "123456789abc",
        "source": "git",
    }


def test_portal_version_falls_back_to_development(monkeypatch):
    monkeypatch.delenv("RESULT_SERVER_VERSION", raising=False)
    monkeypatch.delenv("BENCHKIT_PORTAL_VERSION", raising=False)
    monkeypatch.setattr(portal_version, "_find_git_root", lambda start_path: None)

    info = portal_version.portal_version_info()

    assert info == {
        "label": "development",
        "commit": "",
        "source": "default",
    }
