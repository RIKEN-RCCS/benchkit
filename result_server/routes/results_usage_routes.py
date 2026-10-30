import csv
import io
from datetime import datetime

from flask import abort, current_app, render_template, request, url_for

from routes.admin import admin_required
from utils.evidence_snapshot import EVIDENCE_SNAPSHOT_CSV_COLUMNS, build_evidence_snapshot
from utils.node_hours import get_fiscal_year
from utils.usage_report_view import build_usage_report_context
from utils.usage_query_params import parse_usage_query_params
from utils.report_selection import definition_options, usage_requested, usage_selection

REPORTS = {'node_hours': 'Node-Hour Usage', 'profiles': 'Profile Operations',
           'performance': 'Performance Telemetry', 'evidence': 'Evidence Snapshot',
           'configuration': 'Configuration Checks (All Current Definitions)'}


def _selection():
    params = parse_usage_query_params(request.args, get_fiscal_year(datetime.now()))
    try:
        selection = usage_selection(request.args, params['fiscal_year'], params['period_type'], params['period_filter'])
    except ValueError as error:
        abort(400, str(error))
    if any(len(selection[key]) > 128 for key in ('code', 'system')):
        abort(400, 'Report target is too long')
    return params, selection


def _portal_commit():
    portal_version = current_app.config.get("PORTAL_VERSION")
    if isinstance(portal_version, dict):
        return portal_version.get("commit") or ""
    return ""


def register_results_usage_routes(results_bp):
    @results_bp.route("/usage", methods=["GET"])
    @admin_required
    def usage_report():
        report = request.args.get('report', 'node_hours')
        if report not in REPORTS:
            abort(400, 'Unknown report')
        params, selection = _selection()
        execute = usage_requested(request.args)
        context = dict(params)
        if execute:
            context.update(build_usage_report_context(
                current_app.config['RECEIVED_DIR'], request.args, params['fiscal_year'],
                db_path=current_app.config.get('EXECUTION_PROFILE_DB_PATH'),
                estimated_dir=current_app.config.get('ESTIMATED_DIR'),
                benchkit_commit=_portal_commit(), report=report, selection=selection))
        csv_args = dict(params, code=selection['code'], system=selection['system'])
        context.update(report=report, reports=REPORTS, report_executed=execute, selection=selection,
                       filter_options=definition_options(selection['code'], selection['system']),
                       evidence_csv_url=url_for('results.usage_evidence_snapshot_csv', **csv_args))
        return render_template('usage_report.html', **context)

    @results_bp.route("/usage/evidence-snapshot.csv", methods=["GET"])
    @admin_required
    def usage_evidence_snapshot_csv():
        _, selection = _selection()
        snapshot = build_evidence_snapshot(
            current_app.config["RECEIVED_DIR"],
            current_app.config.get("ESTIMATED_DIR", current_app.config["RECEIVED_DIR"]),
            benchkit_commit=_portal_commit(),
            selection=selection,
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
