import json
import os
import re

from flask import abort, current_app, render_template, request, url_for
from werkzeug.exceptions import Forbidden, NotFound

from utils.environment_snapshots import (
    get_environment_snapshot,
    list_environment_snapshot_results,
)
from utils.node_hours import compute_node_hours
from utils.evidence_packet import (
    build_result_evidence_packet,
    evidence_packet_download_name,
)
from utils.public_reuse import (
    build_public_reuse_manifest,
    build_public_reuse_markdown_packet,
    build_reuse_detail_rows,
    evaluate_public_reuse_packet,
    public_reuse_manifest_download_name,
    public_reuse_packet_download_name,
)
from utils.result_compare_view import load_result_compare_context
from utils.result_detail_view import build_result_detail_context
from utils.result_file import (
    get_file_confidential_tags,
    load_public_result_json,
    load_permitted_result_json,
    serve_permitted_result_file,
    serve_public_padata_file,
)
from utils.result_records import (
    format_numeric_value,
    format_result_timestamp,
    summarize_result_quality,
)
from utils.trigger_display import load_trigger_run_lookup, summarize_execution_trigger


PADATA_ARTIFACT_BASENAME_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:tgz|tar\.gz)"
)


def register_results_detail_routes(results_bp):
    def public_surface():
        return current_app.config.get("PUBLIC_PORTAL_MODE", False)

    @results_bp.route("/compare", methods=["GET"])
    def result_compare():
        files_param = request.args.get("files", "")
        filenames = [name.strip() for name in files_param.split(",") if name.strip()]

        if len(filenames) < 2:
            abort(400, "Select 2 or more results to compare")

        compare_context = load_result_compare_context(
            filenames,
            current_app.config["RECEIVED_DIR"],
            public_surface=public_surface(),
        )
        return render_template("result_compare.html", **compare_context)

    @results_bp.route("/detail/<filename>")
    def result_detail(filename):
        is_public_surface = public_surface()
        if is_public_surface:
            result = load_public_result_json(
                filename,
                current_app.config["RECEIVED_DIR"],
                not_found_message="Result file not found",
            )
        else:
            result = load_permitted_result_json(
                filename,
                current_app.config["RECEIVED_DIR"],
                not_found_message="Result file not found",
            )
        quality = summarize_result_quality(result)
        padata_dir = current_app.config.get("RECEIVED_PADATA_DIR", current_app.config["RECEIVED_DIR"])
        padata_filenames = _list_result_padata_filenames(result, padata_dir) if is_public_surface else [
            name for name in os.listdir(padata_dir) if name.endswith(".tgz")
        ]
        detail_context = build_result_detail_context(
            result,
            quality,
            load_trigger_run_lookup(current_app.config.get("EXECUTION_PROFILE_DB_PATH")),
            padata_filenames,
            public_surface=is_public_surface,
        )
        public_result = not get_file_confidential_tags(filename, current_app.config["RECEIVED_DIR"])
        reuse_eligibility = evaluate_public_reuse_packet(result, public_result=public_result)
        detail_context["reuse_packet_rows"] = (
            []
            if is_public_surface
            else build_reuse_detail_rows(
                result,
                public_result=public_result,
            )
        )
        detail_context["reuse_packet_url"] = (
            url_for("results.result_reuse_packet", filename=filename)
            if reuse_eligibility["eligible"] and not is_public_surface
            else ""
        )
        detail_context["reuse_manifest_url"] = (
            url_for("results.result_reuse_manifest", filename=filename)
            if reuse_eligibility["eligible"] and not is_public_surface
            else ""
        )
        if detail_context.get("environment_snapshot_hash") and not is_public_surface:
            detail_context["environment_snapshot_results_url"] = url_for(
                "results.environment_snapshot_results",
                snapshot_hash=detail_context["environment_snapshot_hash"],
            )
        detail_context["evidence_packet_url"] = (
            ""
            if is_public_surface
            else url_for("results.result_evidence_packet", filename=filename)
        )
        return render_template("result_detail.html", result=result, quality=quality, **detail_context)

    @results_bp.route("/detail/<filename>/evidence-packet.md")
    def result_evidence_packet(filename):
        is_public_surface = public_surface()
        if is_public_surface:
            abort(404, "Result file not found")

        result = load_permitted_result_json(
            filename,
            current_app.config["RECEIVED_DIR"],
            not_found_message="Result file not found",
        )
        quality = summarize_result_quality(result)
        padata_dir = current_app.config.get("RECEIVED_PADATA_DIR", current_app.config["RECEIVED_DIR"])
        padata_filenames = [name for name in os.listdir(padata_dir) if name.endswith(".tgz")]
        padata_urls = {
            name: url_for("results.show_result", filename=name)
            for name in padata_filenames
        }
        packet = build_result_evidence_packet(
            result,
            filename,
            quality,
            public_surface=False,
            detail_url=url_for("results.result_detail", filename=filename),
            raw_json_url=url_for("results.show_result", filename=filename),
            padata_filenames=padata_filenames,
            padata_url_by_filename=padata_urls,
        )

        response = current_app.response_class(
            packet,
            content_type="text/markdown; charset=utf-8",
        )
        response.headers["Content-Disposition"] = (
            f"attachment; filename={evidence_packet_download_name(filename)}"
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    @results_bp.route("/detail/<filename>/reuse-packet.md")
    def result_reuse_packet(filename):
        if public_surface():
            abort(404, "Result file not found")

        result = load_public_result_json(
            filename,
            current_app.config["RECEIVED_DIR"],
            not_found_message="Result file not found",
        )
        manifest = _build_public_reuse_manifest_for_route(result, filename)
        if not manifest["eligibility"]["eligible"]:
            abort(404, "Result file not found")

        packet = build_public_reuse_markdown_packet(manifest)
        response = current_app.response_class(
            packet,
            content_type="text/markdown; charset=utf-8",
        )
        response.headers["Content-Disposition"] = (
            f"attachment; filename={public_reuse_packet_download_name(filename)}"
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    @results_bp.route("/detail/<filename>/reuse-manifest.json")
    def result_reuse_manifest(filename):
        if public_surface():
            abort(404, "Result file not found")

        result = load_public_result_json(
            filename,
            current_app.config["RECEIVED_DIR"],
            not_found_message="Result file not found",
        )
        manifest = _build_public_reuse_manifest_for_route(result, filename)
        if not manifest["eligibility"]["eligible"]:
            abort(404, "Result file not found")

        response = current_app.response_class(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            content_type="application/json; charset=utf-8",
        )
        response.headers["Content-Disposition"] = (
            f"attachment; filename={public_reuse_manifest_download_name(filename)}"
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    @results_bp.route("/environment-snapshots/<path:snapshot_hash>")
    def environment_snapshot_results(snapshot_hash):
        if public_surface():
            abort(404)

        db_path = current_app.config.get("EXECUTION_PROFILE_DB_PATH")
        snapshot = get_environment_snapshot(db_path, snapshot_hash)
        if snapshot is None:
            abort(404, "Environment snapshot not found")

        trigger_run_lookup = load_trigger_run_lookup(db_path)
        result_rows = []
        for link in list_environment_snapshot_results(db_path, snapshot_hash):
            filename = link.get("json_file") or ""
            try:
                result = load_permitted_result_json(
                    filename,
                    current_app.config["RECEIVED_DIR"],
                    not_found_message="Result file not found",
                )
            except (Forbidden, NotFound):
                continue
            trigger_summary = summarize_execution_trigger(result, trigger_run_lookup)
            result_rows.append({
                "filename": filename,
                "timestamp": format_result_timestamp(filename),
                "code": result.get("code") or link.get("code") or "-",
                "system": result.get("system") or link.get("system") or "-",
                "exp": result.get("Exp") or link.get("exp") or "-",
                "fom": format_numeric_value(result.get("FOM")),
                "fom_unit": result.get("FOM_unit") or "",
                "pipeline_id": result.get("pipeline_id") or link.get("pipeline_id") or "-",
                "node_hours": compute_node_hours(result),
                "trigger_headline": trigger_summary["headline"],
                "trigger_subline": trigger_summary.get("subline") or "",
                "trigger_title": trigger_summary.get("title") or "",
            })

        visible_node_hours = round(sum(row["node_hours"] for row in result_rows), 2)
        result_summary = {
            "visible_count": len(result_rows),
            "linked_count": snapshot.get("result_count") or len(result_rows),
            "node_hours": visible_node_hours,
            "latest_timestamp": result_rows[0]["timestamp"] if result_rows else "-",
        }
        return render_template(
            "environment_snapshot_results.html",
            snapshot=snapshot,
            result_rows=result_rows,
            result_summary=result_summary,
        )

    @results_bp.route("/<filename>")
    def show_result(filename):
        if public_surface():
            if filename.endswith(".tgz"):
                return serve_public_padata_file(
                    filename,
                    current_app.config["RECEIVED_DIR"],
                    current_app.config["RECEIVED_PADATA_DIR"],
                )
            abort(404)

        if filename.endswith(".tgz"):
            return serve_permitted_result_file(
                filename,
                current_app.config["RECEIVED_DIR"],
                current_app.config["RECEIVED_PADATA_DIR"],
            )
        return serve_permitted_result_file(filename, current_app.config["RECEIVED_DIR"])

    def _build_public_reuse_manifest_for_route(result, filename):
        padata_dir = current_app.config.get("RECEIVED_PADATA_DIR", current_app.config["RECEIVED_DIR"])
        padata_filenames = _list_result_padata_filenames(result, padata_dir)
        padata_urls = {
            name: url_for("results.show_result", filename=name)
            for name in padata_filenames
        }
        return build_public_reuse_manifest(
            result,
            filename,
            detail_url=url_for("results.result_detail", filename=filename),
            packet_url=url_for("results.result_reuse_packet", filename=filename),
            manifest_url=url_for("results.result_reuse_manifest", filename=filename),
            padata_filenames=padata_filenames,
            padata_url_by_filename=padata_urls,
        )


def _list_result_padata_filenames(result, padata_dir):
    result_uuid = _clean_result_value(result.get("_server_uuid"))
    timestamp = _clean_result_value(result.get("_server_timestamp"))
    if not result_uuid or not timestamp:
        return []

    filenames = []
    seen = set()
    for artifact_path in _iter_result_padata_artifact_paths(result):
        artifact_slug = _padata_artifact_slug(artifact_path)
        if not artifact_slug:
            continue
        filename = f"padata_{timestamp}_{result_uuid}_{artifact_slug}.tgz"
        if filename in seen:
            continue
        seen.add(filename)
        if os.path.isfile(os.path.join(padata_dir, filename)):
            filenames.append(filename)
    return filenames


def _iter_result_padata_artifact_paths(result):
    breakdown = result.get("fom_breakdown")
    if not isinstance(breakdown, dict):
        return
    for collection_name in ("sections", "overlaps"):
        for item in breakdown.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            for artifact in item.get("artifacts") or []:
                if not isinstance(artifact, dict) or artifact.get("type") != "file_reference":
                    continue
                path = _clean_result_value(artifact.get("path"))
                if path:
                    yield path


def _padata_artifact_slug(artifact_path):
    if not isinstance(artifact_path, str) or not artifact_path.startswith("results/"):
        return ""
    basename = os.path.basename(artifact_path)
    if not PADATA_ARTIFACT_BASENAME_RE.fullmatch(basename):
        return ""
    return basename[:-7] if basename.endswith(".tar.gz") else basename[:-4]


def _clean_result_value(value):
    return str(value or "").strip()
