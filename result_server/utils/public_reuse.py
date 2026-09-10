"""Public-only reuse package manifests and Markdown packets."""

from __future__ import annotations

import os
import re
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from utils.result_records import (
    format_numeric_value,
    format_result_timestamp,
    summarize_input_info,
    summarize_result_quality,
)


PUBLIC_REUSE_MANIFEST_SCHEMA_VERSION = 1
PUBLIC_REUSE_MANIFEST_KIND = "benchkit_public_reuse_packet"


def evaluate_public_reuse_packet(
    result: dict[str, Any],
    *,
    public_result: bool = True,
) -> dict[str, Any]:
    """Return the public reuse packet status for one Result JSON."""
    public_source = has_public_source_info(result.get("source_info"))
    public_input = has_public_input_info(result.get("input_info"), public_source)

    if not public_result:
        status = "not exportable"
        next_action = "Review publication eligibility"
    elif not public_source:
        status = "needs public source"
        next_action = "Record public source provenance"
    elif not result.get("input_info"):
        status = "needs public input"
        next_action = "Declare public input binding"
    elif not public_input:
        status = "needs public input"
        next_action = "Record public input binding"
    else:
        status = "eligible"
        next_action = "Prepare public Markdown packet"

    return {
        "eligible": status == "eligible",
        "status": status,
        "public_result": bool(public_result),
        "public_source": public_source,
        "public_input": public_input,
        "next_action": next_action,
    }


def build_reuse_detail_rows(
    result: dict[str, Any],
    *,
    public_result: bool = True,
) -> list[dict[str, Any]]:
    """Build compact rows for the Result Detail reuse package panel."""
    eligibility = evaluate_public_reuse_packet(result, public_result=public_result)
    quality = summarize_result_quality(result)
    stats = quality.get("stats", {})
    input_summary = summarize_input_info(result)
    rows = [
        ("Public packet", eligibility["status"]),
        ("Next action", eligibility["next_action"]),
        ("Public result", "yes" if eligibility["public_result"] else "no"),
        ("Public source", "yes" if eligibility["public_source"] else "no"),
        ("Public input", "yes" if eligibility["public_input"] else "no"),
        ("Input status", input_summary["label"]),
        (
            "Estimation bindings",
            _format_binding_count(
                stats.get("section_package_count", 0),
                stats.get("section_count", 0),
                stats.get("overlap_package_count", 0),
                stats.get("overlap_count", 0),
            ),
        ),
        ("Profile artifacts", stats.get("artifact_count", 0)),
    ]
    return [{"label": label, "value": value} for label, value in rows]


def build_public_reuse_manifest(
    result: dict[str, Any],
    filename: str,
    *,
    detail_url: str = "",
    packet_url: str = "",
    manifest_url: str = "",
    padata_filenames: list[str] | None = None,
    padata_url_by_filename: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a public-only, machine-readable reuse package manifest."""
    eligibility = evaluate_public_reuse_packet(result, public_result=True)
    quality = summarize_result_quality(result)
    input_summary = summarize_input_info(result)
    manifest = {
        "schema_version": PUBLIC_REUSE_MANIFEST_SCHEMA_VERSION,
        "kind": PUBLIC_REUSE_MANIFEST_KIND,
        "eligibility": eligibility,
        "urls": _strip_empty(
            {
                "detail": detail_url,
                "markdown_packet": packet_url,
                "manifest": manifest_url,
            }
        ),
        "result": _result_summary(result, filename),
        "source": _source_summary(result.get("source_info")),
        "input": _input_summary(result.get("input_info"), input_summary),
        "build": _build_summary(result.get("build_cache")),
        "profile": _profile_summary(
            result,
            padata_filenames or [],
            padata_url_by_filename or {},
        ),
        "estimation": _estimation_summary(result, quality),
        "reuse": {
            "status": "eligible" if eligibility["eligible"] else eligibility["status"],
            "notes": [
                "This manifest includes public result, source, and input evidence only.",
                "Use the recorded source and input commits as the starting point for reuse.",
                "Site access, queue access, and local software setup are outside this packet.",
            ],
        },
    }
    return _strip_empty(manifest)


def build_public_reuse_markdown_packet(manifest: dict[str, Any]) -> str:
    """Render a public reuse manifest as AI-friendly Markdown."""
    packet = _MarkdownBuilder()
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    title_parts = [
        _clean(result.get("code")),
        _clean(result.get("system")),
        _clean(result.get("experiment")),
    ]
    title_suffix = " / ".join(part for part in title_parts if part)
    packet.heading(1, "Benchkit Public Reuse Packet")
    if title_suffix:
        packet.paragraph(f"Target: {title_suffix}")
    packet.paragraph(
        "This packet summarizes a public Benchkit benchmark result for reuse. "
        "It includes public result metadata, public source provenance, public "
        "input binding, and reusable build, profile, and estimation evidence."
    )

    urls = manifest.get("urls") if isinstance(manifest.get("urls"), dict) else {}
    packet.heading(2, "Result")
    packet.table(
        [
            ("Result file", result.get("filename")),
            ("Detail page", _markdown_link(urls.get("detail"), urls.get("detail"))),
            ("Code", result.get("code")),
            ("System", result.get("system")),
            ("Experiment", result.get("experiment")),
            ("FOM", result.get("fom")),
            ("FOM version", result.get("fom_version")),
            ("Node count", result.get("node_count")),
            ("Processes per node", result.get("processes_per_node")),
            ("Threads per process", result.get("threads_per_process")),
            ("Recorded at", result.get("recorded_at")),
        ]
    )

    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    packet.heading(2, "Source")
    packet.table(
        [
            ("Status", source.get("status")),
            ("Type", source.get("type")),
            ("Repository", _markdown_link(source.get("repository_url"), source.get("repository_url"))),
            ("Reference", source.get("reference")),
            ("Resolved commit", source.get("resolved_commit")),
        ]
    )

    input_info = manifest.get("input") if isinstance(manifest.get("input"), dict) else {}
    packet.heading(2, "Input Binding")
    packet.table(
        [
            ("Status", input_info.get("status")),
            ("Summary", input_info.get("summary")),
        ]
    )
    input_items = input_info.get("items") if isinstance(input_info.get("items"), list) else []
    if input_items:
        packet.heading(3, "Inputs")
        packet.bullets(_format_input_item(item) for item in input_items)

    build = manifest.get("build") if isinstance(manifest.get("build"), dict) else {}
    packet.heading(2, "Build Evidence")
    cache_entry = build.get("cache_entry") if isinstance(build.get("cache_entry"), dict) else {}
    digests = cache_entry.get("digests") if isinstance(cache_entry.get("digests"), dict) else {}
    packet.table(
        [
            ("Cache status", build.get("cache_status")),
            ("Stored fresh entry", build.get("stored")),
            ("Cached binary created at", cache_entry.get("created_at")),
            ("Build inputs hash", digests.get("build_inputs")),
            ("Source info digest", digests.get("source_info")),
            ("Cached artifacts digest", digests.get("artifacts")),
        ]
    )

    profile = manifest.get("profile") if isinstance(manifest.get("profile"), dict) else {}
    packet.heading(2, "Profile Evidence")
    packet.table(
        [
            ("Status", profile.get("status")),
            ("Tool", profile.get("tool")),
            ("Level", profile.get("level")),
            ("Report format", profile.get("report_format")),
            ("Run count", profile.get("run_count")),
            ("Public archive count", profile.get("public_archive_count")),
        ]
    )
    artifacts = profile.get("artifacts") if isinstance(profile.get("artifacts"), list) else []
    if artifacts:
        packet.heading(3, "Profile Archives")
        packet.bullets(
            _format_profile_artifact(artifact)
            for artifact in artifacts
            if isinstance(artifact, dict)
        )

    estimation = manifest.get("estimation") if isinstance(manifest.get("estimation"), dict) else {}
    packet.heading(2, "Estimation Evidence")
    packet.table(
        [
            ("Status", estimation.get("status")),
            ("Sections", estimation.get("section_count")),
            ("Overlaps", estimation.get("overlap_count")),
            ("Package bindings", estimation.get("package_binding_summary")),
        ]
    )
    bindings = estimation.get("package_bindings")
    if isinstance(bindings, list) and bindings:
        packet.heading(3, "Package Bindings")
        packet.bullets(_format_package_binding(item) for item in bindings if isinstance(item, dict))

    reuse = manifest.get("reuse") if isinstance(manifest.get("reuse"), dict) else {}
    packet.heading(2, "Reuse Notes")
    packet.bullets(reuse.get("notes") or [])

    return packet.render()


def public_reuse_packet_download_name(filename: str) -> str:
    stem = _safe_stem(filename)
    return f"reuse_packet_{stem or 'result'}.md"


def public_reuse_manifest_download_name(filename: str) -> str:
    stem = _safe_stem(filename)
    return f"reuse_manifest_{stem or 'result'}.json"


def has_public_source_info(source_info: Any) -> bool:
    if not isinstance(source_info, dict):
        return False
    if _clean(source_info.get("source_type")).lower() != "git":
        return False
    if not is_public_http_url(source_info.get("repo_url")):
        return False
    if not (_clean(source_info.get("ref_name")) or _clean(source_info.get("branch"))):
        return False
    return bool(
        _clean(source_info.get("resolved_commit"))
        or _clean(source_info.get("commit_hash"))
    )


def has_public_input_info(input_info: Any, public_source_available: bool) -> bool:
    input_items = _input_info_items(input_info)
    if not input_items:
        return False
    return all(_has_public_input_item(item, public_source_available) for item in input_items)


def is_public_http_url(value: Any) -> bool:
    text = _clean(value)
    if not text or "\\" in text or any(char.isspace() for char in text):
        return False
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if "@" in parsed.netloc:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    return _is_public_hostname(hostname)


def _result_summary(result: dict[str, Any], filename: str) -> dict[str, Any]:
    fom = format_numeric_value(result.get("FOM"))
    unit = _clean(result.get("FOM_unit"))
    return _strip_empty(
        {
            "filename": filename,
            "recorded_at": format_result_timestamp(filename),
            "code": result.get("code"),
            "system": result.get("system"),
            "experiment": result.get("Exp"),
            "fom": f"{fom} {unit}".strip() if unit else fom,
            "fom_version": result.get("FOM_version"),
            "node_count": result.get("node_count"),
            "processes_per_node": result.get("numproc_node"),
            "threads_per_process": result.get("nthreads"),
        }
    )


def _source_summary(source_info: Any) -> dict[str, Any]:
    if not isinstance(source_info, dict) or not source_info:
        return {"status": "not recorded"}
    repo_url = _clean(source_info.get("repo_url"))
    return _strip_empty(
        {
            "status": "public" if has_public_source_info(source_info) else "not public",
            "type": _clean(source_info.get("source_type")) or "unknown",
            "repository_url": repo_url if is_public_http_url(repo_url) else "",
            "reference": _join_nonempty(
                source_info.get("ref_kind"),
                source_info.get("ref_name") or source_info.get("branch"),
            ),
            "resolved_commit": source_info.get("resolved_commit")
            or source_info.get("commit_hash"),
        }
    )


def _input_summary(input_info: Any, input_summary: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in _input_info_items(input_info):
        public_item = _public_input_item_summary(item)
        if public_item:
            items.append(public_item)
    return _strip_empty(
        {
            "status": input_summary["label"],
            "summary": input_summary["summary"],
            "items": items,
        }
    )


def _public_input_item_summary(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    values = {
        "dataset_id": item.get("dataset_id"),
        "dataset_version": item.get("dataset_version"),
        "kind": item.get("kind"),
        "source": item.get("source"),
        "source_ref": item.get("source_ref"),
        "resolved_commit": item.get("resolved_commit"),
        "commit_hash": item.get("commit_hash"),
        "source_commit": item.get("source_commit"),
        "revision": item.get("revision"),
        "dataset_revision": item.get("dataset_revision"),
        "repo_relative_path": _safe_relative_path(item.get("repo_relative_path")),
        "verification_status": item.get("verification_status"),
        "manifest_digest": item.get("manifest_digest"),
        "content_digest": item.get("content_digest"),
        "sha256": item.get("sha256"),
        "sha256sum": item.get("sha256sum"),
        "digest": item.get("digest"),
        "recipe": item.get("recipe"),
        "doi": item.get("doi"),
    }
    for key in ("public_url", "source_url", "archive_url"):
        if is_public_http_url(item.get(key)):
            values[key] = item.get(key)
    return _strip_empty(values)


def _build_summary(build_cache: Any) -> dict[str, Any]:
    if not isinstance(build_cache, dict) or not build_cache:
        return {"cache_status": "not recorded"}
    entry = build_cache.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    digests = entry.get("digests")
    digests = digests if isinstance(digests, dict) else {}
    return _strip_empty(
        {
            "cache_status": _clean(build_cache.get("status")) or "unknown",
            "stored": build_cache.get("stored") is True,
            "cache_entry": _strip_empty(
                {
                    "created_at": entry.get("created_at"),
                    "source": _cache_source_summary(entry.get("source")),
                    "digests": _strip_empty(
                        {
                            "build_inputs": digests.get("build_inputs"),
                            "source_info": digests.get("source_info"),
                            "artifacts": digests.get("artifacts"),
                        }
                    ),
                }
            ),
        }
    )


def _cache_source_summary(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict) or not source:
        return {}
    source_type = _clean(source.get("type")) or _clean(source.get("source_type"))
    summary = {
        "type": source_type,
        "reference": _join_nonempty(
            source.get("ref_kind"),
            source.get("ref_name") or source.get("branch"),
        ),
        "resolved_commit": source.get("resolved_commit") or source.get("commit_hash"),
        "sha256": source.get("sha256sum") or source.get("sha256"),
    }
    repo_url = source.get("repo_url") or source.get("url")
    if is_public_http_url(repo_url):
        summary["repository_url"] = repo_url
    return _strip_empty(summary)


def _profile_summary(
    result: dict[str, Any],
    padata_filenames: list[str],
    padata_url_by_filename: dict[str, str],
) -> dict[str, Any]:
    profile_data = result.get("profile_data")
    profile_data = profile_data if isinstance(profile_data, dict) else {}
    uploaded = set(padata_filenames)
    artifacts = []
    for section_name, artifact_path in _iter_profile_artifacts(result):
        artifact_slug = _padata_artifact_slug(artifact_path)
        if not artifact_slug:
            continue
        result_uuid = _clean(result.get("_server_uuid"))
        timestamp = _clean(result.get("_server_timestamp"))
        if not result_uuid or not timestamp:
            continue
        archive = f"padata_{timestamp}_{result_uuid}_{artifact_slug}.tgz"
        if archive not in uploaded:
            continue
        artifacts.append(
            _strip_empty(
                {
                    "section": section_name,
                    "archive": archive,
                    "url": padata_url_by_filename.get(archive),
                }
            )
        )

    return _strip_empty(
        {
            "status": "recorded" if profile_data else "not recorded",
            "tool": profile_data.get("tool"),
            "level": profile_data.get("level"),
            "report_format": profile_data.get("report_format"),
            "run_count": profile_data.get("run_count"),
            "report_kinds": profile_data.get("report_kinds"),
            "public_archive_count": len(artifacts),
            "artifacts": artifacts,
        }
    )


def _estimation_summary(result: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    stats = quality.get("stats", {}) if isinstance(quality, dict) else {}
    bindings = _estimation_package_bindings(result.get("fom_breakdown"))
    section_count = stats.get("section_count", 0)
    overlap_count = stats.get("overlap_count", 0)
    binding_count = stats.get("section_package_count", 0) + stats.get("overlap_package_count", 0)
    expected_count = section_count + overlap_count
    if expected_count == 0:
        status = "not recorded"
    elif binding_count == expected_count:
        status = "ready"
    else:
        status = "partial"
    return _strip_empty(
        {
            "status": status,
            "section_count": section_count,
            "overlap_count": overlap_count,
            "package_binding_summary": _format_binding_count(
                stats.get("section_package_count", 0),
                section_count,
                stats.get("overlap_package_count", 0),
                overlap_count,
            ),
            "package_bindings": bindings,
        }
    )


def _estimation_package_bindings(fom_breakdown: Any) -> list[dict[str, Any]]:
    breakdown = fom_breakdown if isinstance(fom_breakdown, dict) else {}
    bindings = []
    for collection_name in ("sections", "overlaps"):
        for item in breakdown.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            package = _clean(item.get("estimation_package"))
            if not package:
                continue
            bindings.append(
                _strip_empty(
                    {
                        "kind": collection_name[:-1],
                        "name": item.get("name"),
                        "estimation_package": package,
                    }
                )
            )
    return bindings[:40]


def _format_binding_count(
    section_package_count: Any,
    section_count: Any,
    overlap_package_count: Any,
    overlap_count: Any,
) -> str:
    return (
        f"{section_package_count}/{section_count} sections; "
        f"{overlap_package_count}/{overlap_count} overlaps"
    )


def _input_info_items(input_info: Any) -> list[Any]:
    if not isinstance(input_info, dict) or not input_info:
        return []
    inputs = input_info.get("inputs")
    if isinstance(inputs, list) and inputs:
        return inputs
    return [input_info]


def _has_public_input_item(item: Any, public_source_available: bool) -> bool:
    if not isinstance(item, dict):
        return False

    source = _clean(item.get("source")).lower()
    verification_status = _clean(item.get("verification_status")).lower()
    repo_relative_path = _clean(item.get("repo_relative_path"))
    if repo_relative_path and public_source_available:
        if source == "source_info" or verification_status == "covered_by_source_commit":
            return True

    if _clean(item.get("doi")):
        return True

    public_url = next(
        (
            item.get(key)
            for key in ("public_url", "source_url", "archive_url")
            if is_public_http_url(item.get(key))
        ),
        None,
    )
    if not public_url:
        return False

    return _has_input_digest(item) or _has_input_revision(item)


def _has_input_digest(item: dict[str, Any]) -> bool:
    digest_fields = (
        "manifest_digest",
        "content_digest",
        "sha256",
        "sha256sum",
        "digest",
    )
    return any(_clean(item.get(field)) for field in digest_fields)


def _has_input_revision(item: dict[str, Any]) -> bool:
    revision_fields = (
        "resolved_commit",
        "commit_hash",
        "source_commit",
        "revision",
        "dataset_revision",
    )
    return any(_clean(item.get(field)) for field in revision_fields)


def _iter_profile_artifacts(result: dict[str, Any]):
    breakdown = result.get("fom_breakdown")
    breakdown = breakdown if isinstance(breakdown, dict) else {}
    for collection_name in ("sections", "overlaps"):
        for item in breakdown.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            item_name = _clean(item.get("name")) or collection_name[:-1] or "-"
            for artifact in item.get("artifacts") or []:
                if not isinstance(artifact, dict) or artifact.get("type") != "file_reference":
                    continue
                path = _clean(artifact.get("path"))
                if path:
                    yield item_name, path


def _padata_artifact_slug(artifact_path: str) -> str:
    if not isinstance(artifact_path, str) or not artifact_path.startswith("results/"):
        return ""
    basename = os.path.basename(artifact_path)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:tgz|tar\.gz)", basename):
        return ""
    return basename[:-7] if basename.endswith(".tar.gz") else basename[:-4]


def _safe_relative_path(value: Any) -> str:
    text = _clean(value)
    if not text or os.path.isabs(text) or "\\" in text:
        return ""
    normalized = os.path.normpath(text)
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        return ""
    return text


def _is_public_hostname(hostname: str) -> bool:
    host = hostname.strip().strip("[]").lower().rstrip(".")
    if (
        not host
        or host == "localhost"
        or host.endswith((".local", ".localhost", ".internal", ".private"))
    ):
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return True
    return address.is_global


def _format_input_item(item: dict[str, Any]) -> str:
    keys = (
        "dataset_id",
        "dataset_version",
        "kind",
        "source",
        "public_url",
        "source_url",
        "archive_url",
        "source_ref",
        "resolved_commit",
        "commit_hash",
        "source_commit",
        "revision",
        "dataset_revision",
        "repo_relative_path",
        "verification_status",
        "manifest_digest",
        "content_digest",
        "sha256",
        "sha256sum",
        "digest",
        "recipe",
        "doi",
    )
    parts = [f"{key}: {item[key]}" for key in keys if item.get(key) not in (None, "", [], {})]
    return "; ".join(parts)


def _format_profile_artifact(artifact: dict[str, Any]) -> str:
    archive = artifact.get("archive")
    url = artifact.get("url")
    archive_text = _markdown_link(archive, url) if archive and url else archive
    return _join_nonempty(artifact.get("section"), archive_text)


def _format_package_binding(item: dict[str, Any]) -> str:
    return _join_nonempty(
        item.get("kind"),
        item.get("name"),
        item.get("estimation_package"),
    )


def _safe_stem(filename: str) -> str:
    stem, _ext = os.path.splitext(os.path.basename(filename))
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")


def _markdown_link(label: Any, href: Any) -> str:
    label_text = _clean(label)
    href_text = _clean(href)
    if not label_text or not href_text:
        return ""
    return f"[{_inline(label_text)}]({_escape_link_target(href_text)})"


def _escape_link_target(value: str) -> str:
    return str(value).replace(")", "%29")


def _inline(value: Any) -> str:
    if value in (None, "", [], {}):
        return "-"
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    text = str(value).replace("\r\n", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|")


def _join_nonempty(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _strip_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, item in value.items()
            for cleaned in [_strip_empty(item)]
            if cleaned not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            for cleaned in [_strip_empty(item)]
            if cleaned not in (None, "", [], {})
        ]
    return value


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
            self._lines.append("_No public evidence recorded._")
            self._lines.append("")
            return
        self._lines.append("| Field | Value |")
        self._lines.append("| --- | --- |")
        for label, value in visible_rows:
            self._lines.append(f"| {_inline(label)} | {_inline(value)} |")
        self._lines.append("")

    def bullets(self, values: Any) -> None:
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
