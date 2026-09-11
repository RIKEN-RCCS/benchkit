"""Markdown evidence packets for result-level reproducibility review."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

from utils.result_detail_view import (
    build_cache_digest_help,
    build_cache_host_environment_help,
)
from utils.result_records import (
    format_numeric_value,
    input_info_items_for_result,
    summarize_input_info,
)
from utils.trigger_display import summarize_execution_trigger


def build_result_evidence_packet(
    result: dict[str, Any],
    filename: str,
    quality: dict[str, Any],
    *,
    public_surface: bool = False,
    detail_url: str = "",
    raw_json_url: str = "",
    padata_filenames: list[str] | None = None,
    padata_url_by_filename: dict[str, str] | None = None,
) -> str:
    """Build a Markdown evidence packet for one Result JSON."""
    packet = _MarkdownBuilder()
    packet.heading(1, "CX Result Evidence Packet")
    packet.paragraph(
        "This Evidence Packet is a portable review note for one benchmark "
        "result. Use it as the starting point for investigating reproducibility, "
        "unexpected performance changes, source and input provenance, "
        "build-cache reuse, and profiling or estimation evidence."
    )
    packet.paragraph(
        "It is written for readers who may not know the surrounding benchmark "
        "operation. Start from the Result, Source, Input, Quality, Profiling, "
        "and Build Cache sections below. Treat missing, declared-only, or "
        "unverifiable evidence as follow-up questions for the application or "
        "site owner."
    )
    packet.paragraph(
        "This packet does not guarantee independent reproduction. Re-runs may "
        "require site accounts, allocation approval, local runner access, "
        "software licenses, or non-public input data."
    )
    if public_surface:
        packet.paragraph(
            "Public surface packet: restricted fields, raw Result JSON, "
            "operator-only environment details, and confidential artifacts are "
            "intentionally omitted."
        )

    packet.heading(2, "Result")
    packet.table([
        ("Result file", filename),
        ("Detail page", _markdown_link(detail_url, detail_url) if detail_url else "-"),
        ("Code", result.get("code")),
        ("System", result.get("system")),
        ("Experiment", result.get("Exp")),
        ("FOM", _format_fom(result)),
        ("Node count", result.get("node_count")),
        ("Processes per node", result.get("numproc_node")),
        ("Threads per process", result.get("nthreads")),
    ])

    if not public_surface:
        trigger = summarize_execution_trigger(result)
        packet.heading(2, "Execution")
        packet.table([
            ("Pipeline ID", result.get("pipeline_id")),
            ("Parent pipeline ID", result.get("parent_pipeline_id")),
            ("Run cause", _format_trigger_summary(trigger)),
            ("Raw Result JSON", _markdown_link(raw_json_url, raw_json_url) if raw_json_url else "-"),
        ])

    packet.heading(2, "Source")
    source_rows = _source_rows(result.get("source_info"), include_url=not public_surface)
    packet.table(source_rows)

    packet.heading(2, "Input")
    input_summary = summarize_input_info(result)
    packet.table([
        ("Input status", input_summary["label"]),
        ("Summary", input_summary["summary"]),
    ])
    input_rows = _input_rows(result)
    if input_rows:
        packet.bullets(input_rows)

    packet.heading(2, "Quality")
    stats = quality.get("stats", {}) if isinstance(quality, dict) else {}
    packet.table([
        ("Level", quality.get("label") if isinstance(quality, dict) else ""),
        ("Summary", quality.get("summary") if isinstance(quality, dict) else ""),
        ("Sections", stats.get("section_count")),
        ("Overlaps", stats.get("overlap_count")),
        ("Estimation package bindings", _format_estimation_bindings(stats)),
        ("Profile artifact references", stats.get("artifact_count")),
    ])
    warnings = quality.get("warnings") if isinstance(quality, dict) else []
    actions = quality.get("suggested_actions") if isinstance(quality, dict) else []
    if warnings:
        packet.heading(3, "Warnings")
        packet.bullets(warnings)
    if actions:
        packet.heading(3, "Suggested Actions")
        packet.bullets(actions)

    packet.heading(2, "Profiling")
    packet.table(_profile_rows(result.get("profile_data")))
    artifact_rows = _profile_artifact_rows(result, padata_filenames or [], padata_url_by_filename or {})
    if artifact_rows:
        packet.heading(3, "PA Data Archives")
        packet.table(artifact_rows)

    build_cache_rows = _build_cache_rows(result.get("build_cache"))
    if build_cache_rows:
        packet.heading(2, "Build Cache")
        packet.table(build_cache_rows)

    if not public_surface:
        environment_rows = _environment_rows(result.get("environment_snapshot"))
        if environment_rows:
            packet.heading(2, "Environment Snapshot")
            packet.table(environment_rows)

    packet.heading(2, "Re-run Scope")
    packet.bullets([
        "Use the code, system, experiment, source, and input status above as the re-run checklist.",
        "System-level re-runs may require site accounts, allocation approval, and local runner access.",
        "If input status is Declared or None, ask the application owner for dataset identity, recipe, or digest evidence before treating the run as independently reproducible.",
        "If build cache status is hit, the cached artifacts digest records the identity of the restored build output, but re-running from source may still require the same build environment.",
    ])

    return packet.render()


def evidence_packet_download_name(filename: str) -> str:
    stem, _ext = os.path.splitext(os.path.basename(filename))
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")
    return f"evidence_packet_{safe_stem or 'result'}.md"


def _format_fom(result: dict[str, Any]) -> str:
    fom = format_numeric_value(result.get("FOM"))
    unit = str(result.get("FOM_unit") or "").strip()
    return f"{fom} {unit}".strip()


def _format_trigger_summary(trigger: dict[str, Any]) -> str:
    headline = str(trigger.get("headline") or "").strip()
    subline = str(trigger.get("subline") or "").strip()
    if headline and subline:
        return f"{headline} ({subline})"
    return headline or "-"


def _source_rows(source_info: Any, *, include_url: bool) -> list[tuple[str, Any]]:
    if not isinstance(source_info, dict) or not source_info:
        return [("Status", "not recorded")]

    source_type = str(source_info.get("source_type") or "").strip()
    rows: list[tuple[str, Any]] = [("Type", source_type or "unknown")]
    if source_type == "git":
        ref = _join_nonempty(
            source_info.get("ref_kind"),
            source_info.get("ref_name") or source_info.get("branch"),
        )
        rows.extend([
            ("Reference", ref),
            ("Resolved commit", source_info.get("resolved_commit") or source_info.get("commit_hash")),
        ])
        repo_url = str(source_info.get("repo_url") or "").strip()
        if include_url and repo_url:
            rows.append(("Repository URL", _safe_url_or_placeholder(repo_url)))
    elif source_type == "file":
        file_path = str(source_info.get("file_path") or "").strip()
        rows.extend([
            ("Source archive", os.path.basename(file_path) if file_path else "-"),
            ("SHA-256", source_info.get("sha256sum")),
            ("MD5", source_info.get("md5sum")),
        ])
    else:
        rows.extend([
            ("Resolved commit", source_info.get("resolved_commit") or source_info.get("commit_hash")),
            ("SHA-256", source_info.get("sha256sum")),
        ])
    return rows


def _safe_url_or_placeholder(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "not exported"
    if parsed.username or parsed.password or any(ch.isspace() for ch in value) or "\\" in value:
        return "not exported"
    return value


def _input_rows(result: dict[str, Any]) -> list[str]:
    input_items = input_info_items_for_result(result)
    rows = []
    for index, item in enumerate(input_items, start=1):
        if not isinstance(item, dict):
            continue
        parts = []
        for key in (
            "dataset_id",
            "dataset_version",
            "kind",
            "source",
            "parameter_set_id",
            "result_exp",
            "command",
            "arguments",
            "parameters",
            "repo_relative_path",
            "verification_status",
            "manifest_digest",
            "content_digest",
            "sha256",
            "sha256sum",
            "digest",
            "recipe",
            "doi",
            "public_url",
            "source_url",
            "archive_url",
        ):
            value = item.get(key)
            if value in (None, "", [], {}):
                continue
            if key in {"public_url", "source_url", "archive_url"}:
                value = _safe_url_or_placeholder(str(value))
            parts.append(f"{key}: {_inline(value)}")
        if parts:
            rows.append(f"input {index}: " + "; ".join(parts))
    return rows


def _format_estimation_bindings(stats: dict[str, Any]) -> str:
    sections = f"{stats.get('section_package_count', 0)}/{stats.get('section_count', 0)} sections"
    overlaps = f"{stats.get('overlap_package_count', 0)}/{stats.get('overlap_count', 0)} overlaps"
    return f"{sections}; {overlaps}"


def _profile_rows(profile_data: Any) -> list[tuple[str, Any]]:
    if not isinstance(profile_data, dict) or not profile_data:
        return [("Status", "not recorded")]
    rows: list[tuple[str, Any]] = [
        ("Tool", profile_data.get("tool")),
        ("Level", profile_data.get("level")),
        ("Report format", profile_data.get("report_format")),
        ("Run count", profile_data.get("run_count")),
    ]
    if profile_data.get("events"):
        rows.append(("Events", ", ".join(str(item) for item in profile_data["events"])))
    if profile_data.get("ncu_options"):
        rows.append(("NCU options", " ".join(str(item) for item in profile_data["ncu_options"])))
    if profile_data.get("report_kinds"):
        rows.append(("Report kinds", ", ".join(str(item) for item in profile_data["report_kinds"])))
    return rows


def _profile_artifact_rows(
    result: dict[str, Any],
    padata_filenames: list[str],
    padata_url_by_filename: dict[str, str],
) -> list[tuple[str, Any]]:
    result_uuid = result.get("_server_uuid")
    timestamp = result.get("_server_timestamp")
    if not result_uuid or not timestamp:
        return []

    uploaded = set(padata_filenames)
    rows = []
    for section_name, artifact_path in _iter_profile_artifacts(result):
        artifact_slug = _padata_artifact_slug(artifact_path)
        if not artifact_slug:
            continue
        archive = f"padata_{timestamp}_{result_uuid}_{artifact_slug}.tgz"
        status = "available" if archive in uploaded else "not uploaded"
        archive_value = archive
        if archive in uploaded and padata_url_by_filename.get(archive):
            archive_value = _markdown_link(archive, padata_url_by_filename[archive])
        rows.append((section_name, f"{artifact_path} - {status} - {archive_value}"))
    return rows


def _iter_profile_artifacts(result: dict[str, Any]):
    breakdown = result.get("fom_breakdown")
    breakdown = breakdown if isinstance(breakdown, dict) else {}
    for collection_name in ("sections", "overlaps"):
        for item in breakdown.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            item_name = str(item.get("name") or collection_name[:-1] or "-")
            for artifact in item.get("artifacts") or []:
                if not isinstance(artifact, dict) or artifact.get("type") != "file_reference":
                    continue
                path = str(artifact.get("path") or "").strip()
                if path:
                    yield item_name, path


def _padata_artifact_slug(artifact_path: str) -> str:
    if not isinstance(artifact_path, str) or not artifact_path.startswith("results/"):
        return ""
    basename = os.path.basename(artifact_path)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:tgz|tar\.gz)", basename):
        return ""
    return basename[:-7] if basename.endswith(".tar.gz") else basename[:-4]


def _build_cache_rows(build_cache: Any) -> list[tuple[str, Any]]:
    if not isinstance(build_cache, dict) or not build_cache:
        return []

    rows: list[tuple[str, Any]] = [
        ("Status", _build_cache_status(build_cache)),
        ("Reason", build_cache.get("reason")),
    ]
    entry = build_cache.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    if entry:
        context = (
            "matched" if str(build_cache.get("status") or "") == "hit" else "recorded"
        )
        rows.extend([
            ("Cached binary created at", entry.get("created_at")),
            ("Source", _format_cache_source(entry.get("source"))),
            (
                "Host environment fingerprint",
                _digest_with_help(
                    entry.get("host_environment_fingerprint"),
                    build_cache_host_environment_help(context),
                ),
            ),
        ])
        digests = entry.get("digests")
        digests = digests if isinstance(digests, dict) else {}
        rows.extend([
            (
                "Build inputs hash",
                _digest_with_help(
                    digests.get("build_inputs"),
                    build_cache_digest_help("build_inputs", context),
                ),
            ),
            (
                "Source info digest",
                _digest_with_help(
                    digests.get("source_info"),
                    build_cache_digest_help("source_info", context),
                ),
            ),
            (
                "Cached artifacts digest",
                _digest_with_help(
                    digests.get("artifacts"),
                    build_cache_digest_help("artifacts", context),
                ),
            ),
        ])
    if build_cache.get("hit_basis"):
        rows.append(("Hit basis", "; ".join(str(item) for item in build_cache["hit_basis"])))
    restore = build_cache.get("restore")
    if isinstance(restore, dict) and restore.get("reason"):
        rows.append(("Rejected cache reason", restore.get("reason")))
    return rows


def _build_cache_status(build_cache: dict[str, Any]) -> str:
    status = str(build_cache.get("status") or "unknown")
    if build_cache.get("stored") is True:
        return f"{status} (stored fresh entry)"
    return status


def _format_cache_source(source: Any) -> str:
    if not isinstance(source, dict) or not source:
        return "-"
    source_type = str(source.get("type") or "").strip()
    if source_type == "git":
        ref = _join_nonempty(source.get("ref_kind"), source.get("ref_name"))
        commit = str(source.get("resolved_commit") or "").strip()
        if ref and commit:
            return f"git {ref} @ {commit}"
        return f"git {_join_nonempty(ref, commit)}".strip()
    if source_type == "file" and source.get("sha256sum"):
        return f"file source {source['sha256sum']}"
    return source_type or "-"


def _digest_with_help(value: Any, help_text: str) -> str:
    if not value:
        return ""
    return f"{value} ({help_text})"


def _environment_rows(environment_snapshot: Any) -> list[tuple[str, Any]]:
    if not isinstance(environment_snapshot, dict) or not environment_snapshot:
        return []
    summary = environment_snapshot.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    payload = environment_snapshot.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    benchkit = payload.get("benchkit") if isinstance(payload.get("benchkit"), dict) else {}
    scheduler = payload.get("scheduler") if isinstance(payload.get("scheduler"), dict) else {}
    rows: list[tuple[str, Any]] = [
        ("Snapshot hash", environment_snapshot.get("hash")),
        ("System", summary.get("system")),
        ("Scheduler", summary.get("scheduler") or scheduler.get("kind")),
        ("Benchkit commit", summary.get("benchkit_commit") or benchkit.get("commit_hash")),
    ]
    toolchain = _display_toolchain(payload.get("toolchain"))
    modules = toolchain.get("modules") if isinstance(toolchain, dict) else []
    if modules:
        rows.append(("Modules", ", ".join(str(item) for item in modules[:20])))
    commands = _toolchain_commands(toolchain.get("commands") if isinstance(toolchain, dict) else {})
    if commands:
        rows.append(("Build tools", "; ".join(commands)))
    return rows


def _display_toolchain(toolchain: Any) -> dict[str, Any]:
    if not isinstance(toolchain, dict):
        return {}
    if isinstance(toolchain.get("commands"), dict) or isinstance(toolchain.get("modules"), list):
        return toolchain
    for stage in ("build_actual", "build_run", "build", "run"):
        stage_toolchain = toolchain.get(stage)
        if isinstance(stage_toolchain, dict) and stage_toolchain:
            return stage_toolchain
    return {}


def _toolchain_commands(commands: Any) -> list[str]:
    if not isinstance(commands, dict):
        return []
    rows = []
    for name in ("cc", "gcc", "mpicc", "mpicxx", "mpif90", "mpifort", "nvcc", "cmake", "make", "apptainer"):
        command = commands.get(name)
        if not isinstance(command, dict):
            continue
        version = str(command.get("version") or "").strip()
        path = str(command.get("path") or "").strip()
        value = version or os.path.basename(path)
        if value:
            rows.append(f"{name}: {value}")
    return rows[:12]


def _join_nonempty(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _markdown_link(label: str, href: str) -> str:
    if not href:
        return "-"
    return f"[{_inline(label)}]({_escape_link_target(href)})"


def _escape_link_target(value: str) -> str:
    return str(value).replace(")", "%29")


def _inline(value: Any) -> str:
    if value in (None, "", [], {}):
        return "-"
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    text = str(value).replace("\r\n", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|")


class _MarkdownBuilder:
    def __init__(self) -> None:
        self._lines: list[str] = []

    def heading(self, level: int, text: str) -> None:
        if self._lines and self._lines[-1] != "":
            self._lines.append("")
        self._lines.append(f"{'#' * level} {text}")
        self._lines.append("")

    def paragraph(self, text: str) -> None:
        self._lines.append(text)
        self._lines.append("")

    def table(self, rows: list[tuple[str, Any]]) -> None:
        visible_rows = [(label, value) for label, value in rows if value not in (None, "", [], {})]
        if not visible_rows:
            self._lines.append("_No evidence recorded._")
            self._lines.append("")
            return
        self._lines.append("| Field | Value |")
        self._lines.append("| --- | --- |")
        for label, value in visible_rows:
            self._lines.append(f"| {_inline(label)} | {_inline(value)} |")
        self._lines.append("")

    def bullets(self, values: list[Any]) -> None:
        visible_values = [value for value in values if value not in (None, "", [], {})]
        if not visible_values:
            self._lines.append("- none")
            self._lines.append("")
            return
        for value in visible_values:
            self._lines.append(f"- {_inline(value)}")
        self._lines.append("")

    def render(self) -> str:
        return "\n".join(self._lines).rstrip() + "\n"
