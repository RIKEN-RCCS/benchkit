"""Administrator-only views of stored observations; never call GitLab on GET."""

import os

from flask import Blueprint, current_app, make_response, redirect, render_template, request, session, url_for

from utils.encrypted_sqlite import EncryptedDatabaseError
from utils.runner_observations import RunnerObservations, presentation
from utils.user_store import get_user_store


runner_monitor_bp = Blueprint("runner_monitor", __name__)


def register_runner_monitor(app, prefix=""):
    app.config["RUNNER_MONITOR_DB_PATH"] = os.environ.get("RESULT_SERVER_RUNNER_MONITOR_DB_PATH", "")
    app.config["RUNNER_MONITOR_KEY_FILE"] = os.environ.get("RESULT_SERVER_RUNNER_MONITOR_KEY_FILE", "")
    app.register_blueprint(runner_monitor_bp, url_prefix=f"{prefix}/runners")


@runner_monitor_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@runner_monitor_bp.route("/", methods=["GET"])
def index():
    if current_app.config.get("PUBLIC_PORTAL_MODE"):
        return "Not found", 404
    if not session.get("authenticated"):
        return redirect(url_for("auth.login"))
    principal = session.get("user_email", "")
    try:
        users = get_user_store()
        if not principal or not users.user_exists(principal) or "admin" not in users.get_affiliations(principal):
            return "Runner access is not permitted", 403
    except Exception:
        return "Identity service is unavailable", 503
    path = current_app.config.get("RUNNER_MONITOR_DB_PATH")
    key = current_app.config.get("RUNNER_MONITOR_KEY_FILE")
    if not path or not key:
        return "Runner observations are not configured", 503
    try:
        catalog = presentation(RunnerObservations(path, key).read())
    except EncryptedDatabaseError:
        return "Runner observations are unavailable", 503
    target = request.args.get("target", "")
    state = request.args.get("state", "")
    query = request.args.get("q", "").strip()[:200]
    selected = []
    for row in catalog["runners"]:
        if target and target not in row["targets"]:
            continue
        if state and state != row["heartbeat"]:
            continue
        record = row["record"] or row["summary"]
        searchable = " ".join([str(row["id"]), row["server"], record.get("description", ""),
                               *record.get("tag_list", [])]).casefold()
        if query and query.casefold() not in searchable:
            continue
        selected.append(row)
    return make_response(render_template("runner_monitor.html", catalog=catalog, runners=selected,
                                         selected_target=target, selected_state=state, query=query))
