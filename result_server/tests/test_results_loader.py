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
from utils.results_loader import load_single_result, load_multiple_results, load_results_table, get_filter_options


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
            ("Branch/Hash", "source_hash"),
            ("Exp", "exp"),
            ("FOM", "fom"),
            ("FOM version", "fom_version"),
            ("SYSTEM", "system"),
            ("Nodes", "nodes"),
            ("Proc/node", "numproc_node"),
            ("Thread/proc", "nthreads"),
            ("JSON", "json_link"),
            ("PA Data", "data_link"),
            ("Mode", "execution_mode"),
            ("Trigger", "ci_trigger"),
            ("Pipeline", "pipeline_id"),
        ]
        assert columns == expected_columns

    def test_existing_row_fields_preserved(self, flask_app, tmp_dir):
        """既存のrowフィールドが保持されている"""
        uid = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_120000_{uid}.json", {
            "code": "mycode", "system": "mysys", "Exp": "myexp",
            "FOM": 99.9, "FOM_version": "v1", "node_count": 4,
            "numproc_node": "48", "nthreads": "12",
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
        assert row["numproc_node"] == "48"
        assert row["nthreads"] == "12"


# ============================================================
# Pipeline Timing フィールドのテスト
# ============================================================

class TestPipelineTimingFields:
    def test_row_with_pipeline_timing_fields(self, flask_app, tmp_dir):
        """pipeline_timing, execution_mode, ci_trigger を含むJSONから正しく行データが構築される"""
        uid = str(uuid.uuid4())
        filename = f"result_20250301_100000_{uid}.json"
        data = {
            "code": "qws", "system": "Fugaku", "Exp": "test", "FOM": 42.0,
            "pipeline_timing": {
                "build_time": 120,
                "queue_time": 45,
                "run_time": 300,
            },
            "execution_mode": "cross",
            "ci_trigger": "schedule",
            "build_job": "qws_Fugaku_build",
            "run_job": "qws_Fugaku_N1_P4_T12_run",
            "pipeline_id": 17026,
        }
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, columns, _ = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        row = rows[0]
        assert row["build_time"] == "120"
        assert row["queue_time"] == "45"
        assert row["run_time"] == "300"
        assert row["execution_mode"] == "cross"
        assert row["ci_trigger"] == "schedule"
        assert row["build_job"] == "qws_Fugaku_build"
        assert row["run_job"] == "qws_Fugaku_N1_P4_T12_run"
        assert row["pipeline_id"] == "17026"

    def test_row_without_pipeline_timing_fields(self, flask_app, tmp_dir):
        """新フィールドなしの既存JSONでもエラーなく行データが構築され、フォールバック値が返る"""
        uid = str(uuid.uuid4())
        filename = f"result_20250301_100000_{uid}.json"
        data = {"code": "qws", "system": "Fugaku", "Exp": "test", "FOM": 42.0}
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, columns, _ = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        row = rows[0]
        assert row["build_time"] == "-"
        assert row["queue_time"] == "-"
        assert row["run_time"] == "-"
        assert row["execution_mode"] == "-"
        assert row["ci_trigger"] == "-"
        assert row["build_job"] == "-"
        assert row["run_job"] == "-"
        assert row["pipeline_id"] == "-"

    def test_row_with_partial_pipeline_timing(self, flask_app, tmp_dir):
        """pipeline_timingの一部フィールドが欠損している場合のフォールバック"""
        uid = str(uuid.uuid4())
        filename = f"result_20250301_100000_{uid}.json"
        data = {
            "code": "qws", "system": "Fugaku", "FOM": 1.0,
            "pipeline_timing": {"build_time": 60},
        }
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, _, _ = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        row = rows[0]
        assert row["build_time"] == "60"
        assert row["queue_time"] == "-"
        assert row["run_time"] == "-"

    def test_row_with_invalid_pipeline_timing_type(self, flask_app, tmp_dir):
        """pipeline_timingが不正な型（文字列等）の場合はフォールバック"""
        uid = str(uuid.uuid4())
        filename = f"result_20250301_100000_{uid}.json"
        data = {
            "code": "qws", "system": "Fugaku", "FOM": 1.0,
            "pipeline_timing": "invalid",
        }
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, _, _ = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        row = rows[0]
        assert row["build_time"] == "-"
        assert row["queue_time"] == "-"
        assert row["run_time"] == "-"


# ============================================================
# カスケードフィルタのテスト
# ============================================================

class TestCascadeFilter:
    def test_filter_code_filters_exps(self, tmp_dir):
        """filter_code指定時にそのCodeのExpのみ返される"""
        uid1 = str(uuid.uuid4())
        uid2 = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_000000_{uid1}.json",
                     {"code": "qws", "system": "Fugaku", "Exp": "CASE0"})
        _write_json(tmp_dir, f"result_20250101_000001_{uid2}.json",
                     {"code": "genesis", "system": "Fugaku", "Exp": "CASE1"})

        opts = get_filter_options(tmp_dir, filter_code="qws")
        assert "CASE0" in opts["exps"]
        assert "CASE1" not in opts["exps"]

    def test_filter_code_none_returns_all_exps(self, tmp_dir):
        """filter_code=Noneの場合は全Expが返される"""
        uid1 = str(uuid.uuid4())
        uid2 = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_000000_{uid1}.json",
                     {"code": "qws", "system": "Fugaku", "Exp": "CASE0"})
        _write_json(tmp_dir, f"result_20250101_000001_{uid2}.json",
                     {"code": "genesis", "system": "Fugaku", "Exp": "CASE1"})

        opts = get_filter_options(tmp_dir, filter_code=None)
        assert "CASE0" in opts["exps"]
        assert "CASE1" in opts["exps"]

    def test_filter_code_nonexistent_returns_empty_exps(self, tmp_dir):
        """存在しないCodeを指定した場合はExpsが空"""
        uid1 = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_000000_{uid1}.json",
                     {"code": "qws", "system": "Fugaku", "Exp": "CASE0"})

        opts = get_filter_options(tmp_dir, filter_code="nonexistent")
        assert opts["exps"] == []
        # codes and systems should still be populated
        assert "qws" in opts["codes"]
        assert "Fugaku" in opts["systems"]
