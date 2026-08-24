import os

from flask import abort, current_app, render_template, request, url_for
from werkzeug.exceptions import Forbidden, NotFound

from utils.environment_snapshots import (
    get_environment_snapshot,
    list_environment_snapshot_results,
)
from utils.node_hours import compute_node_hours
from utils.result_compare_view import load_result_compare_context
from utils.result_detail_view import build_result_detail_context
from utils.result_file import (
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
        padata_filenames = [name for name in os.listdir(padata_dir) if name.endswith(".tgz")]
        detail_context = build_result_detail_context(
            result,
            quality,
            load_trigger_run_lookup(current_app.config.get("EXECUTION_PROFILE_DB_PATH")),
            padata_filenames,
            public_surface=is_public_surface,
        )
        if detail_context.get("environment_snapshot_hash") and not is_public_surface:
            detail_context["environment_snapshot_results_url"] = url_for(
                "results.environment_snapshot_results",
                snapshot_hash=detail_context["environment_snapshot_hash"],
            )
        return render_template("result_detail.html", result=result, quality=quality, **detail_context)

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
