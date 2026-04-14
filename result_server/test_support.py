import sys
import types

from flask import Blueprint, Flask


def install_portal_test_stubs(*, include_redis=True, include_otp=True):
    """Install lightweight stubs for optional portal test dependencies."""
    if include_redis and "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")

    if not include_otp:
        return

    otp_mod = types.ModuleType("utils.otp_manager")
    otp_mod.get_affiliations = lambda email: ["dev"]
    otp_mod.is_allowed = lambda email: True
    sys.modules["utils.otp_manager"] = otp_mod

    otp_redis_mod = types.ModuleType("utils.otp_redis_manager")
    otp_redis_mod.get_affiliations = lambda email: ["dev"]
    otp_redis_mod.is_allowed = lambda email: True
    otp_redis_mod.send_otp = lambda email: (True, "stub")
    otp_redis_mod.verify_otp = lambda email, code: True
    otp_redis_mod.invalidate_otp = lambda email: None
    sys.modules["utils.otp_redis_manager"] = otp_redis_mod


def build_portal_shell_app(*, templates_dir, include_home_route=True, include_systemlist_route=True):
    """Build a lightweight Flask app with common portal shell routes for template tests."""
    app = Flask(__name__, template_folder=templates_dir)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    results_bp = Blueprint("results", __name__)
    estimated_bp = Blueprint("estimated", __name__)
    auth_bp = Blueprint("auth", __name__)
    admin_bp = Blueprint("admin", __name__)

    @results_bp.route("/")
    def results():
        return ""

    @results_bp.route("/compare")
    def result_compare():
        return ""

    @results_bp.route("/detail/<filename>")
    def result_detail(filename):
        return filename

    @results_bp.route("/usage")
    def usage_report():
        return ""

    @estimated_bp.route("/")
    def estimated_results():
        return ""

    @estimated_bp.route("/detail/<filename>")
    def estimated_detail(filename):
        return filename

    @estimated_bp.route("/show/<filename>")
    def show_estimated_result(filename):
        return filename

    @auth_bp.route("/login")
    def login():
        return ""

    @auth_bp.route("/setup/<token>")
    def setup(token):
        return token

    @admin_bp.route("/users")
    def users():
        return ""

    @admin_bp.route("/users/add", methods=["POST"])
    def add_user():
        return ""

    @admin_bp.route("/users/<path:email>/affiliations", methods=["POST"])
    def update_affiliations(email):
        return email

    @admin_bp.route("/users/<path:email>/reinvite", methods=["POST"])
    def reinvite_user(email):
        return email

    @admin_bp.route("/users/<path:email>/delete", methods=["POST"])
    def delete_user(email):
        return email

    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    if include_home_route:
        @app.route("/")
        def home():
            return ""

    if include_systemlist_route:
        @app.route("/systemlist")
        def systemlist():
            return ""

    return app


def build_results_index_app():
    """Build a minimal Flask app with the results index route for redirect helpers."""
    app = Flask(__name__)
    results_bp = Blueprint("results", __name__)

    @results_bp.route("/")
    def results():
        return ""

    app.register_blueprint(results_bp, url_prefix="/results")
    return app


def build_results_route_app(
    *,
    received_dir,
    estimated_dir=None,
    received_padata_dir=None,
    templates_dir=None,
):
    """Build a Flask app with the real results blueprint for focused route tests."""
    app_kwargs = {"template_folder": templates_dir} if templates_dir else {}
    app = Flask(__name__, **app_kwargs)
    app.config["RECEIVED_DIR"] = received_dir
    app.config["ESTIMATED_DIR"] = estimated_dir or received_dir
    app.config["TESTING"] = True
    app.secret_key = "test-secret"

    if received_padata_dir is not None:
        app.config["RECEIVED_PADATA_DIR"] = received_padata_dir

    from routes.results import results_bp

    app.register_blueprint(results_bp, url_prefix="/results")
    return app


def build_api_route_app(
    *,
    received_dir,
    received_padata_dir,
    received_estimation_inputs_dir,
    estimated_dir,
):
    """Build a Flask app with the API, results, and estimated blueprints for API tests."""
    app = Flask(__name__)
    app.config["RECEIVED_DIR"] = received_dir
    app.config["RECEIVED_PADATA_DIR"] = received_padata_dir
    app.config["RECEIVED_ESTIMATION_INPUTS_DIR"] = received_estimation_inputs_dir
    app.config["ESTIMATED_DIR"] = estimated_dir
    app.config["TESTING"] = True

    from routes.api import api_bp
    from routes.estimated import estimated_bp
    from routes.results import results_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    return app


class StaticAffiliationUserStore:
    """Return fixed affiliations for test users."""

    def __init__(self, affiliations_by_email):
        self._affiliations_by_email = affiliations_by_email

    def get_affiliations(self, email):
        return self._affiliations_by_email.get(email, [])


def build_portal_route_app(
    *,
    templates_dir,
    received_dir,
    estimated_dir,
    user_store=None,
    totp_issuer=None,
    include_admin=True,
):
    """Build a Flask app with the real portal route blueprints used by route tests."""
    app = Flask(__name__, template_folder=templates_dir)
    app.config["RECEIVED_DIR"] = received_dir
    app.config["ESTIMATED_DIR"] = estimated_dir
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    if user_store is not None:
        app.config["USER_STORE"] = user_store

    if totp_issuer is not None:
        app.config["TOTP_ISSUER"] = totp_issuer

    from routes.auth import auth_bp
    from routes.estimated import estimated_bp
    from routes.home import register_home_routes
    from routes.results import results_bp

    register_home_routes(app)
    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp, url_prefix="/auth")

    if include_admin:
        from routes.admin import admin_bp

        app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.route("/systemlist")
    def systemlist():
        return ""

    return app
