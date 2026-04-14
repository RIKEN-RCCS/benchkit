from utils.result_records import format_numeric_value


def build_result_detail_context(result, quality, filename):
    profile_data = result.get("profile_data") or {}
    build_data = result.get("build") or {}
    vector_metrics = (result.get("metrics") or {}).get("vector")
    scalar_metrics = (result.get("metrics") or {}).get("scalar") or {}

    return {
        "filename": filename,
        "title_exp": result.get("Exp", "Unknown"),
        "meta_rows": _build_meta_rows(result),
        "profile_rows": _build_profile_rows(profile_data),
        "quality_rows": _build_quality_rows(quality),
        "vector_metrics": vector_metrics,
        "scalar_rows": _build_scalar_rows(scalar_metrics),
        "build_rows": _build_build_rows(build_data),
    }


def _build_meta_rows(result):
    rows = [
        {"label": "Code", "value": result.get("code", "N/A")},
        {"label": "System", "value": result.get("system", "N/A")},
        {"label": "Exp", "value": result.get("Exp", "N/A")},
        {"label": "FOM", "value": format_numeric_value(result.get("FOM", "N/A"))},
        {"label": "FOM Unit", "value": result.get("FOM_unit") or "implicit default (s)"},
        {"label": "Node Count", "value": result.get("node_count", "N/A")},
    ]

    optional_rows = [
        ("Processes per Node", result.get("numproc_node")),
        ("Threads per Process", result.get("nthreads")),
        ("CPUs per Node", result.get("cpus_per_node")),
    ]
    for label, value in optional_rows:
        if value not in (None, "", "N/A", "null"):
            rows.append({"label": label, "value": value})
    return rows


def _build_profile_rows(profile_data):
    if not profile_data:
        return []

    events = profile_data.get("events") or []
    report_kinds = profile_data.get("report_kinds") or []
    return [
        {"label": "Tool", "value": profile_data.get("tool", "N/A")},
        {"label": "Level", "value": profile_data.get("level", "N/A")},
        {"label": "Report Format", "value": profile_data.get("report_format", "N/A")},
        {"label": "Run Count", "value": profile_data.get("run_count", "N/A")},
        {"label": "Tool-Specific Events", "value": _build_tool_specific_events_description(profile_data)},
        {"label": "Events", "value": ", ".join(events) if events else "none"},
        {"label": "Report Kinds", "value": ", ".join(report_kinds) if report_kinds else "none"},
    ]


def _build_tool_specific_events_description(profile_data):
    if profile_data.get("tool") != "fapp":
        return "tool-specific event set"

    level = profile_data.get("level")
    mapping = {
        "single": "fapp event set: pa1",
        "simple": "fapp event set: pa1..pa5",
        "standard": "fapp event set: pa1..pa11",
        "detailed": "fapp event set: pa1..pa17",
    }
    return mapping.get(level, "fapp tool-specific event set")


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
        {"label": "Warnings", "list": warnings or ["none"]},
    ]


def _build_scalar_rows(scalar_metrics):
    if len(scalar_metrics.keys()) < 2:
        return []
    return [{"label": key, "value": value} for key, value in scalar_metrics.items()]


def _build_build_rows(build_data):
    if not build_data:
        return []

    rows = [{"label": "Build Tool", "value": build_data.get("tool", "N/A")}]
    spack = build_data.get("spack") or {}
    compiler = spack.get("compiler") or {}
    mpi = spack.get("mpi") or {}
    packages = spack.get("packages") or []

    if compiler:
        rows.append({"label": "Compiler", "value": f"{compiler.get('name', '')} {compiler.get('version', '')}".strip()})
    if mpi:
        rows.append({"label": "MPI", "value": f"{mpi.get('name', '')} {mpi.get('version', '')}".strip()})
    if packages:
        rows.append({
            "label": "Packages",
            "list": [f"{pkg.get('name', '')} {pkg.get('version', '')}".strip() for pkg in packages],
        })
    return rows
