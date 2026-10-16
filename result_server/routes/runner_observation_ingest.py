"""Opt-in, console-only receiver for scoped runner observations."""

from datetime import datetime, timezone
import os

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from utils.encrypted_sqlite import EncryptedDatabaseError
from utils.rate_limit import enforce_rate_limit
from utils.runner_observation_auth import (
    ObservationConfigurationError,
    authenticate_observation_key,
    configured_observation_sources,
)
from utils.runner_observation_protocol import MAX_BYTES, ProtocolError, validate_batch
from utils.runner_observations import RunnerObservations


runner_observation_ingest_bp = Blueprint("runner_observation_ingest", __name__)


def register_runner_observation_ingest(app, prefix="", *, env=None):
    source = os.environ if env is None else env
    enabled = source.get("RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED", "").lower() in {"1", "true"}
    app.config["RUNNER_OBSERVATION_INGEST_ENABLED"] = enabled
    app.config["RUNNER_OBSERVATION_SOURCES"] = None
    if not enabled or app.config.get("PUBLIC_PORTAL_MODE"):
        return
    try:
        app.config["RUNNER_OBSERVATION_SOURCES"] = configured_observation_sources(
            source, forbidden_keys=app.config.get("INGEST_KEYS") or {})
    except ObservationConfigurationError:
        pass
    app.register_blueprint(runner_observation_ingest_bp, url_prefix=prefix)


@runner_observation_ingest_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@runner_observation_ingest_bp.errorhandler(HTTPException)
@runner_observation_ingest_bp.errorhandler(413)
def http_error(error):
    code = {400: "invalid_request", 413: "payload_too_large", 429: "rate_limited"}.get(error.code, "unavailable")
    return jsonify(error=code), error.code


@runner_observation_ingest_bp.route("/api/v1/runner-observations", methods=["POST"])
def ingest():
    if current_app.config.get("PUBLIC_PORTAL_MODE") or not current_app.config.get("RUNNER_OBSERVATION_INGEST_ENABLED"):
        return jsonify(error="not_found"), 404
    sources = current_app.config.get("RUNNER_OBSERVATION_SOURCES")
    if not sources:
        return jsonify(error="observation_configuration_unavailable"), 503
    try:
        policy = authenticate_observation_key(request.headers.get("X-Collector-Key"), sources)
        enforce_rate_limit(redis_conn=current_app.config.get("REDIS_CONN"),
                           key_suffix="source:" + policy.source_id, max_per_minute=20, scope="runner_observation")
        if request.mimetype != "application/json" or request.headers.get("Content-Encoding", "identity") != "identity":
            return jsonify(error="unsupported_media_type"), 415
        if request.content_length is not None and request.content_length > MAX_BYTES:
            return jsonify(error="payload_too_large"), 413
        raw = request.stream.read(MAX_BYTES + 1)
        received_at = datetime.now(timezone.utc)
        # Reject unauthorized or malformed content before touching the store.
        validate_batch(raw, policy, received_at=received_at)
        path = current_app.config.get("RUNNER_MONITOR_DB_PATH")
        key_file = current_app.config.get("RUNNER_MONITOR_KEY_FILE")
        if not path or not key_file:
            return jsonify(error="observation_storage_unavailable"), 503
        update = RunnerObservations(path, key_file).ingest(raw, policy, received_at=received_at)
        current_app.logger.info("runner observation batch %s", update.acknowledgement["status"],
                                extra={"source_id": policy.source_id, "sequence": update.acknowledgement["sequence"]})
        return jsonify(update.acknowledgement), 200
    except ProtocolError as error:
        current_app.logger.warning("runner observation rejected: %s", error.code,
                                   extra={"status_code": error.status})
        return jsonify(error=error.code), error.status
    except EncryptedDatabaseError:
        return jsonify(error="observation_storage_unavailable"), 503
