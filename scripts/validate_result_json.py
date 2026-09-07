#!/usr/bin/env python3
"""Validate Benchkit Result JSON and Estimate JSON files.

This is a lightweight operator/reviewer check. It verifies the minimum JSON
contract and reports weaker provenance as warnings or notices instead of
blocking normal ingestion.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RESULT_REQUIRED_FIELDS = ("code", "system", "FOM")
RESULT_RECOMMENDED_FIELDS = (
    "FOM_unit",
    "FOM_version",
    "Exp",
    "node_count",
    "numproc_node",
    "nthreads",
)
ESTIMATE_REQUIRED_FIELDS = (
    "code",
    "exp",
    "current_system",
    "future_system",
    "performance_ratio",
)
ESTIMATE_SIDE_REQUIRED_FIELDS = (
    "system",
    "fom",
    "target_nodes",
    "scaling_method",
    "benchmark",
)
ESTIMATE_BENCHMARK_REQUIRED_FIELDS = (
    "system",
    "fom",
    "nodes",
    "numproc_node",
    "timestamp",
    "uuid",
)
APPLICABILITY_STATUSES = {
    "applicable",
    "partially_applicable",
    "fallback",
    "not_applicable",
    "needs_remeasurement",
}
BUILD_CACHE_STATUSES = {"hit", "miss", "disabled", "unknown"}
SOURCE_TYPES = {"git", "file"}


@dataclass(frozen=True)
class Issue:
    severity: str
    path: str
    message: str


def is_empty(value: Any) -> bool:
    return value is None or value == ""


def is_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def is_hex(value: Any, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def add_issue(issues: list[Issue], severity: str, path: str, message: str) -> None:
    issues.append(Issue(severity, path, message))


def require_fields(payload: dict[str, Any], fields: tuple[str, ...], prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    for field in fields:
        if field not in payload or is_empty(payload.get(field)):
            add_issue(issues, "error", f"{prefix}.{field}", "required field is missing or empty")
    return issues


def warn_missing_fields(payload: dict[str, Any], fields: tuple[str, ...], prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    for field in fields:
        if field not in payload or is_empty(payload.get(field)):
            add_issue(issues, "notice", f"{prefix}.{field}", "recommended field is missing or empty")
    return issues


def validate_numeric_field(payload: dict[str, Any], field: str, prefix: str) -> list[Issue]:
    if field not in payload or is_empty(payload.get(field)):
        return []
    if not is_number(payload.get(field)):
        return [Issue("error", f"{prefix}.{field}", "value must be numeric")]
    return []


def validate_result_payload(payload: dict[str, Any]) -> list[Issue]:
    issues = require_fields(payload, RESULT_REQUIRED_FIELDS, "$")
    issues.extend(warn_missing_fields(payload, RESULT_RECOMMENDED_FIELDS, "$"))
    issues.extend(validate_numeric_field(payload, "FOM", "$"))

    source_info = payload.get("source_info")
    issues.extend(validate_source_info(source_info, "$.source_info"))

    if "input_info" in payload:
        issues.extend(validate_input_info(payload.get("input_info"), "$.input_info"))
    else:
        add_issue(issues, "notice", "$.input_info", "optional input provenance is not present")

    issues.extend(validate_timing_block(payload.get("pipeline_timing"), "$.pipeline_timing"))
    issues.extend(validate_build_cache(payload.get("build_cache"), "$.build_cache"))
    issues.extend(validate_fom_breakdown(payload.get("fom_breakdown"), "$.fom_breakdown"))
    return issues


def validate_source_info(source_info: Any, prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    if source_info is None:
        add_issue(issues, "notice", prefix, "source provenance is not present")
        return issues
    if not isinstance(source_info, dict):
        add_issue(issues, "error", prefix, "source_info must be an object or null")
        return issues

    source_type = source_info.get("source_type")
    if source_type not in SOURCE_TYPES:
        add_issue(issues, "warning", f"{prefix}.source_type", "source_type should be git or file")
        return issues

    if source_type == "git":
        if is_empty(source_info.get("repo_url")):
            add_issue(issues, "warning", f"{prefix}.repo_url", "git source should record repo_url")
        if is_empty(source_info.get("resolved_commit")) and is_empty(source_info.get("commit_hash")):
            add_issue(
                issues,
                "warning",
                f"{prefix}.resolved_commit",
                "git source should record resolved_commit or commit_hash",
            )
        for field in ("resolved_commit", "commit_hash"):
            value = source_info.get(field)
            if not is_empty(value) and not is_hex(value, 40):
                add_issue(issues, "error", f"{prefix}.{field}", "git commit must be a 40-hex SHA")
    elif source_type == "file":
        if is_empty(source_info.get("file_path")):
            add_issue(issues, "warning", f"{prefix}.file_path", "file source should record file_path")
        if is_empty(source_info.get("sha256sum")):
            add_issue(issues, "warning", f"{prefix}.sha256sum", "file source should record sha256sum")
        elif not is_hex(source_info.get("sha256sum"), 64):
            add_issue(issues, "error", f"{prefix}.sha256sum", "SHA-256 must be a 64-hex digest")
    return issues


def validate_input_info(input_info: Any, prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    if input_info is None:
        add_issue(issues, "notice", prefix, "optional input provenance is null")
        return issues
    if not isinstance(input_info, dict):
        add_issue(issues, "error", prefix, "input_info must be an object when present")
        return issues

    verification_status = input_info.get("verification_status")
    has_digest = any(
        not is_empty(input_info.get(field))
        for field in ("manifest_digest", "content_digest", "sha256sum", "tree_digest")
    )
    if verification_status == "verified" and not has_digest:
        add_issue(
            issues,
            "warning",
            f"{prefix}.verification_status",
            "verified input_info should include a manifest or content digest",
        )
    if input_info.get("source") == "source_info" and is_empty(input_info.get("repo_relative_path")):
        add_issue(
            issues,
            "notice",
            f"{prefix}.repo_relative_path",
            "repo-local input coverage is clearer with repo_relative_path",
        )
    return issues


def validate_timing_block(timing: Any, prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    if timing is None:
        return issues
    if not isinstance(timing, dict):
        return [Issue("error", prefix, "timing block must be an object when present")]
    for field in ("build_time", "queue_time", "run_time", "elapsed_time"):
        value = timing.get(field)
        if value is None:
            continue
        if not is_number(value):
            add_issue(issues, "error", f"{prefix}.{field}", "timing value must be numeric")
        elif float(value) < 0:
            add_issue(issues, "error", f"{prefix}.{field}", "timing value must be non-negative")
    return issues


def validate_build_cache(build_cache: Any, prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    if build_cache is None:
        return issues
    if not isinstance(build_cache, dict):
        return [Issue("error", prefix, "build_cache must be an object when present")]
    status = build_cache.get("status")
    if not is_empty(status) and status not in BUILD_CACHE_STATUSES:
        add_issue(issues, "warning", f"{prefix}.status", "unknown build cache status")
    entry = build_cache.get("entry")
    if entry is not None and not isinstance(entry, dict):
        add_issue(issues, "error", f"{prefix}.entry", "build_cache.entry must be an object")
    restore = build_cache.get("restore")
    if restore is not None and not isinstance(restore, dict):
        add_issue(issues, "error", f"{prefix}.restore", "build_cache.restore must be an object")
    return issues


def validate_fom_breakdown(fom_breakdown: Any, prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    if fom_breakdown is None:
        return issues
    if not isinstance(fom_breakdown, dict):
        return [Issue("error", prefix, "fom_breakdown must be an object when present")]
    sections = fom_breakdown.get("sections")
    overlaps = fom_breakdown.get("overlaps")
    if sections is not None and not isinstance(sections, list):
        add_issue(issues, "error", f"{prefix}.sections", "sections must be an array")
    if overlaps is not None and not isinstance(overlaps, list):
        add_issue(issues, "error", f"{prefix}.overlaps", "overlaps must be an array")
    return issues


def validate_estimate_payload(payload: dict[str, Any]) -> list[Issue]:
    issues = require_fields(payload, ESTIMATE_REQUIRED_FIELDS, "$")
    issues.extend(validate_numeric_field(payload, "performance_ratio", "$"))

    for side_name in ("current_system", "future_system"):
        side = payload.get(side_name)
        prefix = f"$.{side_name}"
        if not isinstance(side, dict):
            add_issue(issues, "error", prefix, "system side must be an object")
            continue
        issues.extend(require_fields(side, ESTIMATE_SIDE_REQUIRED_FIELDS, prefix))
        issues.extend(validate_numeric_field(side, "fom", prefix))
        benchmark = side.get("benchmark")
        benchmark_prefix = f"{prefix}.benchmark"
        if not isinstance(benchmark, dict):
            add_issue(issues, "error", benchmark_prefix, "benchmark must be an object")
            continue
        issues.extend(require_fields(benchmark, ESTIMATE_BENCHMARK_REQUIRED_FIELDS, benchmark_prefix))
        issues.extend(validate_numeric_field(benchmark, "fom", benchmark_prefix))

    issues.extend(validate_estimate_metadata(payload.get("estimate_metadata"), "$.estimate_metadata"))
    issues.extend(validate_timing_block(payload.get("estimation_timing"), "$.estimation_timing"))
    issues.extend(validate_applicability(payload.get("applicability"), "$.applicability"))
    return issues


def validate_estimate_metadata(metadata: Any, prefix: str) -> list[Issue]:
    if metadata is None:
        return [Issue("notice", prefix, "estimate metadata is not present")]
    if not isinstance(metadata, dict):
        return [Issue("error", prefix, "estimate_metadata must be an object when present")]
    issues: list[Issue] = []
    source_result = metadata.get("source_result")
    if source_result is not None and not isinstance(source_result, dict):
        add_issue(issues, "error", f"{prefix}.source_result", "source_result must be an object")
    for field in ("current_source_result", "future_source_result"):
        value = metadata.get(field)
        if value is not None and not isinstance(value, dict):
            add_issue(issues, "error", f"{prefix}.{field}", f"{field} must be an object")
    return issues


def validate_applicability(applicability: Any, prefix: str) -> list[Issue]:
    issues: list[Issue] = []
    if applicability is None:
        return issues
    if not isinstance(applicability, dict):
        return [Issue("error", prefix, "applicability must be an object when present")]
    status = applicability.get("status")
    if is_empty(status):
        add_issue(issues, "warning", f"{prefix}.status", "applicability status is empty")
    elif status not in APPLICABILITY_STATUSES:
        add_issue(issues, "warning", f"{prefix}.status", "unknown applicability status")
    for field in ("missing_inputs", "required_actions", "incompatibilities"):
        value = applicability.get(field)
        if value is not None and not isinstance(value, list):
            add_issue(issues, "error", f"{prefix}.{field}", f"{field} must be an array")
    return issues


def detect_kind(path: Path, payload: dict[str, Any], requested_kind: str) -> str:
    if requested_kind != "auto":
        return requested_kind
    if path.name.startswith("estimate_"):
        return "estimate"
    if {"current_system", "future_system", "performance_ratio"}.issubset(payload):
        return "estimate"
    return "result"


def validate_payload(path: Path, payload: Any, kind: str = "auto") -> tuple[str, list[Issue]]:
    if not isinstance(payload, dict):
        return "unknown", [Issue("error", "$", "top-level JSON value must be an object")]
    detected_kind = detect_kind(path, payload, kind)
    if detected_kind == "estimate":
        return detected_kind, validate_estimate_payload(payload)
    return detected_kind, validate_result_payload(payload)


def iter_json_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(child for child in path.iterdir() if child.suffix == ".json"))
        else:
            files.append(path)
    return files


def load_json(path: Path) -> tuple[Any, list[Issue]]:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle), []
    except OSError as exc:
        return None, [Issue("error", str(path), f"cannot read file: {exc}")]
    except json.JSONDecodeError as exc:
        return None, [Issue("error", str(path), f"invalid JSON: {exc}")]


def print_issue(path: Path, issue: Issue) -> None:
    print(f"{issue.severity.upper()}: {path}: {issue.path}: {issue.message}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Benchkit Result JSON and Estimate JSON contract fields.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="JSON files or directories containing JSON files.",
    )
    parser.add_argument(
        "--kind",
        choices=("auto", "result", "estimate"),
        default="auto",
        help="Treat input files as Result JSON, Estimate JSON, or auto-detect.",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Return non-zero when warnings are present.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print issues.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    files = iter_json_files(args.paths)
    if not files:
        print("No JSON files found.", file=sys.stderr)
        return 1

    issue_count = 0
    error_count = 0
    warning_count = 0
    for path in files:
        payload, load_issues = load_json(path)
        if load_issues:
            kind = "unknown"
            issues = load_issues
        else:
            kind, issues = validate_payload(path, payload, args.kind)

        for issue in issues:
            print_issue(path, issue)
        issue_count += len(issues)
        error_count += sum(issue.severity == "error" for issue in issues)
        warning_count += sum(issue.severity == "warning" for issue in issues)
        if not args.quiet and not issues:
            print(f"OK: {path}: {kind}")

    if not args.quiet:
        print(
            "Validation complete: "
            f"{len(files)} file(s), {issue_count} issue(s), "
            f"{error_count} error(s), {warning_count} warning(s)."
        )
    if error_count:
        return 1
    if args.warnings_as_errors and warning_count:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
