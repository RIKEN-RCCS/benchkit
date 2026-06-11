import os
import sys
from datetime import timedelta

from flask import Flask, jsonify, render_template
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

from routes.api import api_bp
from routes.estimated import estimated_bp
from routes.home import register_home_routes
from routes.results import results_bp
from utils.admin_policy import parse_allowed_affiliations
from utils.audit_logging import configure_audit_logging
from utils.auth import parse_ingest_keys
from utils.csrf import init_csrf
from utils.preflight import validate_production_config


DEFAULT_MAX_UPLOAD_MB = 512
DEFAULT_MAX_ARCHIVE_MEMBER_MB = 1024
INGEST_KEYS = parse_ingest_keys()
PREFLIGHT_ERRORS = validate_production_config(os.environ, INGEST_KEYS)

if PREFLIGHT_ERRORS:
    for error in PREFLIGHT_ERRORS:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)


def _configure_session(app, base_dir):
    """Configure secure filesystem-backed sessions."""
    app.config.update(
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR=os.path.join(base_dir, "flask_session"),
        SESSION_PERMANENT=True,
        SESSION_USE_SIGNER=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    )
    Session(app)


def _configure_proxy_fix(app):
    """Trust the single nginx reverse proxy in front of production gunicorn."""
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)


def _configure_redis(app, prefix):
    """Attach Redis connection settings and the key prefix to app config."""
    import redis

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    app.config["REDIS_CONN"] = redis.from_url(redis_url, decode_responses=True)
    app.config["REDIS_PREFIX"] = "dev:" if prefix == "/dev" else "main:"
    app.config["SESSION_COOKIE_NAME"] = "session_dev" if prefix == "/dev" else "session_main"
    app.config["AUTH_REQUIRES_REDIS"] = True


def _configure_user_store(app):
    """Create and attach the shared UserStore instance."""
    from utils.user_store import UserStore

    app.config["USER_STORE"] = UserStore(app.config["REDIS_CONN"], app.config["REDIS_PREFIX"])


def _configure_totp_issuer(app, prefix):
    """Set the issuer label shown by authenticator apps."""
    base_issuer = os.environ.get("TOTP_ISSUER", "BenchKit")
    app.config["TOTP_ISSUER"] = f"{base_issuer}-Dev" if prefix == "/dev" else base_issuer


def _configure_result_directories(app, base_dir):
    """Create and register the runtime data directories."""
    dir_map = {
        "RECEIVED_DIR": os.path.join(base_dir, "received"),
        "RECEIVED_PADATA_DIR": os.path.join(base_dir, "received_padata"),
        "RECEIVED_ESTIMATION_ARTIFACTS_DIR": os.path.join(base_dir, "received_estimation_artifacts"),
        "ESTIMATED_DIR": os.path.join(base_dir, "estimated_results"),
    }
    for path in dir_map.values():
        os.makedirs(path, exist_ok=True)
    app.config.update(dir_map)


def _configure_upload_limits(app):
    """Configure request and archive size limits for ingest endpoints."""
    max_upload_mb = int(os.environ.get("RESULT_SERVER_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB))
    max_member_mb = int(
        os.environ.get("RESULT_SERVER_MAX_ARCHIVE_MEMBER_MB", DEFAULT_MAX_ARCHIVE_MEMBER_MB)
    )
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024
    app.config["MAX_ARCHIVE_MEMBER_SIZE"] = max_member_mb * 1024 * 1024

    @app.errorhandler(413)
    def payload_too_large(_error):
        return jsonify(
            error="Payload too large",
            limit_mb=app.config["MAX_CONTENT_LENGTH"] // 1024 // 1024,
        ), 413


def _configure_admin_policy(app):
    """Configure admin-route policy settings."""
    app.config["ALLOWED_AFFILIATIONS"] = parse_allowed_affiliations(
        os.environ.get("RESULT_SERVER_ALLOWED_AFFILIATIONS")
    )


def _register_portal_blueprints(app, prefix):
    """Register all portal blueprints using the given URL prefix."""
    from routes.admin import admin_bp
    from routes.auth import auth_bp
    from routes.security_metadata import register_security_metadata_routes

    register_security_metadata_routes(app, prefix=prefix)
    app.register_blueprint(api_bp, url_prefix=prefix)
    app.register_blueprint(results_bp, url_prefix=f"{prefix}/results")
    app.register_blueprint(estimated_bp, url_prefix=f"{prefix}/estimated")
    app.register_blueprint(auth_bp, url_prefix=f"{prefix}/auth")
    app.register_blueprint(admin_bp, url_prefix=f"{prefix}/admin")


def create_app(prefix="", base_dir=None):
    """Create a configured Flask application for the main or dev portal."""
    if base_dir is None:
        raise ValueError("base_dir must be specified")

    app = Flask(__name__, template_folder="templates")
    _configure_proxy_fix(app)

    secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY must be set in production")
    app.secret_key = secret_key
    app.config["INGEST_KEYS"] = INGEST_KEYS.copy()
    configure_audit_logging(app)

    _configure_session(app, base_dir)
    _configure_redis(app, prefix)
    _configure_user_store(app)
    _configure_totp_issuer(app, prefix)
    _configure_result_directories(app, base_dir)
    _configure_upload_limits(app)
    _configure_admin_policy(app)
    init_csrf(app, exempt_blueprints=(api_bp,))

    register_home_routes(app, prefix=prefix)
    _register_portal_blueprints(app, prefix)

    @app.route(f"{prefix}/systemlist")
    def systemlist():
        from utils.system_info import get_all_systems_info, summarize_systems_info

        systems_info = get_all_systems_info()
        return render_template(
            "systemlist.html",
            systems_info=systems_info,
            systems_summary=summarize_systems_info(systems_info),
        )

    return app


BASE_PATH = os.getenv("BASE_PATH")
if not BASE_PATH:
    sys.stderr.write("ERROR: BASE_PATH environment variable is not set.\n")
    sys.exit(1)


app = create_app(prefix="", base_dir=os.path.join(BASE_PATH, "main"))
app_dev = create_app(prefix="/dev", base_dir=os.path.join(BASE_PATH, "dev1"))


if __name__ == "__main__":
    host = os.environ.get("RESULT_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("RESULT_SERVER_PORT", "8800"))
    app.run(host=host, port=port)
