"""Read estimation declarations from an existing local Git object database."""

import json
import os
import re
import subprocess


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_REF = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|refs/[A-Za-z0-9_./-]+)\Z")
_MAX_DOCUMENT_BYTES = 128 * 1024
_MAX_PACKAGES = 64


def read_estimation_version_snapshot(repository, ref, code, *, packages=(), section_packages=()):
    """Read explicitly requested declarations at one resolved commit, without fetch.

    The caller supplies a trusted local repository and full ref or commit SHA.
    No shell/package code is executed and no worktree, ref or remote is changed.
    Undeclared versions stay unknown; model versions are not inferred from a
    package version or from the name of its implementation file.
    """
    if not isinstance(code, str) or not _NAME.fullmatch(code):
        raise ValueError("invalid app name")
    if not isinstance(ref, str) or not _REF.fullmatch(ref) or ".." in ref:
        raise ValueError("a full ref or commit SHA is required")
    if isinstance(packages, (str, bytes)) or isinstance(section_packages, (str, bytes)):
        raise ValueError("package names must be collections")
    packages, section_packages = tuple(packages), tuple(section_packages)
    if len(packages) + len(section_packages) > _MAX_PACKAGES:
        raise ValueError("too many package declarations")
    if any(not isinstance(name, str) or not _NAME.fullmatch(name)
           for name in packages + section_packages):
        raise ValueError("invalid package name")

    snapshot = {"ref": ref, "commit": None, "code": code, "app": None,
                "packages": {}, "section_packages": {}, "unknowns": []}
    try:
        try:
            partial_clone = _git(repository, "config", "--local", "--get-regexp",
                                 r"^(extensions\.partialclone|remote\..*\.promisor)$")
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 1:
                raise
            partial_clone = b""
        if partial_clone:
            snapshot["unknowns"].append({"reason": "partial_clone_not_supported"})
            return snapshot
        commit = _git(repository, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise ValueError("invalid commit response")
    except (OSError, subprocess.SubprocessError, ValueError):
        snapshot["unknowns"].append({"reason": "unavailable_ref"})
        return snapshot
    snapshot["commit"] = commit

    def read(path, name):
        try:
            tree = _git(repository, "ls-tree", "-z", commit, "--", path)
            if not tree:
                raise _Unknown("missing_declaration")
            # A symlink also has a blob object, so check the tree mode first.
            mode, kind, rest = tree.split(b" ", 2)
            oid, stored_path = rest.split(b"\t", 1)
            if (mode not in (b"100644", b"100755") or kind != b"blob"
                    or stored_path != path.encode() + b"\0"):
                raise _Unknown("unsupported_declaration_type")
            size = int(_git(repository, "cat-file", "-s", oid.decode()))
            if size > _MAX_DOCUMENT_BYTES:
                raise _Unknown("oversized_declaration")
            data = json.loads(_git(repository, "cat-file", "blob", oid.decode()),
                              object_pairs_hook=_unique_object)
            if not isinstance(data, dict):
                raise _Unknown("invalid_declaration")
            version = data.get("version")
            if not isinstance(version, str) or not version.strip():
                raise _Unknown("missing_version")
            if name is not None and data.get("name") != name:
                raise _Unknown("declaration_name_mismatch")
            return data
        except _Unknown as exc:
            reason = str(exc)
        except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
            reason = "unreadable_declaration"
        snapshot["unknowns"].append({"path": path, "reason": reason})
        return None

    snapshot["app"] = read(f"programs/{code}/estimate.metadata.json", None)
    for group, names in (("packages", packages), ("section_packages", section_packages)):
        for name in sorted(set(names)):
            snapshot[group][name] = read(f"scripts/estimation/{group}/{name}.metadata.json", name)
    return snapshot


class _Unknown(ValueError):
    pass


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _Unknown("duplicate_key")
        value[key] = item
    return value


def _git(repository, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")
    return subprocess.run(
        ["git", "--no-pager", "--no-replace-objects", "--literal-pathspecs",
         "-C", os.fspath(repository), *args],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=10, env=env,
    ).stdout
