#!/usr/bin/env python3
"""
BenchKit結果サーバ - ローカル開発用起動スクリプト

Redis/OTP/APIキー不要で起動可能。
テスト用JSONデータを自動生成してresultsを表示確認できる。

使い方:
  cd result_server
  pip install flask flask-session
  python app_dev.py [--port 8800] [--generate-sample]
"""

import os
import sys
import json
import types
import argparse
from datetime import datetime, timedelta
import uuid


def setup_dev_environment(base_dir):
    """開発用の環境変数とディレクトリを設定"""
    os.environ.setdefault("RESULT_SERVER_KEY", "dev-api-key")
    os.environ.setdefault("FLASK_SECRET_KEY", "dev-secret-key")
    os.environ.setdefault("BASE_PATH", base_dir)
    os.environ["DEV_MODE"] = "1"

    # 必要なディレクトリを作成
    for sub in ["main/received", "main/received_padata", "main/received_estimation_inputs", "main/estimated_results", "main/flask_session",
                 "dev1/received", "dev1/received_padata", "dev1/received_estimation_inputs", "dev1/estimated_results", "dev1/flask_session"]:
        os.makedirs(os.path.join(base_dir, sub), exist_ok=True)


def _create_stub_totp_manager():
    """TOTP検証を常に成功させるスタブモジュール"""
    mod = types.ModuleType("utils.totp_manager")
    mod.ISSUER_NAME = "BenchKit"
    mod.generate_secret = lambda: "DEVDEVDEVDEVDEVDEV"
    mod.generate_totp_uri = lambda s, e, **kw: f"otpauth://totp/BenchKit:{e}?secret={s}"
    mod.generate_qr_base64 = lambda s, e, **kw: ""
    mod.verify_code = lambda s, c: True
    mod.check_code_reuse = lambda *a, **kw: False
    mod.check_rate_limit = lambda *a, **kw: False
    mod.record_failed_attempt = lambda *a, **kw: 0
    mod.clear_failed_attempts = lambda *a, **kw: None
    mod.MAX_LOGIN_ATTEMPTS = 5
    return mod


class _StubUserStore:
    """Redis不要のインメモリUserStoreスタブ"""

    def __init__(self):
        self._users = {}
        self._invitations = {}

    def create_user(self, email, totp_secret, affiliations):
        self._users[email] = {"email": email, "totp_secret": totp_secret, "affiliations": list(affiliations)}

    def get_user(self, email):
        return self._users.get(email)

    def delete_user(self, email):
        return self._users.pop(email, None) is not None

    def list_users(self):
        return list(self._users.values())

    def update_affiliations(self, email, affiliations):
        if email in self._users:
            self._users[email]["affiliations"] = list(affiliations)
            return True
        return False

    def user_exists(self, email):
        return email in self._users

    def get_affiliations(self, email):
        u = self._users.get(email)
        return u["affiliations"] if u else ["dev", "admin"]

    def clear_totp_secret(self, email):
        if email in self._users:
            self._users[email]["totp_secret"] = ""
            return True
        return False

    def has_totp_secret(self, email):
        u = self._users.get(email)
        return bool(u and u.get("totp_secret"))

    def create_invitation(self, email, affiliations):
        import secrets as _sec
        token = _sec.token_urlsafe(32)
        self._invitations[token] = {"email": email, "affiliations": list(affiliations)}
        return token

    def get_invitation(self, token):
        return self._invitations.get(token)

    def delete_invitation(self, token):
        self._invitations.pop(token, None)


def create_dev_app(base_dir):
    """開発用Flaskアプリを作成 - Redis/OTP/SMTP不要"""
    # Redis依存モジュールをダミーに差し替え（import前に）
    sys.modules["redis"] = types.ModuleType("redis")
    sys.modules["utils.totp_manager"] = _create_stub_totp_manager()

    from flask import Flask, render_template
    from flask_session import Session

    from routes.home import register_home_routes
    from utils.system_info import get_all_systems_info

    app = Flask(__name__, template_folder="templates")

    app.secret_key = "dev-secret-key"
    app.config.update(
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR=os.path.join(base_dir, "main", "flask_session"),
        SESSION_PERMANENT=False,
    )
    Session(app)

    # UserStoreスタブを設定
    stub_store = _StubUserStore()
    # デフォルトのadminユーザーを登録
    stub_store.create_user("admin@localhost", "DEVDEVDEVDEVDEVDEV", ["dev", "admin"])
    app.config["USER_STORE"] = stub_store
    app.config["TOTP_ISSUER"] = f"{os.environ.get('TOTP_ISSUER', 'BenchKit')}-Local"

    received_dir = os.path.join(base_dir, "main", "received")
    received_padata_dir = os.path.join(base_dir, "main", "received_padata")
    received_estimation_inputs_dir = os.path.join(base_dir, "main", "received_estimation_inputs")
    estimated_dir = os.path.join(base_dir, "main", "estimated_results")
    os.makedirs(received_dir, exist_ok=True)
    os.makedirs(received_padata_dir, exist_ok=True)
    os.makedirs(received_estimation_inputs_dir, exist_ok=True)
    os.makedirs(estimated_dir, exist_ok=True)

    app.config["RECEIVED_DIR"] = received_dir
    app.config["RECEIVED_PADATA_DIR"] = received_padata_dir
    app.config["RECEIVED_ESTIMATION_INPUTS_DIR"] = received_estimation_inputs_dir
    app.config["ESTIMATED_DIR"] = estimated_dir

    # results_loaderはcurrent_app.configから取得するため、モジュール変数の書き換え不要

    register_home_routes(app)

    # ルートを登録
    from routes.results import results_bp
    app.register_blueprint(results_bp, url_prefix="/results")

    from routes.estimated import estimated_bp
    app.register_blueprint(estimated_bp, url_prefix="/estimated")

    from routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    from routes.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.route("/systemlist")
    def systemlist():
        systems_info = get_all_systems_info()
        return render_template("systemlist.html", systems_info=systems_info)

    return app


def generate_sample_data(received_dir):
    """テスト用のサンプルJSONデータを生成"""
    samples = []

    now = datetime.now()

    # 1. OSU Micro-Benchmarks (ベクトル型メトリクス) - 現在
    osu_bibw = {
        "code": "benchpark-osu-micro-benchmarks",
        "system": "RC_GH200",
        "Exp": "osu_bibw",
        "FOM": 25089.47,
        "FOM_version": "osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2",
        "FOM_unit": "MB/s",
        "cpu_name": "-", "gpu_name": "-",
        "node_count": 1, "cpus_per_node": 2,
        "gpus_per_node": 0, "cpu_cores": 0, "uname": "-",
        "description": None, "confidential": None,
        "metrics": {
            "scalar": {"FOM": 25089.47},
            "vector": {
                "x_axis": {"name": "message_size", "unit": "bytes"},
                "table": {
                    "columns": ["message_size", "Bandwidth", "P50 Tail Bandwidth", "P90 Tail Bandwidth", "P99 Tail Bandwidth"],
                    "rows": [
                        [1, 6.47, 6.54, 6.89, 6.92],
                        [2, 12.64, 12.68, 13.42, 13.82],
                        [4, 25.77, 26.67, 27.63, 27.73],
                        [8, 51.18, 51.20, 54.70, 55.36],
                        [16, 102.24, 102.56, 107.74, 110.15],
                        [32, 201.54, 200.00, 215.13, 221.07],
                        [64, 387.03, 387.88, 414.91, 425.96],
                        [128, 774.60, 779.30, 829.82, 844.88],
                        [256, 1505.88, 1519.76, 1601.22, 1620.48],
                        [512, 2876.32, 2901.44, 3050.88, 3100.16],
                        [1024, 5200.00, 5250.00, 5500.00, 5600.00],
                        [4096, 12500.00, 12600.00, 13000.00, 13200.00],
                        [65536, 22000.00, 22100.00, 22500.00, 22800.00],
                        [1048576, 24800.00, 24900.00, 25000.00, 25050.00],
                        [4194304, 25089.47, 25100.00, 25150.00, 25200.00],
                    ]
                }
            }
        },
        "build": {
            "tool": "spack",
            "spack": {
                "spack_version": "0.22.0",
                "spec": "osu-micro-benchmarks %gcc@11.5.0",
                "compiler": {"name": "gcc", "version": "11.5.0"},
                "mpi": {"name": "openmpi", "version": "4.1.7"},
                "packages": [
                    {"name": "gcc", "version": "11.5.0"},
                    {"name": "openmpi", "version": "4.1.7"}
                ]
            }
        }
    }
    samples.append(("osu_bibw", osu_bibw, now))

    # 2. OSU Micro-Benchmarks (ベクトル型) - 7日前（リグレッション比較用）
    osu_bibw_old = {
        "code": "benchpark-osu-micro-benchmarks",
        "system": "RC_GH200",
        "Exp": "osu_bibw",
        "FOM": 24500.00,
        "FOM_version": "osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2",
        "FOM_unit": "MB/s",
        "cpu_name": "-", "gpu_name": "-",
        "node_count": 1, "cpus_per_node": 2,
        "gpus_per_node": 0, "cpu_cores": 0, "uname": "-",
        "description": None, "confidential": None,
        "metrics": {
            "scalar": {"FOM": 24500.00},
            "vector": {
                "x_axis": {"name": "message_size", "unit": "bytes"},
                "table": {
                    "columns": ["message_size", "Bandwidth", "P50 Tail Bandwidth", "P90 Tail Bandwidth", "P99 Tail Bandwidth"],
                    "rows": [
                        [1, 6.20, 6.30, 6.60, 6.65],
                        [2, 12.10, 12.20, 12.90, 13.30],
                        [4, 24.80, 25.60, 26.50, 26.60],
                        [8, 49.50, 49.60, 52.80, 53.40],
                        [16, 98.50, 99.00, 103.80, 106.10],
                        [32, 194.20, 193.00, 207.30, 213.00],
                        [64, 373.00, 374.00, 399.80, 410.50],
                        [128, 746.00, 751.00, 799.50, 814.00],
                        [256, 1450.00, 1464.00, 1543.00, 1562.00],
                        [512, 2770.00, 2795.00, 2940.00, 2988.00],
                        [1024, 5010.00, 5060.00, 5300.00, 5400.00],
                        [4096, 12050.00, 12150.00, 12530.00, 12720.00],
                        [65536, 21200.00, 21300.00, 21700.00, 22000.00],
                        [1048576, 24100.00, 24200.00, 24300.00, 24350.00],
                        [4194304, 24500.00, 24600.00, 24650.00, 24700.00],
                    ]
                }
            }
        },
        "build": {
            "tool": "spack",
            "spack": {
                "spack_version": "0.22.0",
                "spec": "osu-micro-benchmarks %gcc@11.5.0",
                "compiler": {"name": "gcc", "version": "11.5.0"},
                "mpi": {"name": "openmpi", "version": "4.1.7"},
                "packages": [
                    {"name": "gcc", "version": "11.5.0"},
                    {"name": "openmpi", "version": "4.1.7"}
                ]
            }
        }
    }
    samples.append(("osu_bibw_old", osu_bibw_old, now - timedelta(days=7)))

    # 3. OSU Micro-Benchmarks (ベクトル型) - 14日前（リグレッション比較用）
    osu_bibw_older = {
        "code": "benchpark-osu-micro-benchmarks",
        "system": "RC_GH200",
        "Exp": "osu_bibw",
        "FOM": 23800.00,
        "FOM_version": "osu-micro-benchmarks.osu_bibw.osu-micro-benchmarks_osu_bibw_test_mpi_2",
        "FOM_unit": "MB/s",
        "cpu_name": "-", "gpu_name": "-",
        "node_count": 1, "cpus_per_node": 2,
        "gpus_per_node": 0, "cpu_cores": 0, "uname": "-",
        "description": None, "confidential": None,
        "metrics": {
            "scalar": {"FOM": 23800.00},
            "vector": {
                "x_axis": {"name": "message_size", "unit": "bytes"},
                "table": {
                    "columns": ["message_size", "Bandwidth", "P50 Tail Bandwidth", "P90 Tail Bandwidth", "P99 Tail Bandwidth"],
                    "rows": [
                        [1, 5.90, 6.00, 6.30, 6.35],
                        [2, 11.50, 11.60, 12.30, 12.70],
                        [4, 23.50, 24.30, 25.20, 25.30],
                        [8, 47.00, 47.10, 50.20, 50.80],
                        [16, 93.50, 94.00, 98.60, 100.80],
                        [32, 184.50, 183.50, 197.00, 202.50],
                        [64, 354.50, 355.50, 380.20, 390.50],
                        [128, 709.00, 714.00, 760.50, 774.50],
                        [256, 1380.00, 1393.00, 1468.00, 1486.00],
                        [512, 2635.00, 2660.00, 2798.00, 2843.00],
                        [1024, 4770.00, 4820.00, 5050.00, 5150.00],
                        [4096, 11470.00, 11570.00, 11930.00, 12110.00],
                        [65536, 20200.00, 20300.00, 20680.00, 20960.00],
                        [1048576, 23200.00, 23300.00, 23400.00, 23450.00],
                        [4194304, 23800.00, 23900.00, 23950.00, 24000.00],
                    ]
                }
            }
        },
        "build": {
            "tool": "spack",
            "spack": {
                "spack_version": "0.22.0",
                "spec": "osu-micro-benchmarks %gcc@11.5.0",
                "compiler": {"name": "gcc", "version": "11.5.0"},
                "mpi": {"name": "openmpi", "version": "4.1.7"},
                "packages": [
                    {"name": "gcc", "version": "11.5.0"},
                    {"name": "openmpi", "version": "4.1.7"}
                ]
            }
        }
    }
    samples.append(("osu_bibw_older", osu_bibw_older, now - timedelta(days=14)))

    # 4. OSU Latency (ベクトル型)
    osu_latency = {
        "code": "benchpark-osu-micro-benchmarks",
        "system": "RC_GH200",
        "Exp": "osu_latency",
        "FOM": 1.50,
        "FOM_version": "osu-micro-benchmarks.osu_latency.osu-micro-benchmarks_osu_latency_test_mpi_2",
        "FOM_unit": "us",
        "cpu_name": "-", "gpu_name": "-",
        "node_count": 1, "cpus_per_node": 2,
        "gpus_per_node": 0, "cpu_cores": 0, "uname": "-",
        "description": None, "confidential": None,
        "metrics": {
            "scalar": {"FOM": 1.50},
            "vector": {
                "x_axis": {"name": "message_size", "unit": "bytes"},
                "table": {
                    "columns": ["message_size", "Latency", "P50 Tail Latency", "P90 Tail Latency", "P99 Tail Latency"],
                    "rows": [
                        [1, 1.50, 1.49, 1.52, 1.68],
                        [2, 1.51, 1.50, 1.53, 1.70],
                        [4, 1.52, 1.51, 1.55, 1.72],
                        [8, 1.53, 1.52, 1.56, 1.73],
                        [16, 1.55, 1.54, 1.58, 1.75],
                        [32, 1.58, 1.57, 1.62, 1.80],
                        [64, 1.65, 1.64, 1.70, 1.88],
                        [128, 1.80, 1.79, 1.85, 2.05],
                        [256, 2.10, 2.09, 2.18, 2.40],
                        [512, 2.65, 2.64, 2.75, 3.00],
                        [1024, 3.50, 3.48, 3.65, 4.00],
                        [4096, 5.80, 5.78, 6.10, 6.50],
                        [65536, 25.00, 24.90, 26.00, 28.00],
                        [1048576, 180.00, 179.00, 185.00, 195.00],
                        [4194304, 700.00, 698.00, 720.00, 750.00],
                    ]
                }
            }
        },
        "build": {
            "tool": "spack",
            "spack": {
                "spack_version": "0.22.0",
                "spec": "osu-micro-benchmarks %gcc@11.5.0",
                "compiler": {"name": "gcc", "version": "11.5.0"},
                "mpi": {"name": "openmpi", "version": "4.1.7"},
                "packages": [
                    {"name": "gcc", "version": "11.5.0"},
                    {"name": "openmpi", "version": "4.1.7"}
                ]
            }
        }
    }
    samples.append(("osu_latency", osu_latency, now))

    # 5. gpcnet (スカラー型メトリクス)
    gpcnet_72 = {
        "code": "benchpark-gpcnet",
        "system": "RC_GH200",
        "Exp": "network_test",
        "FOM": 1.1,
        "FOM_version": "gpcnet.network_test.gpcnet_network_test_test_mpi_72",
        "FOM_unit": "MiB/sec",
        "cpu_name": "-", "gpu_name": "-",
        "node_count": 1, "cpus_per_node": 72,
        "gpus_per_node": 0, "cpu_cores": 0, "uname": "-",
        "description": None, "confidential": None,
        "metrics": {
            "scalar": {
                "FOM": 1.1,
                "Avg RR Two-sided Lat": 1.1,
                "Avg RR Get Lat": 2.1,
                "Avg Multiple Allreduce": 2.2
            }
        }
    }
    samples.append(("gpcnet_72", gpcnet_72, now))

    # 6. 既存BenchKit形式（スカラーのみ）
    benchkit_sample = {
        "code": "scale-letkf",
        "system": "Fugaku",
        "Exp": "default",
        "FOM": 123.45,
        "FOM_version": "v1.0",
        "cpu_name": "A64FX",
        "gpu_name": "-",
        "node_count": 16,
        "cpus_per_node": 48,
        "gpus_per_node": 0,
        "cpu_cores": 48,
        "uname": "Linux",
        "description": None,
        "confidential": None
    }
    samples.append(("scale_letkf", benchkit_sample, now))

    # ファイルを生成
    for name, data, timestamp in samples:
        ts = timestamp.strftime("%Y%m%d_%H%M%S")
        uid = str(uuid.uuid4())
        filename = f"result_{ts}_{uid}.json"
        filepath = os.path.join(received_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"  Generated: {filename} ({name})")


def main():
    parser = argparse.ArgumentParser(description="BenchKit Result Server - Dev Mode")
    parser.add_argument("--port", type=int, default=8800, help="Port number (default: 8800)")
    parser.add_argument("--generate-sample", action="store_true", help="Generate sample data")
    args = parser.parse_args()

    # 開発用ベースディレクトリ
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.join(script_dir, "_dev_data")

    # 環境設定
    setup_dev_environment(base_dir)

    # カレントディレクトリをresult_serverに設定
    os.chdir(script_dir)

    # サンプルデータ生成
    received_dir = os.path.join(base_dir, "main", "received")
    if args.generate_sample or not os.listdir(received_dir):
        print("Generating sample data...")
        generate_sample_data(received_dir)

    print(f"\nStarting dev server on http://localhost:{args.port}")
    print(f"  Results: http://localhost:{args.port}/results")
    print(f"  Systems: http://localhost:{args.port}/systemlist")
    print(f"  Data dir: {base_dir}")
    print()

    # Flaskアプリを直接作成して起動
    app = create_dev_app(base_dir)
    app.run(host="127.0.0.1", port=args.port, debug=True)


if __name__ == "__main__":
    main()
