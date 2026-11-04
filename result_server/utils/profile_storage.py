"""Profile backend binding, also usable by headless commands without Flask."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path

from utils.encrypted_sqlite import EncryptedSQLite, EncryptedDatabaseError


_transaction = ContextVar('cx_persistence_transaction', default=None)


def persistence_settings(source=None):
    source = os.environ if source is None else source
    database = source.get('RESULT_SERVER_PERSISTENCE_DB')
    key = source.get('RESULT_SERVER_PERSISTENCE_KEY')
    artifacts = source.get('RESULT_SERVER_PERSISTENCE_ARTIFACT_DB')
    if database or key or artifacts:
        if not database or not key or any(not Path(path).is_absolute() for path in (database, key, artifacts) if path):
            raise EncryptedDatabaseError('Both absolute encrypted persistence bindings are required')
    return database, key, artifacts


def configured_store():
    try:
        from flask import current_app, has_app_context
    except ImportError:
        return None
    return current_app.extensions.get('cx_persistence') if has_app_context() else None


def profile_key(path):
    active = _transaction.get()
    if active and active[0] == str(Path(path).absolute()):
        return active[2]
    store = configured_store()
    if store:
        if Path(path).absolute() != store.path:
            raise EncryptedDatabaseError('Profile database does not match this encrypted instance')
        return store.storage.key_file
    database, key, _ = persistence_settings()
    if database:
        if Path(path).absolute() != Path(database).absolute():
            raise EncryptedDatabaseError('Profile database does not match the encrypted configuration')
        return key
    return None


@contextmanager
def profile_connection(path, key_file):
    active = _transaction.get()
    if active and active[0] == str(Path(path).absolute()):
        yield active[1]
    else:
        with EncryptedSQLite(path, key_file).connect() as conn:
            with conn:
                yield conn
