"""Read-only GitLab runner observations, independent of execution permissions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .gitlab_pipeline import configured_gitlab_targets


RUNNER_TYPES = frozenset({"instance_type", "group_type", "project_type"})
HEARTBEATS = frozenset({"online", "offline", "stale", "never_contacted"})
MAX_BYTES = 4 * 1024 * 1024


class ObservationError(RuntimeError):
    """Only fixed, value-free error codes may leave the transport boundary."""


@dataclass(frozen=True)
class MonitorTarget:
    id: str
    server: str
    project: str
    token_file: Path = field(repr=False)
    runner_types: frozenset[str] = RUNNER_TYPES


def configured_monitor_targets(env=None):
    source = os.environ if env is None else env
    targets, errors = configured_gitlab_targets(source)
    try:
        settings = json.loads(source.get("RESULT_SERVER_RUNNER_MONITOR_TARGETS", "{}"))
        if errors or not isinstance(settings, dict) or not settings:
            raise ValueError
        available = {target.id: target for target in targets}
        result = []
        for target_id, options in settings.items():
            if target_id not in available or not isinstance(options, dict):
                raise ValueError
            if set(options) - {"token_file", "runner_types"}:
                raise ValueError
            repo = available[target_id].repo.removesuffix(".git")
            if "://" in repo:
                raise ValueError
            parsed = urlsplit("https://" + repo)
            if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc)
                    or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..")
                           for part in parsed.path.lstrip("/").split("/"))):
                raise ValueError
            parsed.port
            token_file = Path(options["token_file"])
            types = options.get("runner_types", sorted(RUNNER_TYPES))
            if (not token_file.is_absolute() or not isinstance(types, list) or not types
                    or any(kind not in RUNNER_TYPES for kind in types)):
                raise ValueError
            result.append(MonitorTarget(target_id, "https://" + parsed.netloc.lower(),
                                        parsed.path.lstrip("/"), token_file, frozenset(types)))
        return result
    except (ValueError, TypeError, KeyError):
        raise ObservationError("invalid_configuration") from None


def read_monitor_token(path):
    try:
        info = path.parent.lstat()
        if (path.parent != path.parent.resolve() or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "r", encoding="ascii") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError
            token = handle.read(4097).strip()
        if not token or len(token) > 4096 or any(c.isspace() or not c.isprintable() for c in token):
            raise ValueError
        return token
    except (OSError, ValueError, UnicodeError):
        raise ObservationError("credential_unavailable") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RunnerClient:
    def __init__(self, target):
        self.target = target
        self._token = read_monitor_token(target.token_file)
        self.deadline = time.monotonic() + 240

    def _get(self, path, query=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ObservationError("collection_timeout")
        url = self.target.server + "/api/v4/" + path
        if query:
            url += "?" + urlencode(query)
        request = Request(url, headers={"PRIVATE-TOKEN": self._token, "Accept": "application/json"}, method="GET")
        try:
            with build_opener(_NoRedirect()).open(request, timeout=min(20, remaining)) as response:
                data = response.read(MAX_BYTES + 1)
                page = response.headers.get("X-Next-Page", "")
            if len(data) > MAX_BYTES:
                raise ObservationError("response_too_large")
            if page and (not page.isdigit() or int(page) < 1):
                raise ObservationError("invalid_pagination")
            # Even an upstream echo must not persist the active credential.
            return json.loads(data.decode("utf-8").replace(self._token, "[REDACTED]")), int(page) if page else None
        except HTTPError as exc:
            code = exc.code
            exc.close()
            raise ObservationError("http_" + str(code)) from None
        except (URLError, TimeoutError, OSError):
            raise ObservationError("connection_failed") from None
        except (ValueError, UnicodeError):
            raise ObservationError("invalid_response") from None

    def _pages(self, path):
        items, seen, page = [], set(), 1
        while page:
            if page in seen or len(seen) >= 100:
                raise ObservationError("pagination_limit")
            seen.add(page)
            rows, page = self._get(path, {"page": page, "per_page": 100})
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ObservationError("invalid_response")
            items.extend(rows)
        return items

    def inventory(self):
        rows = self._pages("projects/" + quote(self.target.project, safe="") + "/runners")
        result, seen = [], set()
        for row in rows:
            item = runner_record(row)
            if item["id"] in seen:
                raise ObservationError("duplicate_runner")
            seen.add(item["id"])
            if item["runner_type"] in self.target.runner_types:
                result.append(item)
        return result

    def detail(self, runner_id):
        _positive_id(runner_id)
        row, _ = self._get("runners/" + str(runner_id))
        item = runner_record(row)
        if item["id"] != runner_id:
            raise ObservationError("invalid_response")
        tags = row.get("tag_list")
        if not isinstance(tags, list) or len(tags) > 1000:
            raise ObservationError("invalid_response")
        item.update(tag_list=[_text(tag) for tag in tags], contacted_at=_timestamp(row.get("contacted_at")),
                    access_level=_text(row.get("access_level")), run_untagged=_boolean(row.get("run_untagged")))
        return item

    def managers(self, runner_id):
        _positive_id(runner_id)
        rows = self._pages("runners/" + str(runner_id) + "/managers")
        result = []
        for row in rows:
            _positive_id(row.get("id"))
            result.append({"id": row["id"], "system_id": _text(row.get("system_id")),
                           "version": _text(row.get("version")), "platform": _text(row.get("platform")),
                           "architecture": _text(row.get("architecture")),
                           "contacted_at": _timestamp(row.get("contacted_at")),
                           "status": _heartbeat(row.get("status"))})
        return result


def _positive_id(value):
    if type(value) is not int or value < 1:
        raise ObservationError("invalid_response")


def _text(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 2048:
        raise ObservationError("invalid_response")
    return value


def _boolean(value):
    if value is not None and type(value) is not bool:
        raise ObservationError("invalid_response")
    return value


def _timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        raise ObservationError("invalid_response") from None


def _heartbeat(value):
    return value if isinstance(value, str) and value in HEARTBEATS else "unknown"


def runner_record(row):
    if not isinstance(row, dict):
        raise ObservationError("invalid_response")
    _positive_id(row.get("id"))
    kind = row.get("runner_type")
    if not isinstance(kind, str) or kind not in RUNNER_TYPES:
        raise ObservationError("invalid_response")
    return {"id": row["id"], "description": _text(row.get("description")), "runner_type": kind,
            "status": _heartbeat(row.get("status")), "paused": _boolean(row.get("paused"))}
