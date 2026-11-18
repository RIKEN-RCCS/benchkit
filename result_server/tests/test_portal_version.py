import subprocess
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


def test_version_does_not_run_git(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Git executed')))
    assert portal_version.portal_version_info(env={}, start_path=tmp_path) == {'label':'development','commit':'','source':'default'}


def test_version_uses_reviewed_metadata():
    assert portal_version.portal_version_info(env={'RESULT_SERVER_VERSION':'vtest','RESULT_SERVER_SOURCE_COMMIT':'a'*40}) == {'label':'vtest','commit':'a'*40,'source':'environment'}


def test_version_rejects_unexpected_values():
    assert portal_version.portal_version_info(env={'RESULT_SERVER_VERSION':'/secret/value','RESULT_SERVER_SOURCE_COMMIT':'bad'}) == {'label':'development','commit':'','source':'default'}
