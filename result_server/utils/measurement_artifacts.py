from __future__ import annotations

import os
import re


MEASUREMENT_ARTIFACT_BASENAME_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:tgz|tar\.gz|json)"
)
MEASUREMENT_ARTIFACT_FILENAME_RE = re.compile(
    r"^measurement_artifact_\d{8}_\d{6}_"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:tgz|tar\.gz|json)$",
    re.IGNORECASE,
)
PUBLIC_PADATA_FILENAME_RE = re.compile(
    r"^padata_\d{8}_\d{6}_"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?:_[A-Za-z0-9][A-Za-z0-9_.-]{0,127})?\.tgz$",
    re.IGNORECASE,
)


def normalize_measurement_artifact_basename(value):
    """Return the safe basename for a results/ artifact path."""
    if value is None:
        return None

    artifact_path = str(value).strip()
    if artifact_path == "":
        return None
    if (
        os.path.isabs(artifact_path)
        or "\\" in artifact_path
        or artifact_path.startswith("../")
        or "/../" in artifact_path
        or artifact_path.endswith("/..")
    ):
        raise ValueError("invalid measurement artifact path")
    if not artifact_path.startswith("results/"):
        raise ValueError("invalid measurement artifact path")

    basename = os.path.basename(artifact_path)
    if not MEASUREMENT_ARTIFACT_BASENAME_RE.fullmatch(basename):
        raise ValueError("invalid measurement artifact basename")
    return basename


def measurement_artifact_basename_from_path(artifact_path):
    try:
        return normalize_measurement_artifact_basename(artifact_path) or ""
    except ValueError:
        return ""


def is_profile_archive_basename(basename):
    return isinstance(basename, str) and (
        basename.endswith(".tgz") or basename.endswith(".tar.gz")
    )


def profile_archive_slug_from_basename(basename):
    if not is_profile_archive_basename(basename):
        return ""
    return basename[:-7] if basename.endswith(".tar.gz") else basename[:-4]


def stored_measurement_artifact_filename(timestamp, result_uuid, artifact_basename=None):
    if artifact_basename is None:
        return f"padata_{timestamp}_{result_uuid}.tgz"
    if is_profile_archive_basename(artifact_basename):
        artifact_slug = profile_archive_slug_from_basename(artifact_basename)
        return f"padata_{timestamp}_{result_uuid}_{artifact_slug}.tgz"
    return f"measurement_artifact_{timestamp}_{result_uuid}_{artifact_basename}"


def stored_measurement_artifact_filename_from_path(timestamp, result_uuid, artifact_path):
    artifact_basename = measurement_artifact_basename_from_path(artifact_path)
    if not artifact_basename:
        return ""
    return stored_measurement_artifact_filename(timestamp, result_uuid, artifact_basename)


def profile_archive_filename_candidates(timestamp, result_uuid, artifact_path):
    basename = measurement_artifact_basename_from_path(artifact_path)
    if not is_profile_archive_basename(basename):
        return []

    return [
        stored_measurement_artifact_filename(timestamp, result_uuid, basename),
        f"measurement_artifact_{timestamp}_{result_uuid}_{basename}",
    ]


def is_measurement_artifact_filename(filename):
    if not isinstance(filename, str) or os.path.basename(filename) != filename:
        return False
    if "/" in filename or "\\" in filename:
        return False
    return filename.endswith(".tgz") or bool(
        MEASUREMENT_ARTIFACT_FILENAME_RE.fullmatch(filename)
    )
