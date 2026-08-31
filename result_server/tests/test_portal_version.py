import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import portal_version


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
