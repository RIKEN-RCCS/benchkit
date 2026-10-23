"""Prepare local or stored inputs for both initial estimation and re-estimation.

Runs on the estimation runner, never on the benchmark compute node. Measurement
archives stay opaque except explicitly declared observation bundles. Scientific
applicability and preprocessing belong to the selected estimation package.
"""

import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlencode
from uuid import UUID


API_HELPER = Path(__file__).resolve().parents[1] / "result_server" / "api.sh"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4096


def download(endpoint, destination):
    completed = subprocess.run([
        "bash", "-c",
        'source "$1"; bk_result_server_download_optional_to_file "$2" "$3"',
        "artifact-query", str(API_HELPER), endpoint, str(destination),
    ], check=False)
    if completed.returncode == 3:
        return False
    if completed.returncode:
        raise RuntimeError("Stored estimation input query failed")
    return True


def safe_destination(path):
    parts = path.split("/")
    if (not path.startswith("results/") or "\\" in path
            or any(part in ("", ".", "..") for part in parts)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(tgz|tar\.gz|json)", parts[-1])):
        raise ValueError("Invalid measurement artifact reference")
    if len(parts) == 2 and (
        re.fullmatch(r"result\d+\.json", parts[-1])
        or parts[-1].startswith("estimate")
        or parts[-1] in ("source_estimate.json", "reestimation_context.json", "server_result_meta.json")
    ):
        raise ValueError("Measurement reference targets estimation control data")
    destination = Path(path)
    reject_symlinks(destination)
    return destination


def reject_symlinks(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Estimation input path contains a symlink")


def measurement_paths(result):
    references = []
    breakdown = result.get("fom_breakdown") or {}
    for group in ("sections", "overlaps"):
        for section in breakdown.get(group) or []:
            references.extend(section.get("artifacts") or [])
    for observation in (result.get("timing_observations") or {}).get("observations") or []:
        references.append(observation.get("artifact"))
        if observation.get("format") == "benchkit-observation-bundle/v1":
            references.append((observation.get("summary") or {}).get("bundle"))
    references.append((result.get("node_status_snapshot") or {}).get("artifact"))
    return sorted({
        ref["path"] for ref in references
        if isinstance(ref, dict) and ref.get("type") == "file_reference"
        and isinstance(ref.get("path"), str)
        and ref["path"].endswith((".tgz", ".tar.gz", ".json"))
    })


def source_uuid(result, result_file):
    value = result.get("_server_uuid") or (result.get("_meta") or {}).get("uuid")
    if not value:
        manifest = Path("results/server_result_meta.json")
        if manifest.is_file():
            value = json.loads(manifest.read_text()).get(result_file.name, {}).get("uuid")
    if value:
        return str(UUID(value))
    return None


def restore_bundle(archive, destination, owners=None, uuid=None, manifest=None):
    reject_symlinks(destination)
    # Validate and stage the whole bundle before making any restored file visible.
    with tempfile.TemporaryDirectory(prefix="estimation-bundle-") as staging:
        with tarfile.open(archive, "r:gz") as bundle:
            total = 0
            seen = set()
            for count, member in enumerate(bundle, start=1):
                path = PurePosixPath(member.name)
                if (count > MAX_ARCHIVE_MEMBERS or path.is_absolute()
                        or ".." in path.parts or "\\" in member.name
                        or not (member.isfile() or member.isdir())
                        or str(path) in seen):
                    raise ValueError("Unsafe estimation artifact bundle")
                seen.add(str(path))
                total += member.size
                if total > MAX_ARCHIVE_BYTES or member.size < 0:
                    raise ValueError("Estimation artifact bundle exceeds extraction limit")
                target = Path(staging) / path
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        if manifest is not None:
            if not isinstance(manifest, dict) or not manifest:
                raise ValueError('Invalid observation bundle manifest')
            files = {str(p.relative_to(staging)): p for p in Path(staging).rglob('*') if p.is_file()}
            if set(files) != set(manifest) or any(
                not re.fullmatch(r'profile_[A-Za-z0-9]+/(?:davidson-plan\.json|discovery\.sqlite|profile\.tgz|profile\.metadata\.json)', name)
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or hashlib.sha256(files[name].read_bytes()).hexdigest() != digest
                for name, digest in manifest.items()
            ):
                raise ValueError('Observation bundle files or hashes do not match')
            if any(p.is_dir() and not any(name.startswith(str(p.relative_to(staging)) + '/') for name in files)
                   for p in Path(staging).rglob('*')):
                raise ValueError('Unexpected observation bundle directory')
            # Check all conflicts before publishing any member; never overwrite.
            for name, source in files.items():
                target = destination / name
                reject_symlinks(target)
                if target.exists() and (not target.is_file() or target.read_bytes() != source.read_bytes()):
                    raise ValueError('Conflicting restored observation input')
        for source in Path(staging).rglob("*"):
            target = destination / source.relative_to(staging)
            reject_symlinks(target)
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copyfile(source, target)
                    if owners is not None:
                        owners[target] = uuid
                elif owners is not None and target in owners and owners[target] != uuid:
                    raise ValueError("Different Results share a restored estimation artifact path")


def prepare_inputs(result_files):
    inputs = []
    owners = {}
    for result_file in result_files:
        result = json.loads(result_file.read_text())
        uuid = source_uuid(result, result_file)
        destinations = [(path, safe_destination(path)) for path in measurement_paths(result)]
        for path, destination in destinations:
            if not destination.is_file() and path in owners and owners[path] != uuid:
                raise ValueError("Different Results reference the same missing artifact path")
            owners[path] = uuid
        inputs.append((uuid, destinations))

    observation_bundles = []
    for result_file in result_files:
        result = json.loads(result_file.read_text())
        for observation in (result.get('timing_observations') or {}).get('observations') or []:
            if observation.get('format') == 'benchkit-observation-bundle/v1':
                observation_bundles.append(observation)

    bundle_destination = Path("results/estimation_artifacts")
    reject_symlinks(bundle_destination)
    local_bundle = bundle_destination.is_dir() and any(bundle_destination.iterdir())
    bundle_owners = {}
    for uuid, destinations in inputs:
        if not uuid or not os.environ.get("RESULT_SERVER"):
            if any(not destination.is_file() for _, destination in destinations):
                print("WARNING: Missing measurement inputs cannot be queried without a Result UUID and RESULT_SERVER", file=sys.stderr)
            continue
        with tempfile.TemporaryDirectory(prefix="estimation-inputs-") as staging:
            for path, destination in destinations:
                if destination.is_file():
                    continue
                temporary = Path(staging) / "measurement"
                query = urlencode({"uuid": uuid, "artifact_path": path})
                if download("/api/query/measurement-artifact?" + query, temporary):
                    reject_symlinks(destination)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(temporary, destination)
                    print("Restored measurement artifact:", path)
                else:
                    print("WARNING: Referenced measurement artifact is not stored:", path, file=sys.stderr)

            if local_bundle:
                continue
            temporary = Path(staging) / "estimation.tgz"
            query = urlencode({"uuid": uuid})
            found = download("/api/query/estimation-artifacts?" + query, temporary)
            if not found:
                found = download("/api/query/estimation-inputs?" + query, temporary)
            if found:
                restore_bundle(temporary, bundle_destination, bundle_owners, uuid)
                print("Restored estimation artifacts")

    for observation in observation_bundles:
        manifest_path = safe_destination(observation['artifact']['path'])
        reference = observation['summary']['bundle']
        archive = safe_destination(reference['path'])
        if (not manifest_path.is_file() or not archive.is_file()
                or hashlib.sha256(archive.read_bytes()).hexdigest() != reference.get('sha256')):
            raise ValueError('Observation bundle missing or hash mismatch')
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('format') != 'benchkit-observation-bundle/v1' or manifest.get('summary', {}).get('bundle') != reference:
            raise ValueError('Invalid observation bundle manifest')
        if not isinstance(manifest.get('files'), dict) or not manifest['files']:
            raise ValueError('Invalid observation bundle manifest')
        restore_bundle(archive, Path('results'), manifest=manifest['files'])


if __name__ == "__main__":
    try:
        prepare_inputs([Path(arg) for arg in sys.argv[1:]])
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        print("ERROR: Estimation input preparation failed:", error, file=sys.stderr)
        sys.exit(1)
