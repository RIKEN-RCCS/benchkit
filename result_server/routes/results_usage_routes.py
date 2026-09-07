import csv
import io
from datetime import datetime

from flask import current_app, render_template, request

from routes.admin import admin_required
from utils.evidence_snapshot import EVIDENCE_SNAPSHOT_CSV_COLUMNS, build_evidence_snapshot
from utils.node_hours import get_fiscal_year
from utils.usage_report_view import build_usage_report_context


def _portal_commit():
    portal_version = current_app.config.get("PORTAL_VERSION")
    if isinstance(portal_version, dict):
        return portal_version.get("commit") or ""
    return ""


def register_results_usage_routes(results_bp):
    @results_bp.route("/usage", methods=["GET"])
    @admin_required
    def usage_report():
        usage_context = build_usage_report_context(
            current_app.config["RECEIVED_DIR"],
            request.args,
            get_fiscal_year(datetime.now()),
            db_path=current_app.config.get("EXECUTION_PROFILE_DB_PATH"),
            estimated_dir=current_app.config.get("ESTIMATED_DIR"),
            benchkit_commit=_portal_commit(),
        )
        return render_template("usage_report.html", **usage_context)

    @results_bp.route("/usage/evidence-snapshot.csv", methods=["GET"])
    @admin_required
    def usage_evidence_snapshot_csv():
        snapshot = build_evidence_snapshot(
            current_app.config["RECEIVED_DIR"],
            current_app.config.get("ESTIMATED_DIR", current_app.config["RECEIVED_DIR"]),
            benchkit_commit=_portal_commit(),
        )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=EVIDENCE_SNAPSHOT_CSV_COLUMNS)
        writer.writeheader()
        for row in snapshot["rows"]:
            writer.writerow({column: row.get(column, "") for column in EVIDENCE_SNAPSHOT_CSV_COLUMNS})

        response = current_app.response_class(output.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=evidence_snapshot_{snapshot['generated_at'][:10]}.csv"
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
