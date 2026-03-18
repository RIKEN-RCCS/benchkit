import os
import sys
from datetime import timedelta

# Retrieve the API key from environment variable (needed in receive.py)
EXPECTED_API_KEY = os.environ.get("RESULT_SERVER_KEY")

# Exit if the API key is not set
if not EXPECTED_API_KEY:
    print("ERROR: RESULT_SERVER_KEY is not set.", file=sys.stderr)
    sys.exit(1)

# Import Flask and route blueprints
from flask import Flask, render_template, current_app
from flask_session import Session
from routes.api import api_bp
from routes.results import results_bp
from routes.estimated import estimated_bp

# -----------------------------------------
# Create Flask application
# -----------------------------------------
def create_app(prefix="", base_dir=None):

    """
    prefix: URL prefix (""=For main, "/dev"=For develop)
    base_dir: For main : main, For develop: dev1)
    """
    if base_dir is None:
        raise ValueError("base_dir must be specified")

    # Create the Flask app and specify the templates folder
    app = Flask(__name__, template_folder="templates")

    # Set a secret key for session management (required for flash and OTP sessions)
    # In production, use a secure random key, e.g., os.urandom(24)
    #app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key")

    # --- Secret Key ---
    secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not secret_key:
        raise RuntimeError("FLASK_SECRET_KEY must be set in production")
    app.secret_key = secret_key

    # --- セッションCookieのセキュリティ設定 ---
    app.config.update(
        SESSION_TYPE='filesystem',
        SESSION_FILE_DIR=os.path.join(base_dir, "flask_session"),
        SESSION_PERMANENT=True,
        SESSION_USE_SIGNER=True,
        SESSION_COOKIE_SECURE=True,       # HTTPS必須
        SESSION_COOKIE_HTTPONLY=True,     # JSからのアクセス禁止
        SESSION_COOKIE_SAMESITE="Strict", # もしくは "Lax"
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),  # セッション寿命を短めに
    )
    Session(app)


    # Redis 接続
    import redis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    r_conn = redis.from_url(redis_url, decode_responses=True)

    # 環境ごとの prefix
    if prefix == "/dev":
        app.config["SESSION_COOKIE_NAME"] = "session_dev"
        key_prefix = "dev:"
    else:
        app.config["SESSION_COOKIE_NAME"] = "session_main"
        key_prefix = "main:"

    # Redis接続とプレフィックスをconfigに保存
    app.config["REDIS_CONN"] = r_conn
    app.config["REDIS_PREFIX"] = key_prefix

    # UserStore 初期化
    from utils.user_store import UserStore
    user_store = UserStore(r_conn, key_prefix)
    app.config["USER_STORE"] = user_store

    # TOTP イシュアー名（認証アプリでの表示名）
    app.config["TOTP_ISSUER"] = "BenchKit-Dev" if prefix == "/dev" else "BenchKit"

    # 他でもredisを使う場合、
    #app.redis = r_conn
    #app.redis_prefix = key_prefix




    # make dir, !!!!!!!!                   received & estimated_results
    received_dir = os.path.join(base_dir, "received")
    estimated_dir = os.path.join(base_dir, "estimated_results")
    os.makedirs(received_dir, exist_ok=True)
    os.makedirs(estimated_dir, exist_ok=True)

    app.config["RECEIVED_DIR"] = received_dir
    app.config["ESTIMATED_DIR"] = estimated_dir

    # Register route blueprints
    from routes.auth import auth_bp
    from routes.admin import admin_bp
    app.register_blueprint(api_bp, url_prefix=prefix)
    app.register_blueprint(results_bp, url_prefix=f"{prefix}/results")
    app.register_blueprint(estimated_bp, url_prefix=f"{prefix}/estimated")
    app.register_blueprint(auth_bp, url_prefix=f"{prefix}/auth")
    app.register_blueprint(admin_bp, url_prefix=f"{prefix}/admin")

    @app.route(f"{prefix}/systemlist")
    def systemlist():
        from utils.system_info import get_all_systems_info
        systems_info = get_all_systems_info()
        return render_template("systemlist.html", systems_info=systems_info)

    return app


# -----------------------------------------
# Create main, dev application
# -----------------------------------------
BASE_PATH = os.getenv("BASE_PATH")
if not BASE_PATH:
    sys.stderr.write("ERROR: BASE_PATH environment variable is not set.\n")
    sys.exit(1)


# Main
app = create_app(prefix="", base_dir=os.path.join(BASE_PATH, "main"))

# Develop
app_dev = create_app(prefix="/dev", base_dir=os.path.join(BASE_PATH, "dev1"))


@app.route("/")
def index():
    return "Flask app is running!"

# -----------------------------------------
# Development server startup (only when running python app.py directly)
# Ignored when running with Gunicorn
# -----------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8800)
