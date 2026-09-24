#!/usr/bin/env python3
"""Validate project-bound execution routes without logging configuration values."""

import argparse
import csv
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class RouteError(ValueError):
    pass


def _object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise RouteError("duplicate JSON key")
        obj[key] = value
    return obj


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys():
        raise RouteError("missing required configuration fields")
    if value.keys() - set(required) - set(optional):
        raise RouteError("unknown configuration fields")


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise RouteError("invalid identifier in execution route")
    return value


def _server_url(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise RouteError("invalid target server URL")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise RouteError("target server must be an HTTPS URL without credentials")
    return value.rstrip("/")


def resolve_routes(config, systems, env):
    """Return one complete route per configured system, bound to this project."""
    _fields(config, ("version", "target", "routes"))
    if type(config["version"]) is not int or config["version"] != 1:
        raise RouteError("unsupported execution route version")
    target = config["target"]
    _fields(target, ("server_url", "project_path"))
    server = _server_url(target["server_url"])
    project = target["project_path"]
    if not isinstance(project, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", project):
        raise RouteError("invalid target project path")
    if server != env.get("CI_SERVER_URL", "").rstrip("/") or project != env.get("CI_PROJECT_PATH"):
        raise RouteError("execution routes do not match this GitLab server/project")
    routes = config["routes"]
    if not isinstance(routes, list) or not routes:
        raise RouteError("routes must be a nonempty list")
    resolved = {}
    seen = set()
    for route in routes:
        _fields(route, ("id", "systems", "run_tag", "allocation_project_id"),
                ("build_tag", "id_token_audience"))
        route_id = _identifier(route["id"])
        if route_id in seen:
            raise RouteError("duplicate execution route id")
        seen.add(route_id)
        names = route["systems"]
        if not isinstance(names, list) or not names:
            raise RouteError("route systems must be a nonempty list")
        run_tag = _identifier(route["run_tag"])
        allocation = _identifier(route["allocation_project_id"])
        build_tag = route.get("build_tag", "")
        if build_tag:
            _identifier(build_tag)
        elif build_tag != "":
            raise RouteError("invalid build tag")
        audience = route.get("id_token_audience", server)
        if not isinstance(audience, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}", audience):
            raise RouteError("invalid ID token audience")
        for name in names:
            _identifier(name)
            if name not in systems:
                raise RouteError("route references an unknown system")
            if name in resolved:
                raise RouteError("multiple routes configured for one system")
            if systems[name] not in ("cross", "native"):
                raise RouteError("unsupported system mode for execution route")
            if systems[name] == "cross" and not build_tag:
                raise RouteError("cross-mode execution route requires a build tag")
            resolved[name] = {
                "id": route_id, "build_tag": build_tag, "run_tag": run_tag,
                "allocation_project_id": allocation, "id_token_audience": audience,
            }
    return resolved


def load_routes(path, system_file, env):
    with open(path, encoding="utf-8") as handle:
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise RouteError("execution route configuration is too large")
    config = json.loads(raw, object_pairs_hook=_object)
    with open(system_file, newline="", encoding="utf-8") as handle:
        systems = {row["system"]: row["mode"] for row in csv.DictReader(handle)}
    return resolve_routes(config, systems, env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate without printing resolved values")
    parser.add_argument("--system-file", default="config/system.csv")
    args = parser.parse_args()
    try:
        path = os.environ.get("BK_EXECUTION_ROUTES_FILE", "")
        if not path or not Path(path).is_file():
            raise RouteError("BK_EXECUTION_ROUTES_FILE must name a readable JSON file")
        routes = load_routes(path, args.system_file, os.environ)
    except RouteError as exc:
        print("Execution route configuration: " + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        print("Execution route configuration could not be read or parsed", file=sys.stderr)
        return 1
    if args.check:
        print("Execution route configuration is valid")
    else:
        print(json.dumps(routes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
