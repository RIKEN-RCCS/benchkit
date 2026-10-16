"""Observation-only WSGI factory; no Portal, session, Profile or trigger startup."""

import os

from flask import Flask, jsonify, request
import redis

from routes.runner_observation_ingest import register_runner_observation_ingest
from utils.portal_access import register_public_portal_guard
from utils.runner_observation_service import ObservationServiceError, service_settings


def create_app(env=None):
    source = os.environ if env is None else env
    settings = service_settings(source)
    app = Flask(__name__, static_folder=None)
    app.config.update(
        PUBLIC_PORTAL_MODE=False,
        AUTH_REQUIRES_REDIS=True,
        REDIS_CONN=redis.Redis(unix_socket_path=settings.redis_socket,
                              socket_connect_timeout=5, socket_timeout=5),
        REDIS_PREFIX=settings.redis_prefix,
        RUNNER_MONITOR_DB_PATH=settings.database,
        RUNNER_MONITOR_KEY_FILE=settings.key_file,
    )
    register_runner_observation_ingest(app, settings.url_prefix, env=source)
    if not app.config["RUNNER_OBSERVATION_SOURCES"]:
        raise ObservationServiceError()
    register_public_portal_guard(app)

    @app.before_request
    def require_tls():
        if request.endpoint == "runner_observation_ingest.ingest" and not request.is_secure:
            return jsonify(error="https_required"), 400

    return app
