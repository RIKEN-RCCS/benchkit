"""
results_loader.py のユニットテスト

load_single_result, load_multiple_results, load_results_table の
新規追加・拡張機能をテストする。
"""

import os
import sys
import json
import types
import tempfile
import shutil
import uuid
from datetime import datetime, timedelta

import pytest

# --- テスト用スタブモジュールの設定 ---
# otp_manager / otp_redis_manager はSMTP/Redis依存があるため、
# テスト用のスタブに差し替える

def _setup_stubs():
    """テスト用のスタブモジュールをsys.modulesに登録"""
    # redis スタブ
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.ModuleType("redis")

    # otp_manager スタブ
    otp_mod = types.ModuleType("utils.otp_manager")
    otp_mod.get_affiliations = lambda email: ["dev"]
    otp_mod.is_allowed = lambda email: True
    sys.modules["utils.otp_manager"] = otp_mod

    # otp_redis_manager スタブ
    otp_redis_mod = types.ModuleType("utils.otp_redis_manager")
    otp_redis_mod.get_affiliations = lambda email: ["dev"]
    otp_redis_mod.is_allowed = lambda email: True
    otp_redis_mod.send_otp = lambda email: (True, "stub")
    otp_redis_mod.verify_otp = lambda email, code: True
    otp_redis_mod.invalidate_otp = lambda email: None
    sys.modules["utils.otp_redis_manager"] = otp_redis_mod

_setup_stubs()

# result_server ディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask
from utils.results_loader import load_single_result, load_multiple_results, load_results_table


# --- フィクスチャ ---

@pytest.fixture
def tmp_dir():
    """テスト用の一時ディレクトリを作成・削除"""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def flask_app(tmp_dir):
    """テスト用のFlaskアプリケーション（url_for用）"""
    app = Flask(__name__)

    app.config["RECEIVED_DIR"] = tmp_dir
    app.config["ESTIMATED_DIR"] = tmp_dir

    from routes.results import results_bp
    app.register_blueprint(results_bp, url_prefix="/results")

    yield app


def _write_json(directory, filename, data):
    """テスト用JSONファイルを書き込む"""
    filepath = os.path.join(directory, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return filepath


# ============================================================
# load_single_result のテスト
# ============================================================

class TestLoadSingleResult:
    def test_load_existing_file(self, tmp_dir):
        """存在するJSONファイルを正しく読み込める"""
        data = {"code": "test-app", "system": "TestSys", "FOM": 42.0}
        _write_json(tmp_dir, "result.json", data)

        result = load_single_result("result.json", save_dir=tmp_dir)
        assert result is not None
        assert result["code"] == "test-app"
        assert result["system"] == "TestSys"
        assert result["FOM"] == 42.0

    def test_load_nonexistent_file(self, tmp_dir):
        """存在しないファイルの場合 None を返す"""
        result = load_single_result("nonexistent.json", save_dir=tmp_dir)
        assert result is None

    def test_load_invalid_json(self, tmp_dir):
        """不正なJSONファイルの場合 None を返す"""
        filepath = os.path.join(tmp_dir, "bad.json")
        with open(filepath, "w") as f:
            f.write("not valid json {{{")

        result = load_single_result("bad.json", save_dir=tmp_dir)
        assert result is None

    def test_preserves_all_meta_fields(self, tmp_dir):
        """メタ情報フィールドが全て保持される"""
        data = {
            "code": "benchpark-osu",
            "system": "RC_GH200",
            "Exp": "osu_bibw",
            "FOM": 25089.47,
            "FOM_unit": "MB/s",
            "node_count": 1,
            "cpus_per_node": 2,
        }
        _write_json(tmp_dir, "meta.json", data)

        result = load_single_result("meta.json", save_dir=tmp_dir)
        assert result is not None
        for key in ["code", "system", "Exp", "FOM", "FOM_unit", "node_count", "cpus_per_node"]:
            assert key in result
            assert result[key] == data[key]

    def test_preserves_metrics_vector(self, tmp_dir):
        """metrics.vector フィールドが保持される"""
        data = {
            "code": "test",
            "metrics": {
                "vector": {
                    "x_axis": {"name": "message_size", "unit": "bytes"},
                    "table": {"columns": ["message_size", "BW"], "rows": [[1, 6.47]]}
                }
            }
        }
        _write_json(tmp_dir, "vector.json", data)

        result = load_single_result("vector.json", save_dir=tmp_dir)
        assert result is not None
        assert "metrics" in result
        assert "vector" in result["metrics"]
        assert result["metrics"]["vector"]["x_axis"]["name"] == "message_size"


# ============================================================
# load_multiple_results のテスト
# ============================================================

class TestLoadMultipleResults:
    def test_sorts_by_timestamp_ascending(self, tmp_dir):
        """タイムスタンプ昇順でソートされる"""
        _write_json(tmp_dir, "result_20250115_120000_aaa.json", {"code": "c"})
        _write_json(tmp_dir, "result_20250101_080000_bbb.json", {"code": "a"})
        _write_json(tmp_dir, "result_20250110_100000_ccc.json", {"code": "b"})

        filenames = [
            "result_20250115_120000_aaa.json",
            "result_20250101_080000_bbb.json",
            "result_20250110_100000_ccc.json",
        ]
        results = load_multiple_results(filenames, save_dir=tmp_dir)

        assert len(results) == 3
        assert results[0]["timestamp"] == "2025-01-01 08:00:00"
        assert results[1]["timestamp"] == "2025-01-10 10:00:00"
        assert results[2]["timestamp"] == "2025-01-15 12:00:00"

    def test_extracts_timestamp_from_filename(self, tmp_dir):
        """ファイル名からタイムスタンプを正しく抽出する"""
        uid = str(uuid.uuid4())
        filename = f"result_20250601_143022_{uid}.json"
        _write_json(tmp_dir, filename, {"code": "test"})

        results = load_multiple_results([filename], save_dir=tmp_dir)
        assert len(results) == 1
        assert results[0]["timestamp"] == "2025-06-01 14:30:22"
        assert results[0]["filename"] == filename

    def test_skips_nonexistent_files(self, tmp_dir):
        """存在しないファイルはスキップされる"""
        _write_json(tmp_dir, "result_20250101_000000_x.json", {"code": "ok"})

        results = load_multiple_results(
            ["result_20250101_000000_x.json", "nonexistent.json"],
            save_dir=tmp_dir,
        )
        assert len(results) == 1

    def test_return_format(self, tmp_dir):
        """戻り値の形式が正しい"""
        _write_json(tmp_dir, "result_20250101_000000_x.json", {"code": "test", "FOM": 1.0})

        results = load_multiple_results(["result_20250101_000000_x.json"], save_dir=tmp_dir)
        assert len(results) == 1
        r = results[0]
        assert "filename" in r
        assert "timestamp" in r
        assert "data" in r
        assert isinstance(r["data"], dict)
        assert r["data"]["code"] == "test"

    def test_unknown_timestamp_for_no_pattern(self, tmp_dir):
        """タイムスタンプパターンがないファイル名は 'Unknown' になる"""
        _write_json(tmp_dir, "some_result.json", {"code": "test"})

        results = load_multiple_results(["some_result.json"], save_dir=tmp_dir)
        assert len(results) == 1
        assert results[0]["timestamp"] == "Unknown"

    def test_empty_filenames(self, tmp_dir):
        """空のファイル名リストは空リストを返す"""
        results = load_multiple_results([], save_dir=tmp_dir)
        assert results == []


# ============================================================
# load_results_table 拡張のテスト
# ============================================================

class TestLoadResultsTableExtension:
    def test_has_vector_true_when_metrics_vector_exists(self, flask_app, tmp_dir):
        """metrics.vector がある場合 has_vector=True"""
        uid = str(uuid.uuid4())
        filename = f"result_20250101_000000_{uid}.json"
        data = {
            "code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0,
            "metrics": {
                "vector": {
                    "x_axis": {"name": "msg_size", "unit": "bytes"},
                    "table": {"columns": ["msg_size", "BW"], "rows": [[1, 2.0]]}
                }
            }
        }
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, columns, pagination_info = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        assert rows[0]["has_vector"] is True
        assert rows[0]["detail_link"] == f"/results/detail/{filename}"
        assert rows[0]["filename"] == filename

    def test_has_vector_false_when_no_metrics(self, flask_app, tmp_dir):
        """metrics フィールドがない場合 has_vector=False"""
        uid = str(uuid.uuid4())
        filename = f"result_20250101_000000_{uid}.json"
        data = {"code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0}
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, columns, pagination_info = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        assert rows[0]["has_vector"] is False
        assert rows[0]["detail_link"] is None
        assert rows[0]["filename"] == filename

    def test_has_vector_false_when_only_scalar(self, flask_app, tmp_dir):
        """metrics.scalar のみの場合 has_vector=False"""
        uid = str(uuid.uuid4())
        filename = f"result_20250101_000000_{uid}.json"
        data = {
            "code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0,
            "metrics": {"scalar": {"FOM": 1.0, "metric_a": 2.0}}
        }
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, columns, pagination_info = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        assert rows[0]["has_vector"] is False
        assert rows[0]["detail_link"] is None

    def test_existing_columns_unchanged(self, flask_app, tmp_dir):
        """既存のカラムリストが変更されていない"""
        uid = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_000000_{uid}.json",
                     {"code": "t", "system": "s"})

        with flask_app.test_request_context():
            rows, columns, pagination_info = load_results_table(tmp_dir, public_only=True)

        expected_columns = [
            ("Timestamp", "timestamp"),
            ("CODE", "code"),
            ("Exp", "exp"),
            ("FOM", "fom"),
            ("FOM version", "fom_version"),
            ("SYSTEM", "system"),
            ("CPU Name", "cpu"),
            ("GPU Name", "gpu"),
            ("Nodes", "nodes"),
            ("CPU/node", "cpus"),
            ("GPU/node", "gpus"),
            ("CPU Core Count", "cpu_cores"),
            ("JSON", "json_link"),
            ("PA Data", "data_link"),
        ]
        assert columns == expected_columns

    def test_existing_row_fields_preserved(self, flask_app, tmp_dir):
        """既存のrowフィールドが保持されている"""
        uid = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_120000_{uid}.json", {
            "code": "mycode", "system": "mysys", "Exp": "myexp",
            "FOM": 99.9, "FOM_version": "v1", "cpu_name": "ARM",
            "gpu_name": "H100", "node_count": 4, "cpus_per_node": 48,
            "gpus_per_node": 8, "cpu_cores": 48,
        })

        with flask_app.test_request_context():
            rows, _, pagination_info = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        row = rows[0]
        assert row["code"] == "mycode"
        assert row["system"] == "mysys"
        assert row["exp"] == "myexp"
        assert row["fom"] == 99.9
        assert row["timestamp"] == "2025-01-01 12:00:00"
