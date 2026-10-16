"""Explicit configuration for the standalone observation receiver; no store I/O."""

from dataclasses import dataclass
import os
from pathlib import Path
import re

from .runner_observation_auth import ObservationConfigurationError, configured_observation_sources


class ObservationServiceError(ValueError):
    def __init__(self):
        super().__init__("observation_service_configuration_unavailable")


@dataclass(frozen=True)
class ObservationServiceSettings:
    database: str
    key_file: str
    redis_socket: str
    redis_prefix: str
    url_prefix: str
    bind: str
    certificate: str
    tls_key: str


def _path(value):
    if (not isinstance(value, str) or not value or not Path(value).is_absolute()
            or ".." in Path(value).parts or any(ord(c) < 32 for c in value)):
        raise ValueError
    return str(Path(value))


def service_settings(env=None):
    """Validate explicit references, never fall back to a Portal instance."""
    source = os.environ if env is None else env
    try:
        if source.get("RESULT_SERVER_RUNNER_OBSERVATION_INGEST_ENABLED", "").lower() not in {"1", "true"}:
            raise ValueError
        if source.get("RESULT_SERVER_PUBLIC_PORTAL_MODE", "").lower() not in {"", "0", "false"}:
            raise ValueError
        if not source.get("RESULT_SERVER_GITLAB_TARGETS", "").strip():
            raise ValueError
        database = _path(source["RESULT_SERVER_RUNNER_MONITOR_DB_PATH"])
        key = _path(source["RESULT_SERVER_RUNNER_MONITOR_KEY_FILE"])
        redis_socket = _path(source["RESULT_SERVER_RUNNER_OBSERVATION_REDIS_SOCKET"])
        certificate = _path(source["RESULT_SERVER_RUNNER_OBSERVATION_TLS_CERT_FILE"])
        tls_key = _path(source["RESULT_SERVER_RUNNER_OBSERVATION_TLS_KEY_FILE"])
        if (len({database, key, redis_socket, certificate, tls_key}) != 5
                or Path(database).parent == Path(key).parent):
            raise ValueError
        prefix = source.get("RESULT_SERVER_RUNNER_OBSERVATION_PREFIX", "")
        if not isinstance(prefix, str) or (prefix and not re.fullmatch(r"(?:/[A-Za-z0-9_-]+)+", prefix)):
            raise ValueError
        namespace = source["RESULT_SERVER_RUNNER_OBSERVATION_REDIS_PREFIX"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,126}:", namespace):
            raise ValueError
        bind = source["RESULT_SERVER_RUNNER_OBSERVATION_BIND"]
        match = re.fullmatch(r"127\.0\.0\.1:([0-9]{1,5})", bind)
        if not match or not 1 <= int(match[1]) <= 65535:
            raise ValueError
        configured_observation_sources(source)
        return ObservationServiceSettings(database, key, redis_socket, namespace,
                                          prefix, bind, certificate, tls_key)
    except (ValueError, TypeError, KeyError, AttributeError, ObservationConfigurationError):
        raise ObservationServiceError() from None
