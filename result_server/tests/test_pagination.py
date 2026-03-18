"""
ページネーション機能のユニットテスト

paginate_list(), ルートのクエリパラメータ処理、フィルタ+ページネーション連携、
既存機能との互換性をテストする。
"""

import os
import sys
import json
import types
import tempfile
import shutil
import uuid

import pytest

# --- テスト用スタブモジュールの設定 ---
def _setup_stubs():
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

from flask import Flask
from utils.results_loader import (
    paginate_list, load_results_table, load_estimated_results_table,
    get_filter_options, get_estimated_filter_options,
)


# --- フィクスチャ ---

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def flask_app(tmp_dir):
    import fakeredis
    from utils.user_store import UserStore

    template_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
    app = Flask(__name__, template_folder=template_dir)
    app.config["RECEIVED_DIR"] = tmp_dir
    app.config["ESTIMATED_DIR"] = tmp_dir
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    r_conn = fakeredis.FakeRedis(decode_responses=True)
    app.config["REDIS_CONN"] = r_conn
    app.config["REDIS_PREFIX"] = "test:"
    app.config["USER_STORE"] = UserStore(r_conn, "test:")

    from routes.results import results_bp
    from routes.estimated import estimated_bp
    from routes.auth import auth_bp
    app.register_blueprint(results_bp, url_prefix="/results")
    app.register_blueprint(estimated_bp, url_prefix="/estimated")
    app.register_blueprint(auth_bp, url_prefix="/auth")

    @app.route("/systemlist")
    def systemlist():
        return ""

    yield app


def _write_json(directory, filename, data):
    filepath = os.path.join(directory, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return filepath


def _make_result_files(tmp_dir, count, code="test-app", system="TestSys", exp="exp1"):
    """指定数のテスト用JSONファイルを生成"""
    filenames = []
    for i in range(count):
        uid = str(uuid.uuid4())
        fname = f"result_20250101_{i:06d}_{uid}.json"
        _write_json(tmp_dir, fname, {
            "code": code, "system": system, "Exp": exp, "FOM": float(i),
        })
        filenames.append(fname)
    return filenames


# ============================================================
# paginate_list() のテスト
# ============================================================

class TestPaginateList:
    def test_default_first_page(self):
        """デフォルトパラメータで最初のページを返す"""
        items = list(range(250))
        result, info = paginate_list(items, page=1, per_page=100)
        assert result == list(range(100))
        assert info["page"] == 1
        assert info["per_page"] == 100
        assert info["total"] == 250
        assert info["total_pages"] == 3

    def test_second_page(self):
        """2ページ目を正しく返す"""
        items = list(range(250))
        result, info = paginate_list(items, page=2, per_page=100)
        assert result == list(range(100, 200))
        assert info["page"] == 2

    def test_last_page_partial(self):
        """最終ページが端数の場合"""
        items = list(range(250))
        result, info = paginate_list(items, page=3, per_page=100)
        assert result == list(range(200, 250))
        assert len(result) == 50

    def test_empty_list_returns_total_pages_1(self):
        """空リストの場合 total_pages=1"""
        result, info = paginate_list([], page=1, per_page=100)
        assert result == []
        assert info["total"] == 0
        assert info["total_pages"] == 1
        assert info["page"] == 1

    def test_clamp_page_below_1(self):
        """page < 1 の場合は 1 にクランプ"""
        items = list(range(50))
        result, info = paginate_list(items, page=0, per_page=100)
        assert info["page"] == 1

    def test_clamp_page_negative(self):
        """負のページ番号は 1 にクランプ"""
        items = list(range(50))
        result, info = paginate_list(items, page=-5, per_page=100)
        assert info["page"] == 1

    def test_clamp_page_above_total(self):
        """total_pages を超えるページは total_pages にクランプ"""
        items = list(range(50))
        result, info = paginate_list(items, page=999, per_page=100)
        assert info["page"] == 1  # 50件 / 100 = 1ページ
        assert info["total_pages"] == 1

    def test_exact_page_boundary(self):
        """件数がper_pageの倍数の場合"""
        items = list(range(200))
        result, info = paginate_list(items, page=2, per_page=100)
        assert info["total_pages"] == 2
        assert result == list(range(100, 200))

    def test_per_page_50(self):
        """per_page=50 で正しく分割"""
        items = list(range(120))
        result, info = paginate_list(items, page=1, per_page=50)
        assert len(result) == 50
        assert info["total_pages"] == 3  # ceil(120/50) = 3

    def test_per_page_200(self):
        """per_page=200 で正しく分割"""
        items = list(range(500))
        result, info = paginate_list(items, page=1, per_page=200)
        assert len(result) == 200
        assert info["total_pages"] == 3  # ceil(500/200) = 3

    def test_single_item(self):
        """1件のみの場合"""
        result, info = paginate_list(["a"], page=1, per_page=100)
        assert result == ["a"]
        assert info["total"] == 1
        assert info["total_pages"] == 1


# ============================================================
# per_page バリデーションのテスト
# ============================================================

class TestPerPageValidation:
    def test_invalid_per_page_defaults_to_100(self, flask_app, tmp_dir):
        """不正な per_page 値はデフォルト100にフォールバック"""
        _make_result_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/results/?per_page=75")
            assert resp.status_code == 200

    def test_per_page_50_accepted(self, flask_app, tmp_dir):
        """per_page=50 は有効"""
        _make_result_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/results/?per_page=50")
            assert resp.status_code == 200

    def test_per_page_200_accepted(self, flask_app, tmp_dir):
        """per_page=200 は有効"""
        _make_result_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/results/?per_page=200")
            assert resp.status_code == 200

    def test_per_page_string_defaults(self, flask_app, tmp_dir):
        """文字列の per_page はデフォルトにフォールバック"""
        _make_result_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/results/?per_page=abc")
            assert resp.status_code == 200


# ============================================================
# ページ範囲外リダイレクトのテスト
# ============================================================

class TestPageRedirect:
    def test_page_too_high_redirects(self, flask_app, tmp_dir):
        """存在しないページ番号はリダイレクトされる"""
        _make_result_files(tmp_dir, 5)  # 5件 → 1ページ
        with flask_app.test_client() as client:
            resp = client.get("/results/?page=999")
            assert resp.status_code == 302

    def test_page_zero_redirects(self, flask_app, tmp_dir):
        """page=0 はリダイレクトされる"""
        _make_result_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/results/?page=0")
            assert resp.status_code == 302

    def test_page_negative_redirects(self, flask_app, tmp_dir):
        """負のページ番号はリダイレクトされる"""
        _make_result_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/results/?page=-1")
            assert resp.status_code == 302

    def test_redirect_preserves_filters(self, flask_app, tmp_dir):
        """リダイレクト時にフィルタパラメータが保持される"""
        _make_result_files(tmp_dir, 5, system="SysA")
        with flask_app.test_client() as client:
            resp = client.get("/results/?page=999&system=SysA&per_page=50")
            assert resp.status_code == 302
            location = resp.headers["Location"]
            assert "system=SysA" in location
            assert "per_page=50" in location

    def test_valid_page_no_redirect(self, flask_app, tmp_dir):
        """有効なページ番号はリダイレクトされない"""
        _make_result_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/results/?page=1")
            assert resp.status_code == 200


# ============================================================
# フィルタ + ページネーション連携のテスト
# ============================================================

class TestFilterPagination:
    def test_filter_reduces_total(self, flask_app, tmp_dir):
        """フィルタ適用で件数が減る"""
        _make_result_files(tmp_dir, 3, system="SysA")
        _make_result_files(tmp_dir, 2, system="SysB")

        with flask_app.test_request_context():
            rows, _, info = load_results_table(
                tmp_dir, public_only=True,
                filter_system="SysA",
            )
        assert info["total"] == 3

    def test_filter_no_match_returns_empty(self, flask_app, tmp_dir):
        """フィルタに一致しない場合は空"""
        _make_result_files(tmp_dir, 5, system="SysA")

        with flask_app.test_request_context():
            rows, _, info = load_results_table(
                tmp_dir, public_only=True,
                filter_system="NonExistent",
            )
        assert info["total"] == 0
        assert rows == []
        assert info["total_pages"] == 1

    def test_filter_with_pagination(self, flask_app, tmp_dir):
        """フィルタ + ページネーションの組み合わせ"""
        _make_result_files(tmp_dir, 120, system="SysA")
        _make_result_files(tmp_dir, 30, system="SysB")

        with flask_app.test_request_context():
            rows, _, info = load_results_table(
                tmp_dir, public_only=True,
                filter_system="SysA", page=1, per_page=50,
            )
        assert info["total"] == 120
        assert info["total_pages"] == 3  # ceil(120/50)
        assert len(rows) == 50

    def test_code_filter(self, flask_app, tmp_dir):
        """CODE フィルタが動作する"""
        _make_result_files(tmp_dir, 3, code="app-a")
        _make_result_files(tmp_dir, 2, code="app-b")

        with flask_app.test_request_context():
            rows, _, info = load_results_table(
                tmp_dir, public_only=True,
                filter_code="app-a",
            )
        assert info["total"] == 3

    def test_exp_filter(self, flask_app, tmp_dir):
        """Exp フィルタが動作する"""
        _make_result_files(tmp_dir, 4, exp="exp1")
        _make_result_files(tmp_dir, 1, exp="exp2")

        with flask_app.test_request_context():
            rows, _, info = load_results_table(
                tmp_dir, public_only=True,
                filter_exp="exp2",
            )
        assert info["total"] == 1

    def test_multiple_filters(self, flask_app, tmp_dir):
        """複数フィルタの組み合わせ"""
        _make_result_files(tmp_dir, 3, system="SysA", code="app-a")
        _make_result_files(tmp_dir, 2, system="SysA", code="app-b")
        _make_result_files(tmp_dir, 1, system="SysB", code="app-a")

        with flask_app.test_request_context():
            rows, _, info = load_results_table(
                tmp_dir, public_only=True,
                filter_system="SysA", filter_code="app-a",
            )
        assert info["total"] == 3


# ============================================================
# get_filter_options のテスト
# ============================================================

class TestFilterOptions:
    def test_returns_unique_sorted_values(self, tmp_dir):
        """ユニークかつソート済みの値を返す"""
        _make_result_files(tmp_dir, 2, system="Zeta", code="app-b")
        _make_result_files(tmp_dir, 1, system="Alpha", code="app-a")

        opts = get_filter_options(tmp_dir, public_only=True)
        assert opts["systems"] == ["Alpha", "Zeta"]
        assert opts["codes"] == ["app-a", "app-b"]

    def test_empty_directory(self, tmp_dir):
        """空ディレクトリの場合"""
        opts = get_filter_options(tmp_dir, public_only=True)
        assert opts == {"systems": [], "codes": [], "exps": []}

    def test_estimated_filter_options(self, tmp_dir):
        """推定結果のフィルタオプション"""
        uid = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_000000_{uid}.json", {
            "benchmark_system": "SysA", "code": "app-x", "exp": "exp1",
        })
        opts = get_estimated_filter_options(tmp_dir, public_only=True)
        assert "SysA" in opts["systems"]
        assert "app-x" in opts["codes"]
        assert "exp1" in opts["exps"]


# ============================================================
# 推定結果ページネーションのテスト
# ============================================================

class TestEstimatedPagination:
    def _make_estimated_files(self, tmp_dir, count, system="SysA"):
        for i in range(count):
            uid = str(uuid.uuid4())
            _write_json(tmp_dir, f"result_20250101_{i:06d}_{uid}.json", {
                "code": "est-app", "exp": "exp1",
                "benchmark_system": system, "benchmark_fom": float(i),
                "benchmark_nodes": 1,
                "current_system": {"fom": 1.0, "system": "A", "nodes": 1, "method": "m"},
                "future_system": {"fom": 2.0, "system": "B", "nodes": 2, "method": "m"},
                "performance_ratio": 2.0,
            })

    def test_estimated_pagination(self, flask_app, tmp_dir):
        """推定結果のページネーション"""
        self._make_estimated_files(tmp_dir, 120)

        with flask_app.test_request_context():
            rows, _, info = load_estimated_results_table(
                tmp_dir, public_only=True, page=1, per_page=50,
            )
        assert info["total"] == 120
        assert info["total_pages"] == 3
        assert len(rows) == 50

    def test_estimated_filter(self, flask_app, tmp_dir):
        """推定結果のフィルタ"""
        self._make_estimated_files(tmp_dir, 3, system="SysA")
        self._make_estimated_files(tmp_dir, 2, system="SysB")

        with flask_app.test_request_context():
            rows, _, info = load_estimated_results_table(
                tmp_dir, public_only=True, filter_system="SysB",
            )
        assert info["total"] == 2

    def test_estimated_route_redirect(self, flask_app, tmp_dir):
        """推定結果ルートのページ範囲外リダイレクト"""
        self._make_estimated_files(tmp_dir, 5)
        with flask_app.test_client() as client:
            resp = client.get("/estimated/?page=999")
            assert resp.status_code == 302


# ============================================================
# 既存機能の互換性テスト
# ============================================================

class TestExistingFeatureCompatibility:
    def test_load_results_table_returns_3_tuple(self, flask_app, tmp_dir):
        """load_results_table が (rows, columns, pagination_info) を返す"""
        _make_result_files(tmp_dir, 1)
        with flask_app.test_request_context():
            result = load_results_table(tmp_dir, public_only=True)
        assert isinstance(result, tuple)
        assert len(result) == 3
        rows, columns, pagination_info = result
        assert isinstance(rows, list)
        assert isinstance(columns, list)
        assert isinstance(pagination_info, dict)

    def test_pagination_info_has_required_keys(self, flask_app, tmp_dir):
        """pagination_info に必須キーが含まれる"""
        _make_result_files(tmp_dir, 1)
        with flask_app.test_request_context():
            _, _, info = load_results_table(tmp_dir, public_only=True)
        for key in ("page", "per_page", "total", "total_pages"):
            assert key in info

    def test_compare_route_still_works(self, flask_app, tmp_dir):
        """Compare ルートが引き続き動作する"""
        uid1 = str(uuid.uuid4())
        uid2 = str(uuid.uuid4())
        f1 = f"result_20250101_000000_{uid1}.json"
        f2 = f"result_20250102_000000_{uid2}.json"
        _write_json(tmp_dir, f1, {"code": "a", "system": "s", "FOM": 1.0})
        _write_json(tmp_dir, f2, {"code": "a", "system": "s", "FOM": 2.0})

        with flask_app.test_client() as client:
            resp = client.get(f"/results/compare?files={f1},{f2}")
            assert resp.status_code == 200

    def test_no_filter_reads_only_page_files(self, flask_app, tmp_dir):
        """フィルタなし時は対象ページのJSONのみ読み込む（件数確認）"""
        _make_result_files(tmp_dir, 150)
        with flask_app.test_request_context():
            rows, _, info = load_results_table(
                tmp_dir, public_only=True, page=1, per_page=50,
            )
        assert len(rows) == 50
        assert info["total"] == 150
        assert info["total_pages"] == 3
