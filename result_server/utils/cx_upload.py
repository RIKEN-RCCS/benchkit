"""SQLCipher-backed multipart spool. Never use Werkzeug's plaintext disk spool."""

import io
from pathlib import Path
import tempfile

from flask import Request
from werkzeug.exceptions import RequestEntityTooLarge

from .encrypted_sqlite import EncryptedSQLite, generate_key


PAGE_SIZE = 1024 * 1024


class EncryptedUpload(io.RawIOBase):
    def __init__(self, parent, limit):
        super().__init__()
        self.directory = tempfile.TemporaryDirectory(prefix=".cx-upload-", dir=parent)
        self.context = None
        self.position, self.length, self.limit = 0, 0, limit
        try:
            root = Path(self.directory.name)
            (root / "data").mkdir(mode=0o700)
            (root / "key").mkdir(mode=0o700)
            key = root / "key" / "ephemeral"
            generate_key(key)
            self.context = EncryptedSQLite(root / "data" / "spool.db", key).connect(create=True)
            self.conn = self.context.__enter__()
            self.conn.execute("CREATE TABLE pages(number INTEGER PRIMARY KEY, data BLOB NOT NULL)")
        except BaseException:
            self.close()
            raise

    def readable(self):
        return True

    def writable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.length)
        if whence not in (0, 1, 2) or position < 0 or position > self.limit:
            raise ValueError("Invalid upload offset")
        self.position = position
        return position

    def write(self, data):
        if self.position + len(data) > self.limit:
            raise RequestEntityTooLarge()
        original = len(data)
        view = memoryview(data)
        while view:
            number, offset = divmod(self.position, PAGE_SIZE)
            row = self.conn.execute("SELECT data FROM pages WHERE number=?", (number,)).fetchone()
            page = bytearray(row[0] if row else b"")
            take = min(len(view), PAGE_SIZE - offset)
            if len(page) < offset + take:
                page.extend(b"\x00" * (offset + take - len(page)))
            page[offset:offset + take] = view[:take]
            self.conn.execute("INSERT INTO pages VALUES(?,?) ON CONFLICT(number) DO UPDATE SET data=excluded.data",
                              (number, bytes(page)))
            self.position += take
            view = view[take:]
        self.length = max(self.length, self.position)
        return original

    def read(self, size=-1):
        size = max(0, self.length - self.position) if size is None or size < 0 else min(size, max(0, self.length - self.position))
        result = bytearray()
        while size:
            number, offset = divmod(self.position, PAGE_SIZE)
            take = min(size, PAGE_SIZE - offset)
            row = self.conn.execute("SELECT data FROM pages WHERE number=?", (number,)).fetchone()
            data = bytes(row[0]) if row else b""
            result.extend(data[offset:offset + take].ljust(take, b"\x00"))
            self.position += take
            size -= take
        return bytes(result)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        if self.closed:
            return
        try:
            if self.context:
                self.context.__exit__(None, None, None)
                self.context = None
        finally:
            self.directory.cleanup()
            super().close()


def configure_encrypted_uploads(app, store):
    class EncryptedRequest(Request):
        def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
            stream = EncryptedUpload(store.path.parent, app.config["MAX_CONTENT_LENGTH"])
            self.__dict__.setdefault("_cx_uploads", []).append(stream)
            return stream

    app.request_class = EncryptedRequest

    @app.teardown_request
    def close_spools(_error):
        from flask import request
        for stream in request.__dict__.get("_cx_uploads", []):
            stream.close()
