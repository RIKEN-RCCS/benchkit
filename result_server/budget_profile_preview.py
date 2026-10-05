"""Compare one profile database with the Budget registry without changing either."""

from __future__ import annotations

import argparse
import json
import sys

from .utils.budget_profile_preview import preview_profiles
from .utils.budget_registry import BudgetRegistry, RegistryActor, RegistryError
from .utils.encrypted_sqlite import EncryptedDatabaseError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--profile-database", required=True)
    args = parser.parse_args(argv)
    try:
        # This local operator command requires filesystem access to both DBs and
        # the key. It is not an authentication adapter for a web endpoint.
        result = preview_profiles(BudgetRegistry(args.database, args.key_file),
                                  RegistryActor("local-preview", is_admin=True), args.profile_database)
    except (RegistryError, EncryptedDatabaseError, OSError):
        print("Preview failed; check database access, schemas and GitLab target configuration.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
