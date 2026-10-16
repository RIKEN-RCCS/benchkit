"""Legacy monitor configuration and compatibility imports for the shared client."""

import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import build_opener

try:
    from collector.gitlab import (MonitorTarget, ObservationError, RUNNER_TYPES,
                                  RunnerClient as _RunnerClient, _NoRedirect,
                                  read_monitor_token, runner_record)
except ModuleNotFoundError:
    from ..collector.gitlab import (MonitorTarget, ObservationError, RUNNER_TYPES,
                                    RunnerClient as _RunnerClient, _NoRedirect,
                                    read_monitor_token, runner_record)
from .gitlab_pipeline import configured_gitlab_targets


class RunnerClient(_RunnerClient):
    def _opener(self):
        return build_opener(_NoRedirect())


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
