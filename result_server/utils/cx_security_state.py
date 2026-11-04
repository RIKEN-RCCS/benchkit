"""Atomic, expiring authentication/rate guards in the encrypted instance DB."""

import json
import time


class EncryptedSecurityState:
    def __init__(self, storage):
        self.storage = storage

    def ping(self):
        with self.storage._connect(readonly=True) as conn:
            conn.execute('SELECT 1').fetchone()
        return True

    def get(self, key):
        return self.storage.value_get('guards', key)

    def delete(self, key):
        return self.storage.value_delete('guards', key)

    def increment_with_ttl(self, key, ttl, *, refresh=False):
        now = time.time()
        with self.storage.transaction() as conn:
            row = conn.execute("SELECT value,expires FROM cx_values WHERE namespace='guards' AND key=? AND expires>?",
                               (key, now)).fetchone()
            count = int(json.loads(row[0])) + 1 if row else 1
            expires = now + ttl if refresh or not row else row[1]
            conn.execute("INSERT INTO cx_values VALUES('guards',?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value,expires=excluded.expires",
                         (key, json.dumps(count), expires))
            return count

    def claim_once(self, key, ttl):
        now = time.time()
        with self.storage.transaction() as conn:
            if conn.execute("SELECT 1 FROM cx_values WHERE namespace='guards' AND key=? AND expires>?", (key, now)).fetchone():
                return False
            conn.execute("INSERT INTO cx_values VALUES('guards',?,'1',?) ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value,expires=excluded.expires",
                         (key, now + ttl))
            return True
