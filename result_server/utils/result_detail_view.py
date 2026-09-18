from flask import url_for

from utils.measurement_artifacts import (
    profile_archive_filename_candidates,
    stored_measurement_artifact_filename_from_path,
)
from utils.result_records import build_labeled_value_rows, format_numeric_value
from utils.trigger_display import summarize_execution_trigger


HOST_ENVIRONMENT_FINGERPRINT_COVERAGE = (
    "Covers code, system, loaded modules, selected build environment, and build "
    "tool real paths, versions, and binary hashes."
)

HOST_ENVIRONMENT_FINGERPRINT_HELP = {
    "matched": (
        "Matched current host build environment against the restored cache "
        f"entry. {HOST_ENVIRONMENT_FINGERPRINT_COVERAGE}"
    ),
    "recorded": (
        "Recorded the host build environment for the newly stored cache entry. "
        f"{HOST_ENVIRONMENT_FINGERPRINT_COVERAGE}"
    ),
    "rejected": (
        "Recorded host build environment from a rejected cache candidate, shown "
        f"for diagnosis. {HOST_ENVIRONMENT_FINGERPRINT_COVERAGE}"
    ),
}

BUILD_CACHE_BUILD_INPUTS_COVERAGE = (
    "Covers Git-tracked files under programs/<code>/, the build-cache wrapper, "
    "build-tool wrappers, environment snapshot helper, matrix generator, and "
    "any site-provided extra cache inputs."
)

BUILD_CACHE_DIGEST_HELP = {
    "matched": {
        "build_inputs": (
            "Matched current build recipe inputs against the restored cache "
            f"entry. {BUILD_CACHE_BUILD_INPUTS_COVERAGE}"
        ),
        "source_info": (
            "Matched current source metadata against source_info.env saved with "
            "the cache entry, including source type and resolved source identity."
        ),
        "artifacts": (
            "Matched restored build outputs against the saved cache entry before "
            "and after restore. Covers artifacts/ relative paths, entry types, "
            "file modes, file contents, and symlink targets."
        ),
    },
    "recorded": {
        "build_inputs": (
            "Recorded build recipe inputs for the newly stored cache entry. "
            f"{BUILD_CACHE_BUILD_INPUTS_COVERAGE}"
        ),
        "source_info": (
            "Recorded source_info.env for the newly stored cache entry, including "
            "source type and resolved source identity."
        ),
        "artifacts": (
            "Recorded cached artifacts for the newly stored cache entry. Covers "
            "artifacts/ relative paths, entry types, file modes, file contents, "
            "and symlink targets."
        ),
    },
    "rejected": {
        "build_inputs": (
            "Rejected candidate build inputs. The candidate was not restored; "
            "compare this value with the rejection reason."
        ),
        "source_info": (
            "Rejected candidate source metadata. The candidate was not restored; "
            "compare this value with the rejection reason."
        ),
        "artifacts": (
            "Rejected candidate artifact digest. The candidate was not restored; "
            "this value describes the skipped cache entry."
        ),
    },
}

def build_cache_host_environment_help(context="matched"):
    return HOST_ENVIRONMENT_FINGERPRINT_HELP.get(
        context, HOST_ENVIRONMENT_FINGERPRINT_HELP["matched"]
    )


def build_cache_digest_help(key, context="matched"):
    return BUILD_CACHE_DIGEST_HELP.get(context, BUILD_CACHE_DIGEST_HELP["matched"]).get(
        key, ""
    )


def build_result_detail_context(
    result,
    quality,
    trigger_runs_by_pipeline=None,
    measurement_artifact_filenames=None,
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
        "measurement_artifact_rows": _build_measurement_artifact_rows(
            result,
            measurement_artifact_filenames or [],
            include_private=not public_surface,
        ),
        "node_status_rows": (
            [] if public_surface else _build_node_status_rows(result.get("node_status_snapshot"))
        ),
        "timing_observation_rows": (
            [] if public_surface else _build_timing_observation_rows(result.get("timing_observations"))
        ),
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


def _build_measurement_artifact_rows(
    result,
    measurement_artifact_filenames,
    *,
    include_private=True,
):
    result_uuid = result.get("_server_uuid")
    timestamp = result.get("_server_timestamp")
    if not result_uuid or not timestamp:
        return []

    uploaded = set(measurement_artifact_filenames)
    rows = _build_profile_measurement_artifact_rows(
        result, timestamp, result_uuid, uploaded, include_metadata=include_private,
    )
    if include_private:
        rows.extend(
            _build_timing_measurement_artifact_rows(result, timestamp, result_uuid, uploaded)
        )
        rows.extend(
            _build_node_status_measurement_artifact_rows(
                result, timestamp, result_uuid, uploaded
            )
        )
    return rows


def _build_profile_measurement_artifact_rows(
    result, timestamp, result_uuid, uploaded, *, include_metadata=True,
):
    rows = []
    breakdown = result.get("fom_breakdown")
    if not isinstance(breakdown, dict):
        return rows

    for collection_name, source_label in (("sections", "Section"), ("overlaps", "Overlap")):
        for item in breakdown.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            item_name = item.get("name") or "-"
            for artifact in item.get("artifacts") or []:
                if not isinstance(artifact, dict) or artifact.get("type") != "file_reference":
                    continue
                artifact_path = artifact.get("path") or ""
                candidates = profile_archive_filename_candidates(
                    timestamp,
                    result_uuid,
                    artifact_path,
                )
                kind = "Profile archive"
                if not candidates and include_metadata:
                    filename = stored_measurement_artifact_filename_from_path(
                        timestamp, result_uuid, artifact_path,
                    )
                    if filename.endswith(".json"):
                        candidates = [filename]
                        kind = "Profile metadata"
                if not candidates:
                    continue
                filename = _choose_uploaded_filename(candidates, uploaded)
                rows.append({
                    "kind": kind,
                    "source": f"{source_label}: {item_name}",
                    "artifact_path": artifact_path,
                    "filename": filename,
                    "link": (
                        url_for("results.show_result", filename=filename)
                        if filename in uploaded
                        else None
                    ),
                })
    return rows


def _build_timing_measurement_artifact_rows(result, timestamp, result_uuid, uploaded):
    timing_observations = result.get("timing_observations")
    if not isinstance(timing_observations, dict):
        return []

    observations = timing_observations.get("observations")
    if not isinstance(observations, list):
        return []

    rows = []
    for index, observation in enumerate(observations, start=1):
        if not isinstance(observation, dict):
            continue
        artifact = observation.get("artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        if artifact.get("type") != "file_reference":
            continue
        artifact_path = str(artifact.get("path") or "").strip()
        filename = stored_measurement_artifact_filename_from_path(
            timestamp,
            result_uuid,
            artifact_path,
        )
        if not filename:
            continue
        label = str(observation.get("id") or f"Observation {index}")
        rows.append({
            "kind": "Timing observation",
            "source": label,
            "artifact_path": artifact_path,
            "filename": filename,
            "link": (
                url_for("results.show_result", filename=filename)
                if filename in uploaded
                else None
            ),
        })
    return rows


def _build_node_status_measurement_artifact_rows(result, timestamp, result_uuid, uploaded):
    node_status_snapshot = result.get("node_status_snapshot")
    if not isinstance(node_status_snapshot, dict):
        return []

    artifact = node_status_snapshot.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    if artifact.get("type") != "file_reference":
        return []

    artifact_path = str(artifact.get("path") or "").strip()
    filename = stored_measurement_artifact_filename_from_path(
        timestamp,
        result_uuid,
        artifact_path,
    )
    if not filename:
        return []

    return [
        {
            "kind": "Node status snapshot",
            "source": "Run placement",
            "artifact_path": artifact_path,
            "filename": filename,
            "link": (
                url_for("results.show_result", filename=filename)
                if filename in uploaded
                else None
            ),
        }
    ]


def _build_node_status_rows(node_status_snapshot):
    if not isinstance(node_status_snapshot, dict):
        return []

    summary = node_status_snapshot.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    artifact = node_status_snapshot.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    warnings = _unique_strings(
        list(_list_values(node_status_snapshot.get("collection_warnings")))
        + list(_list_values(summary.get("warnings")))
    )

    rows = build_labeled_value_rows(
        [
            ("Status", node_status_snapshot.get("collection_status") or "unknown"),
            ("Scheduler", node_status_snapshot.get("scheduler_kind") or "unknown"),
            (
                "Hosts Observed",
                _format_observed_total(
                    summary.get("observed_host_count"),
                    summary.get("scheduler_host_count"),
                ),
            ),
            (
                "CPU Counts Observed",
                _format_value_list(summary.get("cpu_logical_counts")),
            ),
            (
                "Host Memory Total",
                _format_mib_range(
                    summary.get("memory_total_mib_min"),
                    summary.get("memory_total_mib_max"),
                ),
            ),
            (
                "Min Memory Available Before Run",
                _format_mib(summary.get("memory_available_mib_min")),
            ),
            (
                "Max Load Average Before Run",
                _format_load_summary(
                    summary.get("load_average_1m_max"),
                    summary.get("load_average_5m_max"),
                ),
            ),
            ("GPUs Observed", summary.get("observed_gpu_count")),
            (
                "GPU Memory Used Before Run",
                _format_mib(summary.get("gpu_memory_used_total_mib")),
            ),
            (
                "Compute Processes Before Run",
                _format_process_summary(
                    summary.get("gpu_compute_process_count"),
                    summary.get("gpu_compute_memory_used_mib"),
                ),
            ),
            ("Snapshot Hash", node_status_snapshot.get("hash")),
        ]
    )
    if warnings:
        rows.append({"label": "Warnings", "value": ", ".join(str(item) for item in warnings)})
    if artifact.get("path"):
        rows.append({"label": "Artifact", "value": artifact["path"]})
    return rows


def _list_values(value):
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _unique_strings(values):
    unique_values = []
    seen = set()
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        unique_values.append(text)
    return unique_values


def _format_observed_total(observed, total):
    if observed in (None, "") and total in (None, ""):
        return "not recorded"
    if total in (None, ""):
        return str(observed)
    return f"{observed or 0}/{total}"


def _format_mib(value):
    if value in (None, ""):
        return "not recorded"
    return f"{format_numeric_value(value)} MiB"


def _format_mib_range(min_value, max_value):
    if min_value in (None, "") and max_value in (None, ""):
        return "not recorded"
    if min_value == max_value or max_value in (None, ""):
        return _format_mib(min_value)
    if min_value in (None, ""):
        return _format_mib(max_value)
    return f"{format_numeric_value(min_value)}-{format_numeric_value(max_value)} MiB"


def _format_value_list(values):
    if not isinstance(values, list) or not values:
        return "not recorded"
    return ", ".join(_format_count_value(value) for value in values)


def _format_load_summary(one_minute, five_minutes):
    if one_minute in (None, "") and five_minutes in (None, ""):
        return "not recorded"
    values = []
    if one_minute not in (None, ""):
        values.append(f"1m={format_numeric_value(one_minute)}")
    if five_minutes not in (None, ""):
        values.append(f"5m={format_numeric_value(five_minutes)}")
    return "; ".join(values)


def _format_count_value(value):
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric_value.is_integer():
        return str(int(numeric_value))
    return format_numeric_value(value)


def _format_process_summary(count, memory_mib):
    if count in (None, ""):
        return "not recorded"
    memory_text = _format_mib(memory_mib)
    return f"{count} process(es); {memory_text}"


def _choose_uploaded_filename(candidates, uploaded):
    for filename in candidates:
        if filename in uploaded:
            return filename
    return candidates[0]


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


def _build_timing_observation_rows(timing_observations):
    if not isinstance(timing_observations, dict):
        return []

    observations = timing_observations.get("observations")
    if not isinstance(observations, list):
        return []

    rows = []
    for index, observation in enumerate(observations, start=1):
        if not isinstance(observation, dict):
            continue
        label = str(observation.get("id") or f"Observation {index}")
        rows.append({"label": label, "value": _format_timing_observation(observation)})
    return rows


def _format_timing_observation(observation):
    parts = []
    for label, value in (
        ("producer", observation.get("producer")),
        ("kind", observation.get("kind")),
        ("format", observation.get("format")),
    ):
        value = str(value or "").strip()
        if value:
            parts.append(f"{label}={value}")

    artifact = observation.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    artifact_path = str(artifact.get("path") or "").strip()
    if artifact_path:
        parts.append(f"artifact={artifact_path}")

    summary = observation.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    timer_count = summary.get("timer_count")
    schema_record_count = summary.get("schema_record_count")
    if timer_count not in (None, ""):
        parts.append(f"timers={timer_count}")
    if schema_record_count not in (None, ""):
        parts.append(f"schema records={schema_record_count}")
    if summary.get("has_overlap_probe_schema") is True:
        parts.append("overlap probe schema=yes")
    elif summary.get("has_overlap_probe_schema") is False:
        parts.append("overlap probe schema=no")

    note = str(observation.get("note") or "").strip()
    if note:
        parts.append(note)

    return "; ".join(parts) if parts else "recorded"


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

    entry_context = "matched" if status == "hit" else "recorded"
    entry = build_cache.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    _append_cache_entry_rows(rows, entry, prefix="", context=entry_context)

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
    _append_cache_entry_rows(rows, rejected_entry, prefix="Rejected ", context="rejected")

    return rows


def _append_cache_entry_rows(rows, entry, *, prefix, context):
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
            "help": build_cache_host_environment_help(context),
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
                "help": build_cache_digest_help(key, context),
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
