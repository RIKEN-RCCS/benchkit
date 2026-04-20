from datetime import datetime

from flask import current_app, render_template, request

from routes.admin import admin_required
from utils.node_hours import get_fiscal_year
from utils.usage_report_view import build_usage_report_context


def register_results_usage_routes(results_bp):
    @results_bp.route("/usage", methods=["GET"])
    @admin_required
    def usage_report():
        usage_context = build_usage_report_context(
            current_app.config["RECEIVED_DIR"],
            request.args,
            get_fiscal_year(datetime.now()),
        )
        return render_template("usage_report.html", **usage_context)
