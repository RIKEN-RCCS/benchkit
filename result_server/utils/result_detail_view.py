import os
import re

from flask import url_for

from utils.result_records import build_labeled_value_rows, format_numeric_value
from utils.trigger_display import summarize_execution_trigger


HOST_ENVIRONMENT_FINGERPRINT_HELP = (
    "Checks whether the host build environment is the same. Covers code, "
    "system, loaded modules, selected build environment, and build tool real "
    "paths, versions, and binary hashes."
)

BUILD_CACHE_DIGEST_HELP = {
    "build_inputs": (
        "Checks whether the build recipe inputs are the same. Covers app "
        "build.sh, app patches, build-cache wrapper, build-tool wrappers, "
        "environment snapshot helper, matrix generator, and any declared extra "
        "cache inputs."
    ),
    "source_info": (
        "Checks whether the source metadata is the same. Uses source_info.env "
        "saved with the cache entry, including source type and resolved source "
        "identity."
    ),
    "artifacts": (
        "Checks whether the restored build outputs are the same as the saved "
        "cache entry. Covers artifacts/ relative paths, entry types, file "
        "modes, file contents, and symlink targets."
    ),
}


def build_result_detail_context(
    result,
    quality,
    trigger_runs_by_pipeline=None,
    padata_filenames=None,
    *,
    public_surface=False,
):
    profile_data = result.get("profile_data") or {}
    build_data = result.get("build") or {}
    vector_metrics = (result.get("metrics") or {}).get("vector")
    scalar_metrics = (result.get("metrics") or {}).get("scalar") or {}

    return {
        "meta_rows": _build_meta_rows(result, trigger_runs_by_pipeline, public_surface=public_surface),
        "profile_rows": _build_profile_rows(profile_data),
        "quality_rows": [] if public_surface else _build_quality_rows(quality),
        "profile_artifact_rows": _build_profile_artifact_rows(result, padata_filenames or []),
        "build_cache_rows": [] if public_surface else _build_build_cache_rows(result.get("build_cache")),
        "environment_rows": (
            [] if public_surface else _build_environment_rows(result.get("environment_snapshot"))
        ),
        "environment_snapshot_hash": (
            "" if public_surface else _environment_snapshot_hash(result.get("environment_snapshot"))
        ),
        "vector_metrics": vector_metrics,
        "scalar_rows": _build_scalar_rows(scalar_metrics),
        "build_rows": _build_build_rows(build_data),
    }


def _build_meta_rows(result, trigger_runs_by_pipeline=None, *, public_surface=False):
    trigger_summary = summarize_execution_trigger(result, trigger_runs_by_pipeline)
    base_items = [
        ("Code", result.get("code", "N/A")),
        ("System", result.get("system", "N/A")),
        ("Exp", result.get("Exp", "N/A")),
        ("FOM", format_numeric_value(result.get("FOM", "N/A"))),
        ("FOM Unit", result.get("FOM_unit") or "not specified"),
        ("Node Count", result.get("node_count", "N/A")),
    ]
    if not public_surface:
        base_items.extend([
            ("Pipeline ID", result.get("pipeline_id", "N/A")),
            (
                "Run Cause",
                (
                    f"{trigger_summary['headline']} ({trigger_summary['subline']})"
                    if trigger_summary.get("subline")
                    else trigger_summary["headline"]
                ),
            ),
        ])
    rows = build_labeled_value_rows(base_items)

    optional_rows = [
        ("Processes per Node", result.get("numproc_node")),
        ("Threads per Process", result.get("nthreads")),
        ("CPUs per Node", result.get("cpus_per_node")),
    ]
    if not public_surface:
        optional_rows.append(("Parent Pipeline ID", result.get("parent_pipeline_id")))
    for label, value in optional_rows:
        if value not in (None, "", "N/A", "null"):
            rows.append({"label": label, "value": value})
    return rows


def _build_profile_rows(profile_data):
    if not profile_data:
        return []

    events = profile_data.get("events") or []
    ncu_options = profile_data.get("ncu_options") or []
    report_kinds = profile_data.get("report_kinds") or []
    rows = build_labeled_value_rows([
        ("Tool", profile_data.get("tool", "N/A")),
        ("Level", profile_data.get("level", "N/A")),
        ("Report Format", profile_data.get("report_format", "N/A")),
        ("Run Count", profile_data.get("run_count", "N/A")),
    ])
    tool_specific_detail = _build_tool_specific_detail(profile_data)
    if tool_specific_detail:
        rows.append({"label": "Tool-Specific Detail", "value": tool_specific_detail})
    if events:
        rows.append({"label": "Events", "value": ", ".join(events)})
    if ncu_options:
        rows.append({"label": "NCU Options", "value": " ".join(ncu_options)})
    if report_kinds:
        rows.append({"label": "Report Kinds", "value": ", ".join(report_kinds)})
    return rows


def _build_tool_specific_detail(profile_data):
    if profile_data.get("tool") == "ncu":
        ncu_options = profile_data.get("ncu_options") or []
        if ncu_options:
            return f"ncu options: {' '.join(ncu_options)}"
        return "ncu options recorded in archive metadata when available"

    if profile_data.get("tool") != "fapp":
        return "tool-specific metadata"

    level = profile_data.get("level")
    mapping = {
        "single": "fapp event set: pa1",
        "simple": "fapp event set: pa1..pa5",
        "standard": "fapp event set: pa1..pa11",
        "detailed": "fapp event set: pa1..pa17",
    }
    return mapping.get(level, "fapp tool-specific event set")


def _build_profile_artifact_rows(result, padata_filenames):
    result_uuid = result.get("_server_uuid")
    timestamp = result.get("_server_timestamp")
    if not result_uuid or not timestamp:
        return []

    rows = []
    for section in (result.get("fom_breakdown") or {}).get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_name = section.get("name") or "-"
        for artifact in section.get("artifacts") or []:
            if not isinstance(artifact, dict) or artifact.get("type") != "file_reference":
                continue
            artifact_path = artifact.get("path") or ""
            artifact_slug = _padata_artifact_slug(artifact_path)
            if not artifact_slug:
                continue
            filename = f"padata_{timestamp}_{result_uuid}_{artifact_slug}.tgz"
            rows.append({
                "section": section_name,
                "artifact_path": artifact_path,
                "filename": filename,
                "link": url_for("results.show_result", filename=filename) if filename in padata_filenames else None,
            })
    return rows


def _padata_artifact_slug(artifact_path):
    if not isinstance(artifact_path, str):
        return ""
    if not artifact_path.startswith("results/"):
        return ""
    basename = os.path.basename(artifact_path)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:tgz|tar\.gz)", basename):
        return ""
    if basename.endswith(".tar.gz"):
        return basename[:-7]
    return basename[:-4]


def _build_quality_rows(quality):
    if not quality:
        return []

    stats = quality.get("stats", {})
    warnings = quality.get("warnings", [])
    return [
        {
            "label": "Level",
            "badge_level": quality.get("level"),
            "badge_label": quality.get("label"),
            "summary": quality.get("summary"),
        },
        {
            "label": "Source Info",
            "value": "top-level source tracked" if stats.get("has_source_info") else "not tracked",
        },
        {
            "label": "Breakdown",
            "value": (
                f"sections={stats.get('section_count', 0)}, overlaps={stats.get('overlap_count', 0)}"
                if stats.get("has_breakdown")
                else "missing"
            ),
        },
        {
            "label": "Estimation Bindings",
            "value": (
                f"sections={stats.get('section_package_count', 0)}/{stats.get('section_count', 0)}, "
                f"overlaps={stats.get('overlap_package_count', 0)}/{stats.get('overlap_count', 0)}"
            ),
        },
        {"label": "Estimation Inputs", "value": f"{stats.get('artifact_count', 0)} artifact reference(s)"},
        {"label": "Suggested Actions", "list": quality.get("suggested_actions") or ["none"]},
        {"label": "Improvement Candidates", "list": quality.get("validator_candidates") or ["none"]},
        {"label": "Warnings", "list": warnings or ["none"]},
    ]


def _build_environment_rows(environment_snapshot):
    if not isinstance(environment_snapshot, dict):
        return []

    summary = environment_snapshot.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    payload = environment_snapshot.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    system = payload.get("system") if isinstance(payload.get("system"), dict) else {}
    scheduler = payload.get("scheduler") if isinstance(payload.get("scheduler"), dict) else {}
    runner = payload.get("runner") if isinstance(payload.get("runner"), dict) else {}
    ci = payload.get("ci") if isinstance(payload.get("ci"), dict) else {}
    benchkit = payload.get("benchkit") if isinstance(payload.get("benchkit"), dict) else {}
    toolchain = payload.get("toolchain") if isinstance(payload.get("toolchain"), dict) else {}
    display_toolchain = _display_toolchain(toolchain)

    rows = build_labeled_value_rows([
        ("Snapshot Hash", environment_snapshot.get("hash", "N/A")),
        ("System", summary.get("system") or system.get("name") or "N/A"),
        (
            "Allocation Project ID",
            summary.get("allocation_project_id")
            or system.get("allocation_project_id")
            or "not specified",
        ),
        ("Scheduler", summary.get("scheduler") or scheduler.get("kind") or "N/A"),
        ("Runner", summary.get("runner") or runner.get("description") or "N/A"),
        ("CI Job", ci.get("job_name") or "N/A"),
        ("Benchkit Commit", summary.get("benchkit_commit") or benchkit.get("commit_hash") or "N/A"),
    ])
    modules = display_toolchain.get("modules") or []
    if modules:
        rows.append({"label": "Modules", "list": modules[:20]})
    commands = _build_toolchain_command_summary(display_toolchain.get("commands"))
    if commands:
        rows.append({"label": "Build Tools", "list": commands})
    return rows


def _display_toolchain(toolchain):
    if not isinstance(toolchain, dict):
        return {}
    if isinstance(toolchain.get("commands"), dict) or isinstance(toolchain.get("modules"), list):
        return toolchain
    for stage in ("build_actual", "build_run", "build", "run"):
        stage_toolchain = toolchain.get(stage)
        if isinstance(stage_toolchain, dict) and stage_toolchain:
            return stage_toolchain
    return {}


def _build_toolchain_command_summary(commands):
    if not isinstance(commands, dict):
        return []

    rows = []
    for name in (
        "cc",
        "gcc",
        "mpicc",
        "mpicxx",
        "mpif90",
        "mpifort",
        "nvcc",
        "nvc",
        "nvfortran",
        "cmake",
        "make",
        "apptainer",
    ):
        command = commands.get(name)
        if not isinstance(command, dict):
            continue
        version = str(command.get("version") or "").strip()
        path = str(command.get("path") or "").strip()
        value = version if version else path
        if value:
            rows.append(f"{name}: {value}")
    return rows[:12]


def _environment_snapshot_hash(environment_snapshot):
    if not isinstance(environment_snapshot, dict):
        return ""
    return str(environment_snapshot.get("hash") or "").strip()


def _build_scalar_rows(scalar_metrics):
    if len(scalar_metrics.keys()) < 2:
        return []
    return build_labeled_value_rows(list(scalar_metrics.items()))


def _build_build_cache_rows(build_cache):
    if not isinstance(build_cache, dict) or not build_cache:
        return []

    rows = []
    status = str(build_cache.get("status") or "unknown")
    stored = bool(build_cache.get("stored"))
    status_label = status
    if stored:
        status_label = f"{status} (stored fresh entry)"
    rows.append({"label": "Status", "value": status_label})

    reason = str(build_cache.get("reason") or "").strip()
    if reason:
        rows.append({"label": "Reason", "value": reason})

    entry = build_cache.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    _append_cache_entry_rows(rows, entry, prefix="")

    if status == "hit":
        hit_basis = build_cache.get("hit_basis") or []
        if hit_basis:
            rows.append({"label": "Hit Basis", "list": [str(item) for item in hit_basis]})
    else:
        store_basis = build_cache.get("store_basis") or []
        if store_basis:
            rows.append({"label": "Stored Entry Basis", "list": [str(item) for item in store_basis]})

    restore = build_cache.get("restore")
    restore = restore if isinstance(restore, dict) else {}
    restore_reason = str(restore.get("reason") or "").strip()
    if restore_reason:
        rows.append({"label": "Rejected Cache Reason", "value": restore_reason})
    rejected_entry = restore.get("rejected_entry")
    rejected_entry = rejected_entry if isinstance(rejected_entry, dict) else {}
    _append_cache_entry_rows(rows, rejected_entry, prefix="Rejected ")

    return rows


def _append_cache_entry_rows(rows, entry, *, prefix):
    if not entry:
        return

    created_at = str(entry.get("created_at") or "").strip()
    if created_at:
        rows.append({"label": f"{prefix}Cached Binary Created At", "value": created_at})

    source_summary = _format_cache_entry_source(entry)
    if source_summary:
        rows.append({"label": f"{prefix}Source", "value": source_summary})

    container = entry.get("container_image")
    container = container if isinstance(container, dict) else {}
    container_sha = str(container.get("sha256sum") or "").strip()
    if container_sha:
        rows.append({"label": f"{prefix}Container Image SHA-256", "value": container_sha})

    host_fingerprint = str(entry.get("host_environment_fingerprint") or "").strip()
    if host_fingerprint:
        rows.append({
            "label": f"{prefix}Host Environment Fingerprint",
            "value": host_fingerprint,
            "help": HOST_ENVIRONMENT_FINGERPRINT_HELP,
        })
    elif entry.get("env_key_present") is True:
        rows.append({"label": f"{prefix}Host Environment", "value": "environment key matched"})

    digests = entry.get("digests")
    digests = digests if isinstance(digests, dict) else {}
    digest_labels = [
        ("build_inputs", "Build Inputs Hash"),
        ("source_info", "Source Info Digest"),
        ("artifacts", "Cached Artifacts Digest"),
    ]
    for key, label in digest_labels:
        value = str(digests.get(key) or "").strip()
        if value:
            rows.append({
                "label": f"{prefix}{label}",
                "value": value,
                "help": BUILD_CACHE_DIGEST_HELP[key],
            })


def _format_cache_entry_source(entry):
    source = entry.get("source")
    source = source if isinstance(source, dict) else {}
    source_type = str(source.get("type") or "").strip()
    if not source_type:
        return ""

    if source_type == "git":
        ref_kind = str(source.get("ref_kind") or "").strip()
        ref_name = str(source.get("ref_name") or "").strip()
        resolved_commit = str(source.get("resolved_commit") or "").strip()
        ref_label = " ".join(part for part in [ref_kind, ref_name] if part)
        if ref_label and resolved_commit:
            return f"git {ref_label} @ {resolved_commit}"
        if resolved_commit:
            return f"git @ {resolved_commit}"
        return f"git {ref_label}".strip()

    source_sha = str(source.get("sha256sum") or "").strip()
    if source_type == "file" and source_sha:
        return f"file source {source_sha}"
    return source_type


def _build_build_rows(build_data):
    if not build_data:
        return []

    rows = build_labeled_value_rows([("Build Tool", build_data.get("tool", "N/A"))])
    spack = build_data.get("spack") or {}
    compiler = spack.get("compiler") or {}
    mpi = spack.get("mpi") or {}
    packages = spack.get("packages") or []

    if compiler:
        rows.extend(build_labeled_value_rows([
            ("Compiler", f"{compiler.get('name', '')} {compiler.get('version', '')}".strip()),
        ]))
    if mpi:
        rows.extend(build_labeled_value_rows([
            ("MPI", f"{mpi.get('name', '')} {mpi.get('version', '')}".strip()),
        ]))
    if packages:
        rows.append({
            "label": "Packages",
            "list": [f"{pkg.get('name', '')} {pkg.get('version', '')}".strip() for pkg in packages],
        })
    return rows
