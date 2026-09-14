import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.measurement_artifacts import (
    PUBLIC_PADATA_FILENAME_RE,
    is_measurement_artifact_filename,
    measurement_artifact_basename_from_path,
    normalize_measurement_artifact_basename,
    profile_archive_filename_candidates,
    stored_measurement_artifact_filename,
    stored_measurement_artifact_filename_from_path,
)


UUID = "12345678-1234-1234-1234-123456789abc"
TIMESTAMP = "20250101_120000"


def test_normalizes_safe_results_artifact_paths():
    assert normalize_measurement_artifact_basename("results/qws_timing_CASE0.json") == (
        "qws_timing_CASE0.json"
    )
    assert normalize_measurement_artifact_basename("results/padata_pairlist.tgz") == (
        "padata_pairlist.tgz"
    )
    assert normalize_measurement_artifact_basename("") is None
    assert normalize_measurement_artifact_basename(None) is None


@pytest.mark.parametrize(
    "artifact_path",
    [
        "../qws_timing.json",
        "results/../qws_timing.json",
        "/tmp/qws_timing.json",
        "results/bad name.json",
        "artifacts/qws_timing.json",
        "results/qws_timing.txt",
    ],
)
def test_rejects_unsafe_or_unsupported_artifact_paths(artifact_path):
    with pytest.raises(ValueError):
        normalize_measurement_artifact_basename(artifact_path)
    assert measurement_artifact_basename_from_path(artifact_path) == ""


def test_builds_canonical_stored_names_for_legacy_profiles_and_timing_json():
    assert stored_measurement_artifact_filename(TIMESTAMP, UUID, None) == (
        f"padata_{TIMESTAMP}_{UUID}.tgz"
    )
    assert stored_measurement_artifact_filename_from_path(
        TIMESTAMP,
        UUID,
        "results/padata_pairlist.tgz",
    ) == f"padata_{TIMESTAMP}_{UUID}_padata_pairlist.tgz"
    assert stored_measurement_artifact_filename_from_path(
        TIMESTAMP,
        UUID,
        "results/qws_timing_CASE0.json",
    ) == f"measurement_artifact_{TIMESTAMP}_{UUID}_qws_timing_CASE0.json"
    assert stored_measurement_artifact_filename_from_path(
        TIMESTAMP,
        UUID,
        "results/node_status_snapshot_run.json",
    ) == f"measurement_artifact_{TIMESTAMP}_{UUID}_node_status_snapshot_run.json"


def test_profile_archive_candidates_keep_legacy_and_generic_names():
    assert profile_archive_filename_candidates(
        TIMESTAMP,
        UUID,
        "results/padata_pairlist.tar.gz",
    ) == [
        f"padata_{TIMESTAMP}_{UUID}_padata_pairlist.tgz",
        f"measurement_artifact_{TIMESTAMP}_{UUID}_padata_pairlist.tar.gz",
    ]


@pytest.mark.parametrize(
    "filename",
    [
        f"padata_{TIMESTAMP}_{UUID}.tgz",
        f"padata_{TIMESTAMP}_{UUID}_padata_pairlist.tgz",
        f"measurement_artifact_{TIMESTAMP}_{UUID}_qws_timing_CASE0.json",
        f"measurement_artifact_{TIMESTAMP}_{UUID}_node_status_snapshot_run.json",
    ],
)
def test_recognizes_served_measurement_artifact_filenames(filename):
    assert is_measurement_artifact_filename(filename)


def test_public_padata_filename_pattern_matches_full_uuid():
    assert PUBLIC_PADATA_FILENAME_RE.fullmatch(f"padata_{TIMESTAMP}_{UUID}.tgz")
    assert PUBLIC_PADATA_FILENAME_RE.fullmatch(
        f"padata_{TIMESTAMP}_{UUID}_padata_pairlist.tgz"
    )


@pytest.mark.parametrize(
    "filename",
    [
        "measurement_artifact_20250101_120000_qws_timing_CASE0.json",
        f"measurement_artifact_{TIMESTAMP}_{UUID}_bad name.json",
        "nested/debug_bundle.tgz",
        "debug_bundle.json",
    ],
)
def test_rejects_unserved_measurement_artifact_filenames(filename):
    assert not is_measurement_artifact_filename(filename)
