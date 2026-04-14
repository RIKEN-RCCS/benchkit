"""Tests for result loading, filtering, and summary behavior."""

import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import install_portal_test_stubs

install_portal_test_stubs()

from flask import Flask
from utils.result_records import load_result_json, load_result_json_batch, summarize_result_quality
from utils.results_loader import load_results_table, get_filter_options


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for result JSON fixtures."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def flask_app(tmp_dir):
    """Create a Flask app so tests can resolve URLs and blueprint routes."""
    app = Flask(__name__)

    app.config["RECEIVED_DIR"] = tmp_dir
    app.config["ESTIMATED_DIR"] = tmp_dir

    from routes.results import results_bp
    app.register_blueprint(results_bp, url_prefix="/results")

    yield app


def _write_json(directory, filename, data):
    """Write a JSON fixture file and return its path."""
    filepath = os.path.join(directory, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return filepath



# ============================================================
# load_result_json behavior

class TestLoadSingleResult:
    def test_load_existing_file(self, tmp_dir):
        """Test case."""
        data = {"code": "test-app", "system": "TestSys", "FOM": 42.0}
        _write_json(tmp_dir, "result.json", data)

        result = load_result_json("result.json", tmp_dir)
        assert result is not None
        assert result["code"] == "test-app"
        assert result["system"] == "TestSys"
        assert result["FOM"] == 42.0

    def test_load_nonexistent_file(self, tmp_dir):
        """Test case."""
        result = load_result_json("nonexistent.json", tmp_dir)
        assert result is None

    def test_load_invalid_json(self, tmp_dir):
        """Test case."""
        filepath = os.path.join(tmp_dir, "bad.json")
        with open(filepath, "w") as f:
            f.write("not valid json {{{")

        result = load_result_json("bad.json", tmp_dir)
        assert result is None

    def test_preserves_all_meta_fields(self, tmp_dir):
        """Test case."""
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

        result = load_result_json("meta.json", tmp_dir)
        assert result is not None
        for key in ["code", "system", "Exp", "FOM", "FOM_unit", "node_count", "cpus_per_node"]:
            assert key in result
            assert result[key] == data[key]

    def test_preserves_metrics_vector(self, tmp_dir):
        """Test case."""
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

        result = load_result_json("vector.json", tmp_dir)
        assert result is not None
        assert "metrics" in result
        assert "vector" in result["metrics"]
        assert result["metrics"]["vector"]["x_axis"]["name"] == "message_size"


# ============================================================
# load_result_json_batch behavior

class TestLoadMultipleResults:
    def test_sorts_by_timestamp_ascending(self, tmp_dir):
        """Test case."""
        _write_json(tmp_dir, "result_20250115_120000_aaa.json", {"code": "c"})
        _write_json(tmp_dir, "result_20250101_080000_bbb.json", {"code": "a"})
        _write_json(tmp_dir, "result_20250110_100000_ccc.json", {"code": "b"})

        filenames = [
            "result_20250115_120000_aaa.json",
            "result_20250101_080000_bbb.json",
            "result_20250110_100000_ccc.json",
        ]
        results = load_result_json_batch(filenames, tmp_dir)

        assert len(results) == 3
        assert results[0]["timestamp"] == "2025-01-01 08:00:00"
        assert results[1]["timestamp"] == "2025-01-10 10:00:00"
        assert results[2]["timestamp"] == "2025-01-15 12:00:00"

    def test_extracts_timestamp_from_filename(self, tmp_dir):
        """Test case."""
        uid = str(uuid.uuid4())
        filename = f"result_20250601_143022_{uid}.json"
        _write_json(tmp_dir, filename, {"code": "test"})

        results = load_result_json_batch([filename], tmp_dir)
        assert len(results) == 1
        assert results[0]["timestamp"] == "2025-06-01 14:30:22"
        assert results[0]["filename"] == filename

    def test_skips_nonexistent_files(self, tmp_dir):
        """Test case."""
        _write_json(tmp_dir, "result_20250101_000000_x.json", {"code": "ok"})

        results = load_result_json_batch(
            ["result_20250101_000000_x.json", "nonexistent.json"],
            directory=tmp_dir,
        )
        assert len(results) == 1

    def test_return_format(self, tmp_dir):
        """Test case."""
        _write_json(tmp_dir, "result_20250101_000000_x.json", {"code": "test", "FOM": 1.0})

        results = load_result_json_batch(["result_20250101_000000_x.json"], tmp_dir)
        assert len(results) == 1
        r = results[0]
        assert "filename" in r
        assert "timestamp" in r
        assert "data" in r
        assert isinstance(r["data"], dict)
        assert r["data"]["code"] == "test"

    def test_unknown_timestamp_for_no_pattern(self, tmp_dir):
        """Test case."""
        _write_json(tmp_dir, "some_result.json", {"code": "test"})

        results = load_result_json_batch(["some_result.json"], tmp_dir)
        assert len(results) == 1
        assert results[0]["timestamp"] == "Unknown"

    def test_empty_filenames(self, tmp_dir):
        """Test case."""
        results = load_result_json_batch([], tmp_dir)
        assert results == []


# ============================================================
# load_results_table behavior

class TestLoadResultsTableExtension:
    def test_has_vector_true_when_metrics_vector_exists(self, flask_app, tmp_dir):
        """Test case."""
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
        """Test case."""
        uid = str(uuid.uuid4())
        filename = f"result_20250101_000000_{uid}.json"
        data = {"code": "test", "system": "sys", "Exp": "exp", "FOM": 1.0}
        _write_json(tmp_dir, filename, data)

        with flask_app.test_request_context():
            rows, columns, pagination_info = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        assert rows[0]["has_vector"] is False
        assert rows[0]["detail_link"] == f"/results/detail/{filename}"
        assert rows[0]["filename"] == filename

    def test_has_vector_false_when_only_scalar(self, flask_app, tmp_dir):
        """Test case."""
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
        assert rows[0]["detail_link"] == f"/results/detail/{filename}"

    def test_existing_columns_unchanged(self, flask_app, tmp_dir):
        """Test case."""
        uid = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_000000_{uid}.json",
                     {"code": "t", "system": "s"})

        with flask_app.test_request_context():
            rows, columns, pagination_info = load_results_table(tmp_dir, public_only=True)

        expected_columns = [
            {"label": "Timestamp", "key": "timestamp", "tooltip": "Date and time when benchmark execution completed and results were automatically submitted to server", "tooltip_class": "tooltip-left"},
            {"label": "CODE", "key": "code"},
            {"label": "Branch/Hash", "key": "source_hash", "tooltip": "Source code branch name and short commit hash (git) or short md5sum (file archive)"},
            {"label": "Exp", "key": "exp", "tooltip": "Experimental conditions (filtered by CODE)"},
            {"label": "FOM", "key": "fom", "tooltip": "Figure of Merit - Benchmark performance metric value, typically elapsed time in seconds for main section"},
            {"label": "FOM version", "key": "fom_version", "tooltip": "Version identifier for the FOM measurement section - helps identify which code region was measured when users modify the timing boundaries"},
            {"label": "SYSTEM", "key": "system", "tooltip": "Computing system name"},
            {"label": "Nodes", "key": "nodes"},
            {"label": "P/N", "key": "numproc_node", "tooltip": "Number of processes per node"},
            {"label": "T/P", "key": "nthreads", "tooltip": "Number of threads per process"},
            {"label": "Profiler / PA", "key": "profile_summary", "tooltip": "Profiler tool, level, report summary, and PA data download access"},
            {"label": "JSON", "key": "json_link", "tooltip": "Detailed benchmark results in JSON format", "tooltip_class": "tooltip-right"},
            {"label": "CI", "key": "ci_summary", "tooltip": "CI trigger source and pipeline ID"},
        ]
        assert columns == expected_columns

    def test_existing_row_fields_preserved(self, flask_app, tmp_dir):
        """Test case."""
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
        assert row["profile_summary"] == "-"

    def test_profile_summary_is_built_from_profile_data(self, flask_app, tmp_dir):
        uid = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_120000_{uid}.json", {
            "code": "qws",
            "system": "Fugaku",
            "Exp": "CASE0",
            "FOM": 1.0,
            "profile_data": {
                "tool": "fapp",
                "level": "detailed",
                "report_format": "both",
                "run_count": 17,
                "events": [f"pa{i}" for i in range(1, 18)],
                "report_kinds": ["summary_text", "cpu_pa_csv"],
            },
        })

        with flask_app.test_request_context():
            rows, _, _ = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        row = rows[0]
        assert row["profile_summary"] == "fapp / detailed"
        assert row["profile_summary_meta"]["headline"] == "fapp / detailed"
        assert row["profile_summary_meta"]["subline"] == "both, 17 runs"
        assert row["profile_summary_meta"]["events"][0] == "pa1"
        assert "cpu_pa_csv" in row["profile_summary_meta"]["report_kinds"]


class TestSummarizeResultQuality:
    def test_basic_quality_without_breakdown(self):
        quality = summarize_result_quality({
            "code": "test",
            "system": "sys",
            "FOM": 1.0,
        })

        assert quality["level"] == "basic"
        assert "fom_breakdown is missing" in quality["warnings"]

    def test_ready_quality_with_breakdown_and_packages(self):
        quality = summarize_result_quality({
            "code": "test",
            "system": "sys",
            "FOM": 1.0,
            "fom_breakdown": {
                "sections": [
                    {"name": "solver", "time": 1.0, "estimation_package": "identity"},
                ],
                "overlaps": [],
            },
        })

        assert quality["level"] == "ready"
        assert quality["stats"]["section_package_count"] == 1

    def test_rich_quality_with_source_and_artifacts(self):
        quality = summarize_result_quality({
            "code": "test",
            "system": "sys",
            "FOM": 1.0,
            "source_info": {
                "source_type": "git",
                "repo_url": "https://example.invalid/repo.git",
                "branch": "main",
                "commit_hash": "0123456789abcdef0123456789abcdef01234567",
            },
            "fom_breakdown": {
                "sections": [
                    {
                        "name": "solver",
                        "time": 1.0,
                        "estimation_package": "identity",
                        "artifacts": [{"type": "file_reference", "path": "results/x"}],
                    },
                ],
                "overlaps": [],
            },
        })

        assert quality["level"] == "rich"
        assert quality["stats"]["artifact_count"] == 1


# ============================================================
# Pipeline timing extraction

class TestPipelineTimingFields:
    def test_row_with_pipeline_timing_fields(self, flask_app, tmp_dir):
        """Test case."""
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
        """Test case."""
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
        """Test case."""
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
        """Test case."""
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
# Section

class TestCascadeFilter:
    def test_filter_code_filters_exps(self, tmp_dir):
        """Test case."""
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
        """Test case."""
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
        """Test case."""
        uid1 = str(uuid.uuid4())
        _write_json(tmp_dir, f"result_20250101_000000_{uid1}.json",
                     {"code": "qws", "system": "Fugaku", "Exp": "CASE0"})

        opts = get_filter_options(tmp_dir, filter_code="nonexistent")
        assert opts["exps"] == []
        # codes and systems should still be populated
        assert "qws" in opts["codes"]
        assert "Fugaku" in opts["systems"]


class TestPadataLinkResolution:
    def test_data_link_uses_server_uuid_when_filename_has_no_uuid(self, flask_app, tmp_dir):
        uid = str(uuid.uuid4())
        filename = "result0.json"
        tgz_name = f"padata_20250101_120000_{uid}.tgz"
        _write_json(tmp_dir, filename, {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 1.0,
            "_server_uuid": uid,
        })
        open(os.path.join(tmp_dir, tgz_name), "wb").close()

        with flask_app.test_request_context():
            rows, _, _ = load_results_table(tmp_dir, public_only=True)

        assert len(rows) == 1
        assert rows[0]["data_link"] == f"/results/{tgz_name}"

    def test_data_link_uses_separate_padata_directory(self, flask_app, tmp_dir):
        uid = str(uuid.uuid4())
        filename = f"result_20250101_120000_{uid}.json"
        padata_dir = os.path.join(tmp_dir, "received_padata")
        os.makedirs(padata_dir, exist_ok=True)
        tgz_name = f"padata_20250101_120000_{uid}.tgz"

        _write_json(tmp_dir, filename, {
            "code": "qws",
            "system": "Fugaku",
            "FOM": 1.0,
        })
        open(os.path.join(padata_dir, tgz_name), "wb").close()

        with flask_app.test_request_context():
            rows, _, _ = load_results_table(tmp_dir, public_only=True, padata_directory=padata_dir)

        assert len(rows) == 1
        assert rows[0]["data_link"] == f"/results/{tgz_name}"
