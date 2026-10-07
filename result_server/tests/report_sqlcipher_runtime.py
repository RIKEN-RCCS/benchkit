#!/usr/bin/env python3
"""Record CI wheel identity and runtime versions without deployment details."""

import importlib.metadata
import json
from pathlib import Path
import platform
import re
import secrets
import sys
from urllib.parse import urlsplit


def runtime_versions():
    from sqlcipher3 import dbapi2

    connection = dbapi2.connect(":memory:")
    try:
        # Provider metadata requires an initialized codec, not a deployed key.
        connection.execute(f'''PRAGMA key = "x'{secrets.token_hex(32)}'"''')
        connection.execute("CREATE TABLE probe (id INTEGER)")
        versions = {}
        for name in ("cipher_version", "cipher_provider", "cipher_provider_version"):
            row = connection.execute("PRAGMA " + name).fetchone()
            if not row or not isinstance(row[0], str) or not row[0].strip():
                raise ValueError("Runtime version is unavailable")
            versions[name] = row[0]
        versions["sqlite_version"] = connection.execute("SELECT sqlite_version()").fetchone()[0]
        return versions
    finally:
        connection.close()


def build_record(install_report):
    entries = [item for item in install_report["install"]
               if item["metadata"]["name"].lower().replace("_", "-") == "sqlcipher3-binary"]
    if len(entries) != 1:
        raise ValueError("Expected one installed SQLCipher wheel")
    entry = entries[0]
    version = importlib.metadata.version("sqlcipher3-binary")
    if entry["metadata"]["version"] != version:
        raise ValueError("Installed distribution does not match the install report")
    download = entry["download_info"]
    filename = urlsplit(download["url"]).path.rsplit("/", 1)[-1]
    digest = download["archive_info"]["hashes"]["sha256"]
    if not re.fullmatch(r"sqlcipher3_binary-[A-Za-z0-9_.+-]+\.whl", filename):
        raise ValueError("Expected a wheel filename")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected a SHA-256 digest")
    return {
        "python_version": platform.python_version(),
        "distribution": {"name": "sqlcipher3-binary", "version": version},
        "wheel": {"filename": filename, "sha256": digest},
        "runtime": runtime_versions(),
    }


def main(argv):
    try:
        if len(argv) != 2:
            raise ValueError("Expected one install report")
        record = build_record(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    except Exception:
        # Do not print report contents, URLs, paths, or driver exception details.
        print("SQLCipher runtime record failed", file=sys.stderr)
        return 1
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
