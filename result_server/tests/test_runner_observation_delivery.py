"""Collector tests use synthetic private files, fake HTTP and clocks only."""

from copy import deepcopy
from datetime import timedelta
from email.message import Message
from http.client import IncompleteRead
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector import delivery, state, transport  # noqa: E402
from collector.errors import DeliveryError  # noqa: E402
from test_runner_observation_protocol import NOW, batch, policy, raw  # noqa: E402

ENDPOINT = "https://cx.example.org/console/api/v1/runner-observations"
KEY = "synthetic-collector-key-not-secret-123456"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected real network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def ack(value=None, **changes):
    value = batch() if value is None else value
    return transport.Response(200, raw({"schema_version": 1, "source_id": value["source_id"],
        "generation": value["generation"], "sequence": value["sequence"], "batch_id": value["batch_id"],
        "received_at": NOW.isoformat(), "status": "accepted", **changes}))


class Sender:
    endpoint = ENDPOINT

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def send(self, data, *, timeout):
        self.calls.append((data, timeout))
        assert load(self.spool)["pending"].encode() == data
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class Clock:
    def __init__(self):
        self.tick, self.sleeps = 0, []

    def monotonic(self):
        return self.tick

    def now(self):
        return NOW + timedelta(seconds=self.tick)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.tick += seconds


@pytest.fixture
def spool(tmp_path):
    directory = tmp_path / "delivery"
    directory.mkdir(mode=0o700)
    state.DeliveryState(directory, policy(), ENDPOINT).initialize()
    return directory


def load(spool):
    return json.loads((spool / "delivery.json").read_bytes())


def run(spool, sender, collect=None, clock=None):
    clock = clock or Clock()
    sender.spool = spool
    return delivery.run_once(spool, policy(), sender, collect or (lambda seq: raw(batch(seq))),
                             now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)


def no_collect(_sequence):
    raise AssertionError("must replay before new collection")


def test_persist_before_send_then_advance(spool):
    sender = Sender(ack())
    assert run(spool, sender) == "acknowledged"
    assert load(spool)["pending"] is None and load(spool)["next_sequence"] == 2
    assert sender.calls == [(raw(batch()), 20)]
    for name in ("delivery.json", "delivery.lock"):
        assert (spool / name).stat().st_mode & 0o777 == 0o600
    assert not list(spool.glob(".delivery-*"))


def test_retry_restart_uses_exact_bytes_without_collection(spool):
    sender = Sender(*[DeliveryError("delivery_connection_failed") for _ in range(3)])
    with pytest.raises(DeliveryError, match="delivery_retry_pending"):
        run(spool, sender)
    again = Sender(ack(status="duplicate"))
    assert run(spool, again, no_collect) == "acknowledged"
    assert all(data == raw(batch()) for data, _ in sender.calls + again.calls)
    assert load(spool)["next_sequence"] == 2


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_status_retries_same_body(spool, status):
    sender = Sender(transport.Response(status, b"ignored"), ack())
    assert run(spool, sender) == "acknowledged"
    assert sender.calls[0] == sender.calls[1]


@pytest.mark.parametrize("status", [201, 202, 204, 301, 400, 401, 403, 404, 409, 413, 415, 422])
def test_other_status_never_acknowledges_or_renumbers(spool, status):
    sender = Sender(transport.Response(status, b"untrusted-private-body"))
    with pytest.raises(DeliveryError, match="^delivery_rejected$"):
        run(spool, sender)
    assert len(sender.calls) == 1 and load(spool)["pending"] is not None
    assert load(spool)["next_sequence"] == 1


@pytest.mark.parametrize("changes", [
    {"source_id": "other"}, {"generation": "other"}, {"sequence": 2}, {"sequence": True},
    {"batch_id": "other"}, {"status": "queued"}, {"extra": "secret"},
    {"schema_version": True}, {"received_at": "bad"}, {"received_at": "2026-01-01T12:00:00"},
    {"received_at": "2026-01-01 12:00:00+00:00"}, {"received_at": "2026-01-01T12:00:00-00:00"},
])
def test_mismatched_ack_retains_pending(spool, changes):
    with pytest.raises(DeliveryError, match="invalid_delivery_acknowledgement"):
        run(spool, Sender(ack(**changes)))
    assert load(spool)["pending"] is not None and load(spool)["next_sequence"] == 1


@pytest.mark.parametrize("body", [b"not-json", b'{"x":1,"x":2}', b"x" * 65537, b"[]"])
def test_bad_ack_body_is_never_saved(spool, body):
    with pytest.raises(DeliveryError, match="invalid_delivery_acknowledgement"):
        run(spool, Sender(transport.Response(200, body)))
    assert load(spool)["pending"] is not None


def test_retry_after_respects_budget(spool):
    clock = Clock()
    assert run(spool, Sender(transport.Response(429, b"", "2"), ack()), clock=clock) == "acknowledged"
    assert clock.sleeps == [2]
    sender = Sender(transport.Response(503, b"", "600"))
    with pytest.raises(DeliveryError, match="delivery_retry_pending"):
        run(spool, sender, clock=clock)
    assert len(sender.calls) == 1 and clock.sleeps == [2]
    assert delivery._delay("Thu, 01 Jan 2026 12:00:05 GMT", 0, NOW) == 5
    assert delivery._delay("bad", 1, NOW) == 2


def test_timeout_budget_reduces_and_stops(spool):
    clock = Clock()
    class Slow(Sender):
        def send(self, data, *, timeout):
            clock.tick += timeout
            return super().send(data, timeout=timeout)
    sender = Slow(*[DeliveryError("delivery_connection_failed") for _ in range(3)])
    with pytest.raises(DeliveryError, match="delivery_retry_pending"):
        run(spool, sender, clock=clock)
    assert len(sender.calls) == 3
    assert sum(timeout for _, timeout in sender.calls) + sum(clock.sleeps) <= 60


def test_crash_before_local_ack_replays(spool, monkeypatch):
    original = state.DeliveryState.save
    def failed(self, directory, value, **kwargs):
        if value["pending"] is None:
            raise OSError("synthetic-private-path")
        return original(self, directory, value, **kwargs)
    monkeypatch.setattr(state.DeliveryState, "save", failed)
    with pytest.raises(DeliveryError, match="delivery_state_unavailable"):
        run(spool, Sender(ack()))
    assert load(spool)["pending"] is not None
    monkeypatch.setattr(state.DeliveryState, "save", original)
    assert run(spool, Sender(ack(status="duplicate")), no_collect) == "acknowledged"


def test_failed_durable_pending_write_never_sends(spool, monkeypatch):
    before = (spool / "delivery.json").read_bytes()
    def fail(_fd):
        raise OSError("synthetic")
    monkeypatch.setattr(state.os, "fsync", fail)
    sender = Sender()
    with pytest.raises(DeliveryError):
        run(spool, sender)
    assert not sender.calls and (spool / "delivery.json").read_bytes() == before
    assert not list(spool.glob(".delivery-*"))


def test_lock_excludes_competing_writer(spool):
    with state.DeliveryState(spool, policy(), ENDPOINT).locked():
        with pytest.raises(DeliveryError, match="delivery_busy"):
            run(spool, Sender(), no_collect)


@pytest.mark.parametrize("change", ["missing", "json", "sequence", "binding", "pending", "duplicate"])
def test_bad_state_stops_before_collection(spool, change):
    path, value = spool / "delivery.json", load(spool)
    if change == "missing": path.unlink()
    elif change == "json": path.write_bytes(b"{")
    elif change == "duplicate": path.write_bytes(b'{"schema_version":1,"schema_version":1}')
    else:
        if change == "sequence": value["next_sequence"] = True
        if change == "binding": value["binding"]["endpoint"] = "https://other.example.org"
        if change == "pending": value["pending"] = raw(batch(2)).decode()
        path.write_text(json.dumps(value))
    with pytest.raises(DeliveryError, match="delivery_state_invalid"):
        run(spool, Sender(), no_collect)


@pytest.mark.parametrize("kind", ["directory_mode", "state_mode", "state_symlink", "state_hardlink", "lock_symlink"])
def test_unsafe_state_paths_rejected(spool, kind):
    path = spool / "delivery.json"
    if kind == "directory_mode": spool.chmod(0o755)
    if kind == "state_mode": path.chmod(0o644)
    if kind == "state_hardlink": os.link(path, spool / "linked")
    if kind == "state_symlink":
        path.rename(spool / "original")
        path.symlink_to(spool / "original")
    if kind == "lock_symlink":
        (spool / "delivery.lock").unlink()
        (spool / "delivery.lock").symlink_to(path)
    with pytest.raises(DeliveryError):
        run(spool, Sender(), no_collect)


def test_explicit_init_never_resets_existing_state(spool):
    before = (spool / "delivery.json").read_bytes()
    with pytest.raises(DeliveryError):
        state.DeliveryState(spool, policy(), ENDPOINT).initialize()
    assert (spool / "delivery.json").read_bytes() == before


def test_scope_or_endpoint_change_does_not_reuse_pending_state(spool):
    before = (spool / "delivery.json").read_bytes()
    for changed_policy, endpoint in ((policy(collector_id="other"), ENDPOINT),
                                     (policy(), ENDPOINT.replace("/console/", "/other/"))):
        store = state.DeliveryState(spool, changed_policy, endpoint)
        with store.locked() as directory:
            with pytest.raises(DeliveryError, match="delivery_state_invalid"):
                store.load(directory, now=NOW)
    assert (spool / "delivery.json").read_bytes() == before


def test_separate_process_obeys_state_lock(spool):
    code = '''
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(0)
sys.exit(1)
'''
    with state.DeliveryState(spool, policy(), ENDPOINT).locked():
        process = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code,
                                  str(spool / "delivery.lock")], cwd=spool,
                                 env={"HOME": str(spool)}, capture_output=True)
        assert process.returncode == 0


def test_sequence_does_not_wrap(spool):
    value = load(spool)
    value["next_sequence"] = 2**53 - 1
    (spool / "delivery.json").write_text(json.dumps(value))
    sender = Sender(ack(batch(2**53 - 1)))
    with pytest.raises(DeliveryError, match="delivery_sequence_exhausted"):
        run(spool, sender)
    assert load(spool)["next_sequence"] == 2**53 - 1 and load(spool)["pending"] is not None


def test_invalid_new_batch_never_sends(spool):
    before = (spool / "delivery.json").read_bytes()
    with pytest.raises(DeliveryError, match="invalid_collected_batch"):
        run(spool, Sender(), lambda _seq: raw(batch(2)))
    assert (spool / "delivery.json").read_bytes() == before


def test_identity_helper_matches_protocol():
    value = batch(7)
    assert delivery.batch_identity(policy(), 7) == {name: value[name] for name in (
        "schema_version", "collector_id", "source_id", "generation", "sequence", "batch_id")}


@pytest.fixture
def key_file(tmp_path):
    directory = tmp_path / "credentials"
    directory.mkdir(mode=0o700)
    path = directory / "collector.key"
    path.write_text(KEY)
    path.chmod(0o600)
    return path


class HTTPResponse(BytesIO):
    def __init__(self, body=b"{}", code=200, **headers):
        super().__init__(body)
        self.code, self.headers = code, Message()
        for name, value in {"Content-Type": "application/json", **headers}.items():
            self.headers[name] = value


def opener(monkeypatch, response):
    calls = []
    def build(*handlers):
        assert any(isinstance(h, transport.ProxyHandler) and h.proxies == {} for h in handlers)
        https = next(h for h in handlers if isinstance(h, transport.HTTPSHandler))
        assert https._context.verify_mode == ssl.CERT_REQUIRED and https._context.check_hostname
        redirect = next(h for h in handlers if isinstance(h, transport._NoRedirect))
        assert redirect.redirect_request(None, None, 302, None, {}, "https://other.example.org") is None
        class Opener:
            def open(self, request, timeout):
                calls.append((request, timeout))
                if isinstance(response, Exception): raise response
                return response
        return Opener()
    monkeypatch.setattr(transport, "build_opener", build)
    return calls


def test_dedicated_post_and_verified_tls(key_file, monkeypatch):
    calls = opener(monkeypatch, HTTPResponse())
    result = transport.HTTPSDelivery(ENDPOINT, key_file).send(b"fixture", timeout=20)
    request, timeout = calls[0]
    assert request.full_url == ENDPOINT and request.method == "POST" and request.data == b"fixture"
    assert request.get_header("X-collector-key") == KEY and timeout == 20
    assert request.get_header("X-api-key") is None and result.status == 200
    assert "{}" not in repr(result)


@pytest.mark.parametrize("endpoint", [
    "http://cx.example.org/api/v1/runner-observations", "https://user:pass@cx.example.org/api/v1/runner-observations",
    ENDPOINT + "?key=x", ENDPOINT + "#x", "https://cx.example.org/wrong",
    "https://cx.example.org/../api/v1/runner-observations", ENDPOINT + "\n",
])
def test_invalid_endpoint_never_reads_key(endpoint):
    with pytest.raises(DeliveryError, match="invalid_delivery_endpoint"):
        transport.HTTPSDelivery(endpoint, "/unused/fixture")


@pytest.mark.parametrize("ca", ["", "relative.crt", "/unused/../ca.crt", "/unused/ca\n.crt", False])
def test_delivery_ca_path_rejected_before_key_read(monkeypatch, ca):
    monkeypatch.setattr(transport, "read_delivery_key", lambda *_args: pytest.fail("no credential read"))
    with pytest.raises(DeliveryError, match="^invalid_delivery_ca_file$"):
        transport.HTTPSDelivery(ENDPOINT, "/unused/key", ca_file=ca)


@pytest.mark.parametrize("kind", ["missing", "invalid", "directory"])
def test_delivery_ca_failure_stops_before_http(key_file, tmp_path, monkeypatch, kind):
    ca = tmp_path / "ca.pem"
    if kind == "invalid": ca.write_text("not a certificate; synthetic private detail")
    if kind == "directory": ca.mkdir()
    monkeypatch.setattr(transport, "build_opener", lambda *_args: pytest.fail("no HTTP before valid CA"))
    with pytest.raises(DeliveryError, match="^delivery_tls_failed$"):
        transport.HTTPSDelivery(ENDPOINT, key_file, ca_file=ca).send(b"fixture", timeout=20)


@pytest.fixture
def tls_certificate(tmp_path):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("OpenSSL executable required for synthetic in-memory TLS handshake")
    certificate, key = tmp_path / "ca.pem", tmp_path / "server.key"
    result = subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-keyout", str(key), "-out", str(certificate), "-subj", "/CN=delivery.example.org",
        "-addext", "subjectAltName=DNS:delivery.example.org",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign",
        "-addext", "extendedKeyUsage=serverAuth",
    ], capture_output=True, timeout=30)
    assert result.returncode == 0, "synthetic certificate generation failed"
    key.chmod(0o600)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(certificate, key)
    return certificate, server


def memory_handshake(context, server_context, hostname="delivery.example.org"):
    client_in, client_out, server_in, server_out = (ssl.MemoryBIO() for _ in range(4))
    client = context.wrap_bio(client_in, client_out, server_hostname=hostname)
    server = server_context.wrap_bio(server_in, server_out, server_side=True)
    completed = set()
    for _ in range(20):
        for name, connection in (("client", client), ("server", server)):
            if name not in completed:
                try:
                    connection.do_handshake()
                    completed.add(name)
                except ssl.SSLWantReadError:
                    pass
        if client_out.pending: server_in.write(client_out.read())
        if server_out.pending: client_in.write(server_out.read())
        if len(completed) == 2:
            return
    pytest.fail("in-memory TLS handshake did not finish")


def test_delivery_ca_only_adds_trust_to_its_context(key_file, tls_certificate, monkeypatch):
    ca, server = tls_certificate
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    before = dict(os.environ)
    defaults = ssl.create_default_context().get_ca_certs(binary_form=True)
    sender = transport.HTTPSDelivery(ENDPOINT, key_file, ca_file=ca)
    context = sender._tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert set(defaults) <= set(context.get_ca_certs(binary_form=True))
    memory_handshake(context, server)
    with pytest.raises(ssl.SSLCertVerificationError):
        memory_handshake(context, server, hostname="wrong.example.org")
    with pytest.raises(ssl.SSLCertVerificationError):
        memory_handshake(ssl.create_default_context(), server)
    assert dict(os.environ) == before


def test_delivery_ca_reaches_only_post_handler(key_file, tls_certificate, monkeypatch):
    ca, server = tls_certificate
    calls = opener(monkeypatch, HTTPResponse())
    original = transport.build_opener
    def build(*handlers):
        context = next(h._context for h in handlers if isinstance(h, transport.HTTPSHandler))
        memory_handshake(context, server)
        return original(*handlers)
    monkeypatch.setattr(transport, "build_opener", build)
    assert transport.HTTPSDelivery(ENDPOINT, key_file, ca_file=ca).send(b"fixture", timeout=20).status == 200
    assert len(calls) == 1 and calls[0][0].method == "POST"


def test_delivery_ca_repair_replays_same_pending_batch(spool, key_file, tls_certificate, monkeypatch):
    ca, _server = tls_certificate
    sender = transport.HTTPSDelivery(ENDPOINT, key_file, ca_file=ca.with_name("missing.pem"))
    calls = opener(monkeypatch, HTTPResponse(ack().body))
    with pytest.raises(DeliveryError, match="^delivery_tls_failed$"):
        run(spool, sender)
    before = load(spool)
    assert before["pending"] is not None and before["next_sequence"] == 1 and not calls
    repaired = transport.HTTPSDelivery(ENDPOINT, key_file, ca_file=ca)
    assert run(spool, repaired, no_collect) == "acknowledged"
    assert calls[0][0].data == before["pending"].encode()
    assert load(spool)["next_sequence"] == 2 and load(spool)["pending"] is None


@pytest.mark.parametrize("kind", ["mode", "symlink", "value"])
def test_bad_key_never_opens_transport(key_file, monkeypatch, kind):
    if kind == "mode": key_file.chmod(0o644)
    if kind == "symlink":
        key_file.rename(key_file.with_name("original"))
        key_file.symlink_to(key_file.with_name("original"))
    if kind == "value": key_file.write_text("invalid")
    calls = opener(monkeypatch, HTTPResponse())
    with pytest.raises(DeliveryError, match="delivery_credential_unavailable"):
        transport.HTTPSDelivery(ENDPOINT, key_file).send(b"fixture", timeout=20)
    assert not calls


@pytest.mark.parametrize("response, code", [
    (HTTPResponse(code=302, Location="https://other.example.org"), "delivery_redirect_rejected"),
    (HTTPResponse(b"x" * 65537), "delivery_response_too_large"),
    (HTTPResponse(**{"Content-Encoding": "gzip"}), "invalid_delivery_response"),
    (HTTPResponse(**{"Content-Type": "text/html"}), "invalid_delivery_response"),
    (URLError(ssl.SSLCertVerificationError("private detail")), "delivery_tls_failed"),
    (URLError("private detail"), "delivery_connection_failed"),
    (IncompleteRead(b"private fragment"), "delivery_connection_failed"),
])
def test_transport_errors_are_value_free(key_file, monkeypatch, response, code):
    opener(monkeypatch, response)
    with pytest.raises(DeliveryError, match="^" + code + "$"):
        transport.HTTPSDelivery(ENDPOINT, key_file).send(b"fixture", timeout=20)


def test_http_error_body_not_reported(key_file, monkeypatch):
    headers = Message()
    headers["Retry-After"] = "3"
    opener(monkeypatch, HTTPError(ENDPOINT, 503, "private reason", headers, BytesIO(b"private body")))
    result = transport.HTTPSDelivery(ENDPOINT, key_file).send(b"fixture", timeout=20)
    assert result.status == 503 and result.retry_after == "3" and "private" not in repr(result)


def test_guard_rejects_an_unmocked_connection():
    with pytest.raises(AssertionError, match="unexpected real network"):
        socket.create_connection(("unused.example.org", 443))


def test_http_date_retry_after_does_not_exceed_budget(spool):
    clock = Clock()
    sender = Sender(transport.Response(429, b"", "Thu, 01 Jan 2026 12:05:00 GMT"))
    with pytest.raises(DeliveryError, match="delivery_retry_pending"):
        run(spool, sender, clock=clock)
    assert clock.sleeps == [] and len(sender.calls) == 1


def test_replay_then_next_invocation_collects_next_sequence(spool):
    sender = Sender(transport.Response(409, b""))
    with pytest.raises(DeliveryError):
        run(spool, sender)
    assert run(spool, Sender(ack(status="duplicate")), no_collect) == "acknowledged"
    sequences = []
    def collect(sequence):
        sequences.append(sequence)
        return raw(batch(sequence))
    assert run(spool, Sender(ack(batch(2))), collect) == "acknowledged"
    assert sequences == [2] and load(spool)["next_sequence"] == 3


def test_tls_failure_not_retried(spool):
    sender = Sender(DeliveryError("delivery_tls_failed"))
    with pytest.raises(DeliveryError, match="delivery_tls_failed"):
        run(spool, sender)
    assert len(sender.calls) == 1 and load(spool)["pending"] is not None


def test_import_without_web_database_packages(tmp_path):
    code = '''
import builtins, sys
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'flask', 'redis', 'sqlcipher3', 'result_server'}:
        raise AssertionError('forbidden dependency')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from collector.delivery import run_once
from collector.transport import HTTPSDelivery
assert not any(name.startswith(('utils.runner_monitor', 'utils.encrypted_sqlite', 'app')) for name in sys.modules)
'''
    process = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, str(ROOT)],
                             cwd=tmp_path, env={"HOME": str(tmp_path)}, capture_output=True, text=True)
    assert process.returncode == 0, process.stderr


def test_lost_ack_replay_uses_real_protocol_duplicate(spool):
    from utils.runner_observation_protocol import apply_batch
    class CX(Sender):
        snapshot = {"targets": {}, "runners": {}}
        lost = True
        def send(self, data, *, timeout):
            update = apply_batch(self.snapshot, data, policy(), received_at=NOW)
            self.snapshot = update.snapshot
            if self.lost:
                raise DeliveryError("delivery_connection_failed")
            assert not update.changed and update.acknowledgement["status"] == "duplicate"
            return transport.Response(200, raw(update.acknowledgement))
    cx = CX()
    with pytest.raises(DeliveryError, match="delivery_retry_pending"):
        run(spool, cx)
    before = deepcopy(cx.snapshot)
    cx.lost = False
    assert run(spool, cx, no_collect) == "acknowledged" and cx.snapshot == before
