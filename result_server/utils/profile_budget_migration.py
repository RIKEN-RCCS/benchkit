"""Explicit reviewed Profile selections; no inference, discovery or submission."""

from copy import deepcopy
from contextlib import closing
import os
from pathlib import Path
import sqlite3

from .budget_profile_binding import prepare_binding, profile_fingerprint, selection_fingerprint
from .budget_registry import RegistryConflict, RegistryError
from .profile_storage import _transaction
from .encrypted_sqlite import EncryptedSQLite, _private_parent
from .execution_profiles import ExecutionProfileStore, _utc_now_iso


def plan_bindings(store, registry, actor, selections, revision):
    """Validate an exact mapping against one Profile snapshot and registry revision."""
    if not actor.is_admin:
        raise RegistryError("Profile migration requires administrator approval")
    if (not isinstance(selections, list) or not selections
            or any(not isinstance(item, dict) or set(item) != {"profile_id", "destination_ids", "fingerprint"}
                   or not isinstance(item['profile_id'], str)
                   or not isinstance(item['fingerprint'], str) or len(item['fingerprint']) != 64
                   for item in selections)):
        raise RegistryError("An explicit Profile mapping is required")
    if len({item['profile_id'] for item in selections}) != len(selections):
        raise RegistryError("Duplicate Profile mapping")
    profiles = {p['id']: p for p in store.list_profiles()}
    planned = []
    for item in selections:
        profile = profiles.get(item['profile_id'])
        if not profile or selection_fingerprint(profile) != item['fingerprint']:
            raise RegistryConflict("Profile changed; inspect the copy again")
        if '_invalid_metadata_json' in (profile.get('metadata_json') or {}):
            raise RegistryError("Existing Profile metadata requires review")
        binding = prepare_binding(profile, registry, actor, item['destination_ids'], revision)
        metadata = profile.get('metadata_json') or {}
        if 'budget_binding' in metadata:
            old = metadata['budget_binding']
            if (not isinstance(old, dict) or old.get('version') not in (1, 2)
                    or old.get('profile_fingerprint') != profile_fingerprint(profile)
                    or not isinstance(old.get('selected_by'), str) or not old['selected_by']):
                raise RegistryError("Existing Budget selection requires review")
            expected = old.get('snapshot')
            actual = binding['snapshot']
            def normalized(snapshot):
                try:
                    if not isinstance(snapshot, dict) or snapshot.get('version') not in (1, 2):
                        raise ValueError
                    selections = snapshot['selections'] if snapshot['version'] == 2 else [
                        {key: snapshot[key] for key in ('budget_id', 'destination_id', 'route')}]
                    return snapshot['target'], sorted(selections, key=lambda row: row['destination_id'])
                except (KeyError, TypeError, ValueError):
                    raise RegistryError("Existing Budget snapshot requires review") from None
            if normalized(expected) != normalized(actual):
                raise RegistryError("Migration cannot change a reviewed Budget route")
            binding['selected_by'] = old['selected_by']
        normalized = deepcopy(profile)
        normalized['allocation_project_id'] = ''
        normalized['metadata_json'] = dict(normalized['metadata_json'], execution_mode='budget')
        binding['profile_fingerprint'] = profile_fingerprint(normalized)
        normalized['metadata_json']['budget_binding'] = binding
        planned.append(dict(profile_id=profile['id'], fingerprint=item['fingerprint'], binding=binding,
                            allocation_copy_removed=bool(profile['allocation_project_id'])))
    return dict(registry_revision=revision, profiles=planned)


def apply_bindings(store, registry, actor, selections, revision):
    """Apply to the explicitly supplied copy, keeping all Profile changes atomic."""
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        token = _transaction.set((str(Path(store.db_path).absolute()), conn, store._key()))
        try:
            plan = plan_bindings(store, registry, actor, selections, revision)
            for item in plan['profiles']:
                profile = next(p for p in store.list_profiles() if p['id'] == item['profile_id'])
                now = _utc_now_iso()
                conn.execute("UPDATE execution_profiles SET allocation_project_id='' WHERE id=?", (profile['id'],))
                store._save_budget_binding_in_conn(conn, profile['id'], item['binding'], actor.principal,
                                                   now, event_type='budget_binding_migrated')
            # A registry edit during the batch must not yield a mixed selection.
            if registry.catalog(actor)['revision'] != revision:
                raise RegistryConflict("Registry changed; inspect the copy again")
            return dict(applied=len(plan['profiles']), allocation_copies_removed=sum(
                item['allocation_copy_removed'] for item in plan['profiles']))
        finally:
            _transaction.reset(token)


def rehearse_bindings(source, destination, registry, actor, selections, revision):
    """Create a new copy from read-only source connections and migrate only it."""
    destination = Path(destination).absolute()
    key = source._key()
    if key:
        EncryptedSQLite(source.db_path, key).backup(destination)
    else:
        _private_parent(destination)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        uri = Path(source.db_path).absolute().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as original, closing(sqlite3.connect(destination)) as copy:
            original.backup(copy)
    copy = ExecutionProfileStore(str(destination), key_file=key)
    result = apply_bindings(copy, registry, actor, selections, revision)
    return dict(result, rehearsal=True)
