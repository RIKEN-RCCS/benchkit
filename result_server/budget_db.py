"""Explicit lifecycle commands for the encrypted budget registry."""

from __future__ import annotations

import argparse

try:
    from utils.budget_registry import BudgetRegistry, RegistryError
    from utils.encrypted_sqlite import EncryptedDatabaseError, generate_key
except ModuleNotFoundError:
    from result_server.utils.budget_registry import BudgetRegistry, RegistryError
    from result_server.utils.encrypted_sqlite import EncryptedDatabaseError, generate_key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate-key", "init", "check", "backup", "migrate-empty"))
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--database")
    parser.add_argument("--destination")
    args = parser.parse_args(argv)
    if args.command != "generate-key" and not args.database:
        parser.error("--database is required")
    if args.command in ("backup", "migrate-empty") and not args.destination:
        parser.error("--destination is required")
    try:
        if args.command == "generate-key":
            generate_key(args.key_file)
        else:
            registry = BudgetRegistry(args.database, args.key_file)
            if args.command == "init":
                registry.initialize()
            if args.command == "migrate-empty":
                registry.storage.backup(args.destination)
                registry.migrate_empty()
            registry.check()
            if args.command == "backup":
                registry.storage.backup(args.destination)
                BudgetRegistry(args.destination, args.key_file).check()
    except (EncryptedDatabaseError, RegistryError) as exc:
        print(f"Budget registry: {exc}")
        return 1
    print("Budget registry operation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
