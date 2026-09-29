"""Explicit lifecycle entrypoint for one database instance at a time."""

import argparse
import json

try:
    from utils.budget_migrations import BudgetMigrationBackend
    from utils.budget_registry import RegistryError
    from utils.db_migrations import EncryptedSQLiteMigrator, MigrationError
    from utils.encrypted_sqlite import EncryptedDatabaseError
except ModuleNotFoundError:
    from result_server.utils.budget_migrations import BudgetMigrationBackend
    from result_server.utils.budget_registry import RegistryError
    from result_server.utils.db_migrations import EncryptedSQLiteMigrator, MigrationError
    from result_server.utils.encrypted_sqlite import EncryptedDatabaseError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "plan", "rehearse", "migrate", "verify"))
    parser.add_argument("--kind", choices=("budget",), required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--destination", help="New encrypted rehearsal copy")
    parser.add_argument("--backup", help="New encrypted pre-migration backup")
    parser.add_argument("--expect-version", type=int)
    parser.add_argument("--expect-revision", type=int)
    parser.add_argument("--expect-instance", help="Instance ID returned by status or plan")
    parser.add_argument("--confirm", action="store_true", help="Confirm target and compatible clients")
    args = parser.parse_args(argv)
    if args.command == "rehearse" and not args.destination:
        parser.error("rehearse requires --destination")
    if args.command == "migrate" and (not args.backup or not args.confirm
                                     or args.expect_version is None or args.expect_revision is None or not args.expect_instance):
        parser.error("migrate requires --backup, --expect-version, --expect-revision, --expect-instance and --confirm")
    if args.destination and args.command != "rehearse":
        parser.error("--destination is only valid with rehearse")
    if args.command != "migrate" and (args.backup or args.confirm or args.expect_version is not None or args.expect_revision is not None or args.expect_instance):
        parser.error("migration options are only valid with migrate")
    try:
        runner = EncryptedSQLiteMigrator(BudgetMigrationBackend(args.database, args.key_file))
        if args.command == "migrate":
            result = runner.migrate(backup=args.backup, expected_version=args.expect_version,
                                    expected_revision=args.expect_revision, expected_instance=args.expect_instance)
        elif args.command == "rehearse":
            result = runner.rehearse(destination=args.destination)
        else:
            result = getattr(runner, args.command)()
    except (EncryptedDatabaseError, RegistryError, MigrationError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
