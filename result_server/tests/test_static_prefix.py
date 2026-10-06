"""Exercise the production factory in isolation, without live stores or credentials."""

import os
from pathlib import Path
import secrets
import subprocess
import sys


def test_static_assets_follow_the_application_prefix(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = '''
from unittest.mock import patch
from flask import url_for
import fakeredis
with patch("redis.from_url", return_value=fakeredis.FakeRedis(decode_responses=True)):
    from app import create_app
    for index, prefix in enumerate(("", "/preview", "/preview/console")):
        app = create_app(prefix=prefix, base_dir=BASE + "/case" + str(index))
        with app.test_request_context():
            path = url_for("static", filename="js/result_charts.js")
        assert path == prefix + "/static/js/result_charts.js"
        with app.test_client() as client:
            with client.get(path) as response:
                assert response.status_code == 200
                assert b"createElementNS" in response.data
            assert client.get(prefix + "/static/vendor/chartjs/chart.umd.min.js").status_code == 404
            if prefix:
                assert client.get("/static/js/result_charts.js").status_code == 404
'''
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(root / "result_server"),
        "BASE_PATH": str(tmp_path),
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "RESULT_SERVER_KEYS": "test:" + secrets.token_hex(32),
    }
    result = subprocess.run(
        [sys.executable, "-c", "import os; BASE = os.environ['BASE_PATH']\n" + script],
        cwd=root, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
