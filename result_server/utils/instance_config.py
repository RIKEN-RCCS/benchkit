"""Resolve instance-local references without opening stores or changing the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstanceSettings:
    name: str
    data_dir: str
    url_prefix: str
    profile_db_path: str
    redis_prefix: str
    session_cookie_name: str
    totp_issuer: str


def resolve_instance_settings(env: Mapping[str, str] | None = None) -> InstanceSettings:
    """Require an explicit instance; existing path and identity overrides take precedence."""
    source = os.environ if env is None else env
    name = source.get("RESULT_SERVER_INSTANCE", "").strip()
    prefixes = {"main": "", "dev1": "/dev", "dev2": "/dev2"}
    if name not in prefixes:
        raise ValueError("RESULT_SERVER_INSTANCE must be main, dev1, or dev2")

    data_dir = source.get("RESULT_SERVER_DATA_DIR", "").strip()
    if not data_dir:
        root = source.get("BASE_PATH", "").strip()
        if not root:
            raise ValueError("RESULT_SERVER_DATA_DIR or BASE_PATH must be specified")
        data_dir = str(Path(root) / name)
    if not Path(data_dir).is_absolute():
        raise ValueError("The instance data directory must be absolute")

    db_path = source.get("RESULT_SERVER_DB_PATH", "").strip() or str(
        Path(data_dir) / "cx_portal.sqlite3"
    )
    if not Path(db_path).is_absolute():
        raise ValueError("RESULT_SERVER_DB_PATH must be absolute")
    identity = "dev" if name == "dev1" else name
    issuer = source.get("TOTP_ISSUER", "Benchkit")
    if name != "main":
        issuer += "-Dev" if name == "dev1" else "-Dev2"
    return InstanceSettings(
        name=name,
        data_dir=data_dir,
        url_prefix=prefixes[name],
        profile_db_path=db_path,
        redis_prefix=source.get("RESULT_SERVER_REDIS_PREFIX", f"{identity}:"),
        session_cookie_name=source.get("RESULT_SERVER_SESSION_COOKIE_NAME", f"session_{identity}"),
        totp_issuer=issuer,
    )
