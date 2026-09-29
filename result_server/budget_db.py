"""Explicit lifecycle commands for the encrypted budget registry."""

from __future__ import annotations

import argparse

try:
    from utils.budget_registry import BudgetRegistry, RegistryError
    from utils.encrypted_sqlite import EncryptedDatabaseError, generate_key
    from utils.budget_migrations import BudgetMigrationBackend
    from utils.db_migrations import EncryptedSQLiteMigrator, MigrationError
except ModuleNotFoundError:
    from result_server.utils.budget_registry import BudgetRegistry, RegistryError
    from result_server.utils.encrypted_sqlite import EncryptedDatabaseError, generate_key
    from result_server.utils.budget_migrations import BudgetMigrationBackend
    from result_server.utils.db_migrations import EncryptedSQLiteMigrator, MigrationError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate-key", "init", "check", "backup", "migrate-empty", "migrate-targets"))
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--database")
    parser.add_argument("--destination")
    args = parser.parse_args(argv)
    if args.command != "generate-key" and not args.database:
        parser.error("--database is required")
    if args.command in ("backup", "migrate-empty", "migrate-targets") and not args.destination:
        parser.error("--destination is required")
    try:
        if args.command == "generate-key":
            generate_key(args.key_file)
        else:
            registry = BudgetRegistry(args.database, args.key_file)
            if args.command == "init":
                registry.initialize()
            if args.command in ("migrate-empty", "migrate-targets"):
                runner = EncryptedSQLiteMigrator(BudgetMigrationBackend(args.database, args.key_file))
                state = runner.plan()
                allowed = (1, 2) if args.command == "migrate-empty" else (3,)
                if state["schema_version"] not in allowed:
                    raise MigrationError("Legacy migration command does not match this schema")
                runner.migrate(backup=args.destination, expected_version=state["schema_version"],
                               expected_revision=state["revision"], expected_instance=state["instance_id"])
            registry.check()
            if args.command == "backup":
                registry.storage.backup(args.destination)
                BudgetRegistry(args.destination, args.key_file).check()
    except (EncryptedDatabaseError, RegistryError, MigrationError) as exc:
        print(f"Budget registry: {exc}")
        return 1
    print("Budget registry operation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
