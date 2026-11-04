"""Explicit offline CX snapshot migration, encrypted backup and copy recovery."""

import argparse
import json
import os
from pathlib import Path

from utils.cx_migration import import_snapshot, recover_copy
from utils.cx_persistence import CxPersistence
from utils.encrypted_sqlite import _check_file, _private_parent


def _private_json(path, limit):
    path = Path(path).absolute()
    _private_parent(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        _check_file(os.fstat(source.fileno()))
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Private input exceeds limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate input key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("initialize", "migrate-copy", "check", "backup-copy", "recover-copy", "rebuild-copy"))
    parser.add_argument("--plan", required=True, help="Private JSON plan with explicit paths; never a key value")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        plan = _private_json(args.plan, 65536)
        required = {"database", "key_file"}
        extra = {"roots", "profile_copy", "source_roots", "snapshot_export", "destination", "session_copy", "artifact_database"}
        if not isinstance(plan, dict) or not required <= set(plan) or set(plan) - required - extra:
            raise ValueError("Invalid plan")
        for name in required:
            if not Path(plan[name]).is_absolute():
                raise ValueError("Absolute paths are required")
        if args.operation == 'initialize':
            store = CxPersistence(plan['database'], plan['key_file'], roots=plan['roots'], artifact_path=plan.get('artifact_database'))
            store.initialize()
            report = {'initialized': True}
        elif args.operation == "migrate-copy":
            store = CxPersistence(plan["database"], plan["key_file"], roots=plan["roots"], artifact_path=plan.get('artifact_database'))
            exported = {}
            if plan.get("snapshot_export"):
                exported = _private_json(plan["snapshot_export"], 16 * 1024 * 1024)
                if set(exported) - {"identity", "sessions"}:
                    raise ValueError("Invalid snapshot export")
            report = import_snapshot(store, profile_copy=plan["profile_copy"], source_roots=plan["source_roots"],
                                     identity=exported.get("identity"), sessions=exported.get("sessions"),
                                     session_copy=plan.get("session_copy"))
        else:
            store = CxPersistence.open_existing(plan["database"], plan["key_file"], artifact_path=plan.get('artifact_database'))
            if args.operation == "check":
                store.check()
            elif args.operation == "rebuild-copy":
                store.rebuild()
                store.check()
            else:
                target = Path(plan["destination"])
                if not target.is_absolute():
                    raise ValueError("Absolute destination is required")
                recover_copy(store, target)
            report = {"checked": True}
        print(json.dumps({"operation": args.operation, "status": "success", **report}, sort_keys=True))
        return 0
    except Exception:
        # No paths, SQL statements, records, credentials or exception values.
        print(json.dumps({"operation": args.operation, "status": "failed", "retry_performed": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
