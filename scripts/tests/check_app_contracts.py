#!/usr/bin/env python3
"""Emit warning-level diagnostics for changed benchmark app contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = REPO_ROOT / "programs"

sys.path.insert(0, str(REPO_ROOT / "result_server"))

from utils.site_diagnostics import build_site_diagnostics  # noqa: E402


def run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()


def event_payload() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    with Path(event_path).open(encoding="utf-8") as handle:
        return json.load(handle)


def changed_files() -> list[str]:
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    event = event_payload()

    try:
        if not event_name:
            merge_base = run_git("merge-base", "HEAD", "origin/develop")
            return run_git("diff", "--name-only", f"{merge_base}..HEAD").splitlines()

        if event_name == "pull_request":
            base_sha = ((event.get("pull_request") or {}).get("base") or {}).get("sha")
            if base_sha:
                return run_git("diff", "--name-only", f"{base_sha}...HEAD").splitlines()

        if event_name == "push":
            before = event.get("before")
            after = event.get("after")
            if before and after and before != "0" * 40 and after != "0" * 40:
                return run_git("diff", "--name-only", f"{before}..{after}").splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not determine changed files; app contract check skipped: {exc}", file=sys.stderr)

    return []


def changed_apps(paths: list[str]) -> list[str]:
    apps = set()
    for path in paths:
        parts = Path(path).parts
        if len(parts) >= 3 and parts[0] == "programs":
            apps.add(parts[1])
    return sorted(apps, key=str.lower)


def app_file(app: str, filename: str) -> str:
    return f"programs/{app}/{filename}"


def workflow_escape(value: object) -> str:
    text = str(value)
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotation(level: str, *, file: str, title: str, message: str) -> None:
    print(
        f"::{level} file={workflow_escape(file)},"
        f"title={workflow_escape(title)}::{workflow_escape(message)}"
    )


def app_script_text(app: str, filename: str) -> str:
    path = PROGRAMS_DIR / app / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def source_provenance_visible(app: str) -> bool:
    build_text = app_script_text(app, "build.sh")
    run_text = app_script_text(app, "run.sh")
    return any(
        marker in f"{build_text}\n{run_text}"
        for marker in ("bk_fetch_source", "results/source_info.env", "BK_SOURCE_")
    )


def input_provenance_visible(app: str) -> bool:
    run_text = app_script_text(app, "run.sh")
    return any(
        marker in run_text
        for marker in (
            "bk_record_input_info",
            "results/input_info.json",
            "input_info",
            "BK_INPUT_",
        )
    )


def profile_contract_visible(app: str) -> bool:
    return (PROGRAMS_DIR / app / "profile.sh").exists()


def estimate_contract_visible(app: str) -> bool:
    app_dir = PROGRAMS_DIR / app
    return (app_dir / "estimate.sh").exists() and not (app_dir / "estimate.disabled").exists()


def emit_warnings_for_apps(apps: list[str], diagnostics: dict) -> None:
    app_set = set(apps)

    for item in diagnostics.get("apps_missing_files", []):
        app = item.get("app")
        if app not in app_set:
            continue
        missing = ", ".join(item.get("missing_files", []))
        annotation(
            "warning",
            file=f"programs/{app}",
            title="Benchkit app contract",
            message=f"Required app contract file(s) are missing: {missing}.",
        )

    for item in diagnostics.get("unknown_listed_systems", []):
        app = item.get("app")
        if app not in app_set:
            continue
        annotation(
            "warning",
            file=app_file(str(app), "list.csv"),
            title="Benchkit app contract",
            message=(
                f"list.csv references system {item.get('system')} that is not "
                "defined in config/system.csv."
            ),
        )

    for item in diagnostics.get("partial_support", []):
        app = item.get("app")
        if app not in app_set:
            continue
        missing = []
        if not item.get("build_supported"):
            missing.append("build.sh")
        if not item.get("run_supported"):
            missing.append("run.sh")
        annotation(
            "warning",
            file=app_file(str(app), "list.csv"),
            title="Benchkit app contract",
            message=(
                f"{item.get('system')} has enabled list.csv row(s), but support "
                f"is not visible in {', '.join(missing)}."
            ),
        )

    for app in apps:
        if not source_provenance_visible(app):
            annotation(
                "notice",
                file=app_file(app, "build.sh"),
                title="Benchkit source provenance",
                message=(
                    "No source_info hook was detected. This is allowed, but "
                    "apps that fetch source code should record source_info."
                ),
            )
        if not input_provenance_visible(app):
            annotation(
                "notice",
                file=app_file(app, "run.sh"),
                title="Benchkit input provenance",
                message=(
                    "No input_info hook was detected. This is allowed, but "
                    "pre-staged or versioned benchmark inputs should record "
                    "input_info when practical."
                ),
            )
        if not profile_contract_visible(app):
            annotation(
                "notice",
                file=f"programs/{app}",
                title="Benchkit profiling contract",
                message="No profile.sh was detected. This is allowed when the app has no profiler path.",
            )
        if not estimate_contract_visible(app):
            annotation(
                "notice",
                file=f"programs/{app}",
                title="Benchkit estimation contract",
                message=(
                    "No active estimate.sh was detected. This is allowed when "
                    "the app has no estimation path."
                ),
            )


def main() -> int:
    paths = changed_files()
    apps = changed_apps(paths)
    if not apps:
        print("No benchmark app files changed; app contract warning check skipped.")
        return 0

    diagnostics = build_site_diagnostics()
    print(
        "Benchkit app contract warning check: "
        f"{len(apps)} changed app(s): {', '.join(apps)}"
    )
    emit_warnings_for_apps(apps, diagnostics)
    print("App contract diagnostics are warning-only and do not block the PR.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
