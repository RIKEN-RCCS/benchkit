"""CI evidence records must be complete and exclude deployment information."""

import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "report_sqlcipher_runtime", Path(__file__).with_name("report_sqlcipher_runtime.py"))
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


@pytest.fixture
def install_report(monkeypatch):
    monkeypatch.setattr(reporter.importlib.metadata, "version", lambda name: "1.2.3")
    monkeypatch.setattr(reporter, "runtime_versions", lambda: {"cipher_version": "4.example"})
    return {"environment": {"private": "excluded"}, "install": [{
        "metadata": {"name": "sqlcipher3-binary", "version": "1.2.3", "extra": "excluded"},
        "download_info": {
            "url": "https://user:credential@example.invalid/private/sqlcipher3_binary-1.2.3-cp312-cp312-linux_x86_64.whl?secret=excluded",
            "archive_info": {"hashes": {"sha256": "a" * 64}},
        },
    }]}


def test_record_contains_only_selected_evidence(install_report):
    record = reporter.build_record(install_report)
    assert record["wheel"]["sha256"] == "a" * 64
    assert record["distribution"]["version"] == "1.2.3"
    assert record["runtime"]["cipher_version"] == "4.example"
    assert record["python_version"]
    encoded = json.dumps(record)
    for value in ("credential", "excluded", "example.invalid", "private", "secret"):
        assert value not in encoded


@pytest.mark.parametrize("change", ["missing", "duplicate", "version", "digest", "source"])
def test_incomplete_or_mismatched_evidence_is_rejected(install_report, change):
    entry = install_report["install"][0]
    if change == "missing":
        install_report["install"] = []
    elif change == "duplicate":
        install_report["install"].append(entry)
    elif change == "version":
        entry["metadata"]["version"] = "9.9.9"
    elif change == "digest":
        entry["download_info"]["archive_info"]["hashes"]["sha256"] = "truncated"
    else:
        entry["download_info"]["url"] = "https://example.invalid/source.tar.gz"
    with pytest.raises(ValueError):
        reporter.build_record(install_report)


def test_failure_does_not_print_report_path_or_content(tmp_path, capsys):
    path = tmp_path / "private-report.json"
    path.write_text("private invalid report", encoding="utf-8")
    assert reporter.main(["report", str(path)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "SQLCipher runtime record failed\n"


def test_real_memory_database_reports_all_components():
    pytest.importorskip("sqlcipher3.dbapi2")
    record = reporter.runtime_versions()
    assert set(record) == {"cipher_version", "sqlite_version", "cipher_provider", "cipher_provider_version"}
    assert all(isinstance(value, str) and value.strip() for value in record.values())
