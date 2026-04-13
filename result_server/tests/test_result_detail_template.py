"""
result_detail.html テンプレートのレンダリングテスト

テンプレートが各種データ構造で正しくレンダリングされることを検証する。
"""

import os
import sys
import types

# --- テスト用スタブモジュールの設定 ---
def _setup_stubs():
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")
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

_setup_stubs()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from flask import Flask
from routes.home import register_home_routes
from routes.results import results_bp
from routes.estimated import estimated_bp
from routes.auth import auth_bp
from routes.admin import admin_bp


@pytest.fixture
def app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    )
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    register_home_routes(app)
    app.register_blueprint(results_bp, url_prefix="/")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    # ナビゲーションテンプレートが url_for('systemlist') を参照するためダミールートを登録
    @app.route("/systemlist")
    def systemlist():
        return ""

    return app


# 全フィールドを持つ完全なテストデータ
FULL_RESULT = {
    "code": "benchpark-osu-micro-benchmarks",
    "system": "RC_GH200",
    "Exp": "osu_bibw",
    "FOM": 6.47,
    "FOM_unit": "MB/s",
    "FOM_version": "osu-micro-benchmarks.osu_bibw.test_mpi_2",
    "node_count": 1,
    "cpus_per_node": 2,
    "metrics": {
        "scalar": {"FOM": 6.47, "other_metric": 1.23},
        "vector": {
            "x_axis": {"name": "message_size", "unit": "bytes"},
            "table": {
                "columns": ["message_size", "Bandwidth", "P50 Tail Bandwidth"],
                "rows": [
                    [1, 6.47, 6.54],
                    [2, 12.64, 12.68],
                    [4194304, 25089.47, 25100.12],
                ],
            },
        },
    },
    "build": {
        "tool": "spack",
        "spack": {
            "compiler": {"name": "gcc", "version": "11.5.0"},
            "mpi": {"name": "openmpi", "version": "4.1.7"},
            "packages": [
                {"name": "gcc", "version": "11.5.0"},
                {"name": "openmpi", "version": "4.1.7"},
            ],
        },
    },
    "profile_data": {
        "tool": "fapp",
        "level": "single",
        "report_format": "text",
        "run_count": 1,
        "events": ["pa1"],
        "report_kinds": ["summary_text"],
    },
}

FULL_QUALITY = {
    "level": "rich",
    "label": "Rich",
    "summary": "Breakdown, estimation bindings, source provenance, and artifacts are present.",
    "warnings": [],
    "stats": {
        "has_fom": True,
        "has_source_info": True,
        "source_info_complete": True,
        "has_breakdown": True,
        "section_count": 2,
        "overlap_count": 1,
        "section_package_count": 2,
        "overlap_package_count": 1,
        "artifact_count": 3,
    },
}


class TestResultDetailTemplate:
    """result_detail.html テンプレートのレンダリングテスト"""

    def test_meta_info_section(self, app):
        """4.1: メタ情報セクションが正しくレンダリングされる"""
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=FULL_RESULT, quality=FULL_QUALITY, filename="test.json")

        assert "benchpark-osu-micro-benchmarks" in html
        assert "RC_GH200" in html
        assert "osu_bibw" in html
        assert "6.47" in html
        assert "MB/s" in html
        assert "CPUs per Node" in html
        # 戻りリンク（url_forで生成されるため、results blueprintのルートURL）
        assert "Back to Results" in html
        # ナビゲーション
        assert "Results" in html

    def test_vector_chart_section(self, app):
        """4.2: ベクトル型メトリクスのグラフセクションが表示される"""
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=FULL_RESULT, quality=FULL_QUALITY, filename="test.json")

        assert "vectorChart" in html
        assert "cdn.jsdelivr.net/npm/chart.js" in html
        assert "logarithmic" in html
        assert "message_size" in html
        # フォールバックメッセージ
        assert "Failed to load chart library" in html

    def test_pa_data_summary_section(self, app):
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=FULL_RESULT, quality=FULL_QUALITY, filename="test.json")

        assert "PA Data Summary" in html
        assert "fapp" in html
        assert "single" in html
        assert "summary_text" in html
        assert "pa1" in html

    def test_vector_data_table(self, app):
        """4.3: ベクトル型メトリクスのデータテーブルが正しく表示される"""
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=FULL_RESULT, quality=FULL_QUALITY, filename="test.json")

        # カラムヘッダー
        assert "Bandwidth" in html
        assert "P50 Tail Bandwidth" in html
        # X軸は整数表示
        assert ">1<" in html or ">1</td>" in html
        assert ">4194304<" in html or ">4194304</td>" in html
        # メトリクス値は小数点以下2桁
        assert "6.47" in html
        assert "25089.47" in html

    def test_scalar_metrics_shown_when_multiple_keys(self, app):
        """4.4: スカラーメトリクスが2つ以上のキーで表示される"""
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=FULL_RESULT, quality=FULL_QUALITY, filename="test.json")

        assert "Scalar Metrics" in html
        assert "other_metric" in html
        assert "1.23" in html

    def test_scalar_metrics_hidden_when_fom_only(self, app):
        """4.4: スカラーメトリクスがFOMのみの場合は非表示"""
        result = {
            "code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0,
            "metrics": {"scalar": {"FOM": 1.0}},
        }
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=result, quality=FULL_QUALITY, filename="test.json")

        # h2タグ内のセクション見出しが表示されないことを確認
        assert "<h2>Scalar Metrics</h2>" not in html

    def test_build_info_section(self, app):
        """4.5: ビルド情報セクションが正しく表示される"""
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=FULL_RESULT, quality=FULL_QUALITY, filename="test.json")

        assert "Build Information" in html
        assert "spack" in html
        assert "gcc" in html
        assert "11.5.0" in html
        assert "openmpi" in html
        assert "4.1.7" in html

    def test_build_info_hidden_when_no_build(self, app):
        """4.5: buildフィールドがない場合はビルド情報非表示"""
        result = {"code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0}
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=result, quality=FULL_QUALITY, filename="test.json")

        assert "<h2>Build Information</h2>" not in html
        assert "implicit default (s)" in html

    def test_no_vector_section_when_no_metrics(self, app):
        """4.2: metricsがない場合はグラフセクション非表示"""
        result = {"code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0}
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=result, quality=FULL_QUALITY, filename="test.json")

        assert "vectorChart" not in html
        assert "cdn.jsdelivr.net/npm/chart.js" not in html

    def test_build_tool_only_no_spack(self, app):
        """4.5: build.spackがない場合はツール名のみ表示"""
        result = {
            "code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0,
            "build": {"tool": "cmake"},
        }
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=result, quality=FULL_QUALITY, filename="test.json")

        assert "Build Information" in html
        assert "cmake" in html
        assert "Compiler" not in html

    def test_quality_section(self, app):
        """Quality セクションが表示される"""
        with app.test_request_context():
            from flask import render_template
            html = render_template("result_detail.html", result=FULL_RESULT, quality=FULL_QUALITY, filename="test.json")

        assert "<h2>Quality</h2>" in html
        assert "Rich" in html
        assert "Breakdown" in html
        assert "Estimation Inputs" in html
        assert "top-level source tracked" in html
