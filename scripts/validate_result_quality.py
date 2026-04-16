#!/usr/bin/env python3
"""Lightweight validator for BenchKit result JSON quality.

By default this script is visibility-first: it reports warnings and validator
candidate gaps without failing the process. Future CI can opt into stricter
behavior with --fail-on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RESULT_SERVER_ROOT = REPO_ROOT / "result_server"
if str(RESULT_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(RESULT_SERVER_ROOT))

from utils.result_records import summarize_result_quality  # noqa: E402


DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "result_quality_policy.json"
DEFAULT_REDIS_KEY = "benchkit:result_quality:app_tiers"


def _iter_result_files(paths: list[str]) -> list[Path]:
    collected: list[Path] = []
    seen: set[Path] = set()

    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            for item in sorted(path.glob("*.json")):
                resolved = item.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    collected.append(item)
            continue

        if path.is_file() and path.suffix.lower() == ".json":
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                collected.append(path)

    return collected


def _load_result(path: Path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:  # pragma: no cover - surfaced in report
        return None, f"failed to parse JSON: {exc}"

    if "FOM" not in data or "system" not in data:
        return None, "not a benchmark result JSON (missing FOM or system)"

    return data, None


def _load_policy(path: str | None) -> dict:
    policy_path = Path(path) if path else DEFAULT_POLICY_PATH
    if not policy_path.exists():
        return {
            "version": 1,
            "default_tier": "relaxed",
            "tiers": {"relaxed": {"fail_candidates": [], "fail_warnings": []}},
            "apps": {},
            "_path": str(policy_path),
        }

    with policy_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if "tiers" not in data or not isinstance(data["tiers"], dict):
        raise ValueError(f"invalid quality policy: missing tiers in {policy_path}")

    data["_path"] = str(policy_path)
    return data


def _load_redis_app_tier_overrides(redis_url: str | None, redis_key: str) -> dict:
    if not redis_url:
        return {}

    try:
        import redis  # type: ignore
    except Exception:
        return {}

    try:
        redis_conn = redis.from_url(redis_url, decode_responses=True)
        overrides = redis_conn.hgetall(redis_key)
    except Exception:
        return {}

    if not isinstance(overrides, dict):
        return {}

    return {
        str(app).strip(): str(tier).strip()
        for app, tier in overrides.items()
        if str(app).strip() and str(tier).strip()
    }


def _resolve_policy_for_app(policy: dict, app: str) -> dict:
    tier_name = policy.get("apps", {}).get(app, policy.get("default_tier", "relaxed"))
    tier = policy.get("tiers", {}).get(tier_name)
    if not tier:
        tier_name = policy.get("default_tier", "relaxed")
        tier = policy.get("tiers", {}).get(tier_name, {"fail_candidates": [], "fail_warnings": []})

    return {
        "tier_name": tier_name,
        "fail_candidates": tier.get("fail_candidates", []),
        "fail_warnings": tier.get("fail_warnings", []),
    }


def build_quality_report(
    paths: list[str],
    policy_path: str | None = None,
    redis_url: str | None = None,
    redis_key: str = DEFAULT_REDIS_KEY,
) -> dict:
    files = _iter_result_files(paths)
    policy = _load_policy(policy_path)
    redis_overrides = _load_redis_app_tier_overrides(redis_url, redis_key)
    if redis_overrides:
        merged_apps = dict(policy.get("apps", {}))
        merged_apps.update(redis_overrides)
        policy["apps"] = merged_apps
    rows = []

    for path in files:
        data, load_error = _load_result(path)
        if load_error:
            rows.append({
                "path": str(path),
                "status": "skipped",
                "reason": load_error,
            })
            continue

        quality = summarize_result_quality(data)
        app = data.get("code", "unknown")
        policy_info = _resolve_policy_for_app(policy, app)
        enforced_candidates = [
            item for item in quality.get("validator_candidates", [])
            if item in policy_info["fail_candidates"]
        ]
        enforced_warnings = [
            item for item in quality.get("warnings", [])
            if item in policy_info["fail_warnings"]
        ]
        rows.append({
            "path": str(path),
            "status": "ok",
            "code": app,
            "system": data.get("system", "unknown"),
            "quality_level": quality["level"],
            "quality_label": quality["label"],
            "warning_count": len(quality["warnings"]),
            "warnings": quality["warnings"],
            "suggested_actions": quality.get("suggested_actions", []),
            "validator_candidates": quality.get("validator_candidates", []),
            "policy_tier": policy_info["tier_name"],
            "policy_fail_candidates": policy_info["fail_candidates"],
            "policy_fail_warnings": policy_info["fail_warnings"],
            "enforced_candidates": enforced_candidates,
            "enforced_warnings": enforced_warnings,
        })

    summary = {
        "scanned_files": len(files),
        "validated_results": sum(1 for row in rows if row["status"] == "ok"),
        "skipped_files": sum(1 for row in rows if row["status"] == "skipped"),
        "policy_path": policy["_path"],
        "default_tier": policy.get("default_tier", "relaxed"),
        "redis_override_key": redis_key if redis_url else "",
        "redis_override_count": len(redis_overrides),
        "rows": rows,
    }
    return summary


def _format_text_report(report: dict) -> str:
    lines = [
        f"Scanned files: {report['scanned_files']}",
        f"Validated results: {report['validated_results']}",
        f"Skipped files: {report['skipped_files']}",
    ]
    if report.get("redis_override_key"):
        lines.append(
            f"Redis overrides: {report.get('redis_override_count', 0)} from {report['redis_override_key']}"
        )

    for row in report["rows"]:
        if row["status"] == "skipped":
            lines.append(f"[SKIP] {row['path']}")
            lines.append(f"  reason: {row['reason']}")
            continue

        lines.append(
            f"[{row['quality_label']}] {row['path']} ({row['code']} / {row['system']})"
        )
        lines.append(f"  policy-tier: {row['policy_tier']}")
        lines.append(f"  warnings: {row['warning_count']}")
        if row["warnings"]:
            for item in row["warnings"]:
                lines.append(f"  - warning: {item}")
        else:
            lines.append("  - warning: none")

        if row["suggested_actions"]:
            for item in row["suggested_actions"]:
                lines.append(f"  - action: {item}")
        else:
            lines.append("  - action: none")

        if row["validator_candidates"]:
            for item in row["validator_candidates"]:
                lines.append(f"  - validator-candidate: {item}")
        else:
            lines.append("  - validator-candidate: none")

        if row["enforced_candidates"]:
            for item in row["enforced_candidates"]:
                lines.append(f"  - policy-candidate: {item}")
        if row["enforced_warnings"]:
            for item in row["enforced_warnings"]:
                lines.append(f"  - policy-warning: {item}")

    return "\n".join(lines)


def _should_fail(report: dict, fail_on: str) -> bool:
    if fail_on == "none":
        return False

    for row in report["rows"]:
        if row["status"] != "ok":
            continue
        if fail_on == "warning" and row["warning_count"] > 0:
            return True
        if fail_on == "candidate" and row["validator_candidates"]:
            return True
        if fail_on == "policy" and (row["enforced_candidates"] or row["enforced_warnings"]):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate BenchKit result JSON quality.")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["results"],
        help="Result JSON files or directories to scan. Defaults to ./results.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "warning", "candidate", "policy"),
        default="none",
        help=(
            "Exit non-zero when warnings or validator candidates are found. "
            "Default is report-only."
        ),
    )
    parser.add_argument(
        "--policy-file",
        default=str(DEFAULT_POLICY_PATH),
        help="Internal quality policy file. Defaults to config/result_quality_policy.json.",
    )
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("BK_RESULT_QUALITY_REDIS_URL", ""),
        help="Optional Redis URL for app-tier overrides.",
    )
    parser.add_argument(
        "--redis-key",
        default=os.environ.get("BK_RESULT_QUALITY_REDIS_KEY", DEFAULT_REDIS_KEY),
        help=f"Redis hash key used for app-tier overrides. Defaults to {DEFAULT_REDIS_KEY}.",
    )
    args = parser.parse_args(argv)

    report = build_quality_report(
        args.paths,
        policy_path=args.policy_file,
        redis_url=args.redis_url or None,
        redis_key=args.redis_key,
    )
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(report))

    return 1 if _should_fail(report, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
