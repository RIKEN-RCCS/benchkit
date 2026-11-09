"""Rehearse explicit Profile-to-Budget mappings on a new database copy only."""

import argparse
import json
from pathlib import Path
import sqlite3

try:
    from .utils.budget_registry import BudgetRegistry, RegistryActor
    from .utils.document_json import load_document_json
    from .utils.encrypted_sqlite import EncryptedDatabaseError
    from .utils.execution_profiles import ExecutionProfileStore
    from .utils.profile_budget_migration import rehearse_bindings
except ImportError:
    from utils.budget_registry import BudgetRegistry, RegistryActor
    from utils.document_json import load_document_json
    from utils.encrypted_sqlite import EncryptedDatabaseError
    from utils.execution_profiles import ExecutionProfileStore
    from utils.profile_budget_migration import rehearse_bindings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--profile-key-file')
    parser.add_argument('--registry', required=True)
    parser.add_argument('--registry-key-file', required=True)
    parser.add_argument('--registry-revision', required=True, type=int)
    parser.add_argument('--mapping', required=True)
    parser.add_argument('--actor', required=True)
    parser.add_argument('--confirm-local-admin', required=True, action='store_true')
    args = parser.parse_args(argv)
    try:
        path = Path(args.mapping)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError
        selections = load_document_json(path.read_text())
        source = ExecutionProfileStore(args.source, key_file=args.profile_key_file)
        registry = BudgetRegistry(args.registry, args.registry_key_file)
        result = rehearse_bindings(source, args.destination, registry,
            RegistryActor(args.actor, is_admin=True), selections, args.registry_revision)
    except (OSError, ValueError, EncryptedDatabaseError, sqlite3.Error):
        print(json.dumps({'error': 'Profile Budget rehearsal failed; retain the copy for inspection'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
