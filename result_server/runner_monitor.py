"""Explicit lifecycle and one-shot collection for encrypted runner observations."""

from __future__ import annotations

import argparse
import fcntl
import os

try:
    from utils.encrypted_sqlite import EncryptedDatabaseError, generate_key
    from utils.runner_monitor import ObservationError, configured_monitor_targets
    from utils.runner_observations import RunnerObservations, collect
except ModuleNotFoundError:
    from result_server.utils.encrypted_sqlite import EncryptedDatabaseError, generate_key
    from result_server.utils.runner_monitor import ObservationError, configured_monitor_targets
    from result_server.utils.runner_observations import RunnerObservations, collect


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate-key", "init", "check", "collect", "backup"))
    parser.add_argument("--database", default=os.environ.get("RESULT_SERVER_RUNNER_MONITOR_DB_PATH"))
    parser.add_argument("--key-file", default=os.environ.get("RESULT_SERVER_RUNNER_MONITOR_KEY_FILE"))
    parser.add_argument("--destination")
    args = parser.parse_args(argv)
    if not args.key_file or (args.command != "generate-key" and not args.database):
        parser.error("database and key file paths are required")
    if args.command == "backup" and not args.destination:
        parser.error("--destination is required")
    try:
        if args.command == "generate-key":
            generate_key(args.key_file)
        else:
            store = RunnerObservations(args.database, args.key_file)
            if args.command == "init":
                store.initialize()
            elif args.command == "collect":
                targets = configured_monitor_targets()
                # Lock the existing DB inode across the entire network collection.
                # Web readers still see the previous committed snapshot.
                store.read()
                fd = os.open(store.storage.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        print("Runner observation collection is already running")
                        return 0
                    snapshot = collect(targets, store.read())
                    store.save(snapshot)
                failures = sum(bool(row["inventory"].get("error")) for row in snapshot["targets"].values())
                failures += sum(bool(row[resource].get("error")) for row in snapshot["runners"].values()
                                for resource in ("detail", "managers"))
                print(f"Runner observations: {len(snapshot['targets'])} targets, "
                      f"{len(snapshot['runners'])} runners, {failures} unavailable observations")
                return 1 if failures else 0
            store.storage.check()
            store.read()
            if args.command == "backup":
                store.storage.backup(args.destination)
    except (EncryptedDatabaseError, ObservationError, OSError):
        print("Runner observation operation failed; check storage and monitor configuration")
        return 1
    print("Runner observation operation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
