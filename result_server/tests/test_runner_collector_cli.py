"""Synthetic GitLab adapter and explicit Collector CLI; no external connections."""

from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector import cli, collection, config, delivery, gitlab, transport  # noqa: E402
from collector.errors import DeliveryError  # noqa: E402
from utils.runner_observation_protocol import apply_batch  # noqa: E402
from test_runner_observation_protocol import NOW, GENERATION, policy, target, batch, raw, runner, summary  # noqa: E402
from test_runner_observation_delivery import tls_certificate, memory_handshake  # noqa: E402, F401

ENDPOINT = "https://cx.example.org/console/api/v1/runner-observations"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*_args, **_kwargs):
        raise AssertionError("unexpected real connection")
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)


def monitor(name="first", server="https://gitlab.example.org"):
    return gitlab.MonitorTarget(name, server, "group/" + name, Path("/unused/read.token"))


class Client:
    def __init__(self, target, *, calls, failures):
        self.target, self.calls, self.failures = target, calls, failures

    def get(self, resource):
        self.calls.append((self.target.id, resource))
        failure = self.failures.get((self.target.id, resource))
        if failure:
            raise gitlab.ObservationError(failure)
        return {"inventory": [summary()], "detail": runner()["detail"]["data"],
                "managers": runner()["managers"]["data"]}[resource]

    def inventory(self): return self.get("inventory")
    def detail(self, _id): return self.get("detail")
    def managers(self, _id): return self.get("managers")


def collect(targets=None, scope=None, failures=None, **kwargs):
    calls = []
    def factory(target):
        return Client(target, calls=calls, failures=failures or {})
    value = collection.collect_batch(scope or policy(), targets or [monitor()], 1,
                                     client_factory=factory, now=lambda: NOW, **kwargs)
    return json.loads(value), calls


def test_successful_adapter_matches_protocol():
    value, calls = collect()
    assert value == batch()
    assert calls == [("first", "inventory"), ("first", "detail"), ("first", "managers")]


def test_shared_runner_read_once_and_same_server_fallback():
    scope = policy(target(), target("second"))
    value, calls = collect([monitor(), monitor("second")], scope)
    assert len(value["runners"]) == 1 and len(value["targets"]) == 2
    assert sum(resource == "detail" for _, resource in calls) == 1
    value, calls = collect([monitor(), monitor("second")], scope,
                           {("first", "detail"): "http_403"})
    assert ("second", "detail") in calls and value["runners"][0]["detail"]["status"] == "ok"


def test_same_id_on_different_servers_does_not_cross_credentials():
    scope = policy(target(), target("second", server_id="other", server="https://other.example.org"))
    value, calls = collect([monitor(), monitor("second", "https://other.example.org")], scope,
                           {("first", "detail"): "http_403"})
    assert len(value["runners"]) == 2
    by_server = {item["server_id"]: item for item in value["runners"]}
    assert by_server["server"]["detail"]["error_code"] == "http_403"
    assert by_server["other"]["detail"]["status"] == "ok"


@pytest.mark.parametrize("resource", ["inventory", "detail", "managers"])
def test_partial_failures_stay_observations_and_cx_keeps_old_data(resource):
    before = apply_batch({"targets": {}, "runners": {}}, raw(batch()), policy(), received_at=NOW).snapshot
    value, calls = collect(failures={("first", resource): "http_403"})
    value.update(sequence=2, batch_id=delivery.batch_identity(policy(), 2)["batch_id"])
    after = apply_batch(before, raw(value), policy(), received_at=NOW).snapshot
    old = before["targets"]["first"]["inventory"] if resource == "inventory" else next(iter(before["runners"].values()))[resource]
    observed = after["targets"]["first"]["inventory"] if resource == "inventory" else next(iter(after["runners"].values()))[resource]
    assert observed["data"] == old["data"] and observed["last_success_at"] == old["last_success_at"]
    if resource == "inventory":
        assert calls == [("first", "inventory")] and value["runners"] == []
    assert observed["error"] == "http_403"


def test_factory_failure_is_fixed_and_includes_no_exception_value():
    def factory(_target):
        raise gitlab.ObservationError("private-path-and-secret")
    result = collection.collect_batch(policy(), [monitor()], 1, client_factory=factory, now=lambda: NOW)
    assert b"private" not in result
    assert json.loads(result)["targets"][0]["inventory"]["error_code"] == "invalid_response"


def test_collection_deadline_shared_across_resources():
    ticks = iter([0, 0, 240, 240, 240, 240])
    value, calls = collect(monotonic=lambda: next(ticks))
    assert calls == [("first", "inventory")]
    assert value["runners"][0]["detail"]["error_code"] == "collection_timeout"
    assert value["runners"][0]["managers"]["error_code"] == "collection_timeout"


def test_bad_collection_identity_precedes_credentials():
    with pytest.raises(DeliveryError, match="invalid_collection_configuration"):
        collect([monitor("other")])


@pytest.mark.parametrize("bound", ["MAX_BYTES", "MAX_RUNNERS", "MAX_MANAGERS"])
def test_collection_bounds_stop_before_delivery(monkeypatch, bound):
    monkeypatch.setattr(collection, bound, 0)
    with pytest.raises(DeliveryError, match="invalid_collected_batch"):
        collect()


@pytest.fixture
def configuration(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    value = {"schema_version": 1, "collector_id": "collector", "source_id": "source", "generation": GENERATION,
             "endpoint": ENDPOINT, "state_directory": str(spool), "key_file": str(private / "delivery.key"),
             "targets": [{"target_id": "first", "server_id": "server", "server_url": "https://gitlab.example.org",
                          "project": "group/first", "token_file": str(private / "read.token")}]}
    path = private / "collector.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path, value, spool


def test_config_explicit_and_init_does_not_read_keys(configuration, monkeypatch):
    path, _, spool = configuration
    monkeypatch.setenv("RESULT_SERVER_RUNNER_MONITOR_DB_PATH", "/unused/real-db")
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", "unrelated")
    settings = config.load_configuration(path)
    assert settings.policy == policy() and not settings.key_file.exists()
    assert settings.delivery_ca_file is None
    assert cli.main(["init", "--config", str(path)]) == 0
    assert (spool / "delivery.json").exists() and not settings.key_file.exists()


@pytest.mark.parametrize("change", ["field", "schema", "types", "target", "plain_token", "same_key", "relative", "http"])
def test_invalid_config_fixed_error_before_state_or_network(configuration, change, capsys):
    path, value, spool = configuration
    if change == "field": value["database"] = "private-db"
    if change == "schema": value["schema_version"] = True
    if change == "types": value["targets"][0]["runner_types"] = "project_type"
    if change == "target": value["targets"].append(deepcopy(value["targets"][0]))
    if change == "plain_token": value["targets"][0]["token"] = "private-token"
    if change == "same_key": value["targets"][0]["token_file"] = value["key_file"]
    if change == "relative": value["key_file"] = "relative.key"
    if change == "http": value["endpoint"] = ENDPOINT.replace("https:", "http:")
    path.write_text(json.dumps(value))
    assert cli.main(["init", "--config", str(path)]) == 1
    assert capsys.readouterr().out == "Collector operation failed: invalid_collector_configuration\n"
    assert not list(spool.iterdir())


@pytest.mark.parametrize("change", ["duplicate", "mode", "symlink", "missing"])
def test_unsafe_config_file_rejected(configuration, change):
    path, _, _ = configuration
    if change == "duplicate": path.write_text('{"schema_version":1,"schema_version":1}')
    if change == "mode": path.chmod(0o644)
    if change == "missing": path.unlink()
    if change == "symlink":
        other = path.with_name("original")
        path.rename(other)
        path.symlink_to(other)
    with pytest.raises(DeliveryError, match="invalid_collector_configuration"):
        config.load_configuration(path)


def test_delivery_ca_config_init_and_cli_forwarding(configuration, monkeypatch):
    path, value, spool = configuration
    ca = path.parent / "receiver-ca.crt"
    value["delivery_ca_file"] = str(ca)
    path.write_text(json.dumps(value))
    settings = config.load_configuration(path)
    assert settings.delivery_ca_file == ca and not ca.exists()
    assert cli.main(["init", "--config", str(path)]) == 0
    before = (spool / "delivery.json").read_bytes()
    calls = []
    def sender(endpoint, key, *, ca_file):
        assert endpoint == ENDPOINT and key == settings.key_file and ca_file == ca
        calls.append(ca_file)
        return object()
    monkeypatch.setattr(cli, "HTTPSDelivery", sender)
    monkeypatch.setattr(cli, "run_once", lambda *_args: "acknowledged")
    assert cli.main(["collect", "--config", str(path)]) == 0
    assert calls == [ca] and (spool / "delivery.json").read_bytes() == before
    del value["delivery_ca_file"]
    path.write_text(json.dumps(value))
    assert config.load_configuration(path).delivery_ca_file is None
    assert (spool / "delivery.json").read_bytes() == before


@pytest.mark.parametrize("value", [None, "", "relative.crt", "/unused/../ca.crt", "/unused/ca\n.crt", False, []])
def test_delivery_ca_invalid_config_before_init(configuration, value, capsys):
    path, contents, spool = configuration
    contents["delivery_ca_file"] = value
    path.write_text(json.dumps(contents))
    assert cli.main(["init", "--config", str(path)]) == 1
    assert capsys.readouterr().out == "Collector operation failed: invalid_collector_configuration\n"
    assert not list(spool.iterdir())


def test_cli_new_collection_then_lost_ack_replay_without_gitlab(configuration, monkeypatch, capsys):
    path, _, spool = configuration
    assert cli.main(["init", "--config", str(path)]) == 0
    calls, snapshot, lost = [], {"targets": {}, "runners": {}}, True
    def collect(_policy, targets, sequence):
        calls.append(sequence)
        assert targets[0].id == "first"
        return raw(batch(sequence))
    class Sender:
        def __init__(self, endpoint, _key, *, ca_file=None): self.endpoint = endpoint
        def send(self, data, *, timeout):
            nonlocal snapshot
            update = apply_batch(snapshot, data, policy(), received_at=NOW)
            snapshot = update.snapshot
            if lost:
                raise DeliveryError("delivery_connection_failed")
            assert not update.changed
            return transport.Response(200, raw(update.acknowledgement))
    def run(*args):
        return delivery.run_once(*args, now=lambda: NOW, sleep=lambda _seconds: None)
    monkeypatch.setattr(cli, "collect_batch", collect)
    monkeypatch.setattr(cli, "HTTPSDelivery", Sender)
    monkeypatch.setattr(cli, "run_once", run)
    assert cli.main(["collect", "--config", str(path)]) == 1
    assert calls == [1] and json.loads((spool / "delivery.json").read_text())["pending"]
    lost = False
    monkeypatch.setattr(cli, "collect_batch", lambda *_args: pytest.fail("no new GitLab fetch on replay"))
    assert cli.main(["collect", "--config", str(path)]) == 0
    assert calls == [1] and json.loads((spool / "delivery.json").read_text())["next_sequence"] == 2


def test_missing_state_prevents_first_gitlab_call(configuration, monkeypatch):
    path, _, _ = configuration
    monkeypatch.setattr(cli, "collect_batch", lambda *_args: pytest.fail("missing state"))
    assert cli.main(["collect", "--config", str(path)]) == 1


def test_cli_entrypoint_help_without_optional_packages(tmp_path):
    code = '''
import builtins, runpy, sys
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'flask', 'redis', 'sqlcipher3', 'result_server'} or name in {'utils.gitlab_pipeline', 'utils.runner_monitor', 'utils.encrypted_sqlite'}:
        raise AssertionError('forbidden CX dependency')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
sys.argv = ['collector_cli.py', '--help']
runpy.run_path(sys.path[0] + '/collector_cli.py', run_name='__main__')
'''
    process = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, str(ROOT)],
                             cwd=tmp_path, env={"HOME": str(tmp_path)}, capture_output=True, text=True)
    assert process.returncode == 0 and "--config" in process.stdout, process.stderr


@pytest.fixture
def credential(configuration):
    path, value, _ = configuration
    token = Path(value["targets"][0]["token_file"])
    token.write_text("synthetic-gitlab-credential")
    token.chmod(0o600)
    return token


def test_client_get_only_no_proxy_redirect_and_redacts_escaped_echo(credential, monkeypatch):
    calls = []
    class Response(BytesIO):
        headers = {"X-Next-Page": ""}
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            body = json.dumps([summary(description="synthetic-gitlab-credential")]).replace("synthetic", "\\u0073ynthetic")
            return Response(body.encode())
    def opener(*handlers):
        assert any(isinstance(h, gitlab.ProxyHandler) and not h.proxies for h in handlers)
        redirect = next(h for h in handlers if isinstance(h, gitlab._NoRedirect))
        assert redirect.redirect_request(None, None, 302, None, {}, "https://other.example.org") is None
        return Opener()
    monkeypatch.setattr(gitlab, "build_opener", opener)
    client = gitlab.RunnerClient(gitlab.MonitorTarget("first", "https://gitlab.example.org", "group/first", credential))
    assert client.inventory()[0]["description"] == "[REDACTED]"
    assert calls[0].method == "GET" and "group%2Ffirst" in calls[0].full_url
    assert calls[0].get_header("Private-token") == "synthetic-gitlab-credential"


def test_client_rejects_unsafe_target_before_credential_read(monkeypatch):
    monkeypatch.setattr(gitlab, "read_monitor_token", lambda _path: pytest.fail("invalid target"))
    with pytest.raises(gitlab.ObservationError, match="invalid_configuration"):
        gitlab.RunnerClient(gitlab.MonitorTarget("first", "http://gitlab.example.org", "a/b", Path("/unused/token")))


def test_duplicate_managers_is_failure_not_complete_success(credential, monkeypatch):
    client = gitlab.RunnerClient(gitlab.MonitorTarget("first", "https://gitlab.example.org", "a/b", credential))
    manager = runner()["managers"]["data"][0]
    monkeypatch.setattr(client, "_pages", lambda _path: [manager, manager])
    with pytest.raises(gitlab.ObservationError, match="invalid_response"):
        client.managers(7)


@pytest.mark.parametrize("use_ca", [False, True])
def test_full_cli_real_adapter_and_clients_with_fake_http(configuration, credential, monkeypatch, request, use_ca):
    from test_runner_observation_delivery import HTTPResponse
    path, value, spool = configuration
    ca, server = request.getfixturevalue("tls_certificate") if use_ca else (None, None)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    environment = dict(os.environ)
    if use_ca:
        value["delivery_ca_file"] = str(ca)
        path.write_text(json.dumps(value))
    key = Path(value["key_file"])
    key.write_text("synthetic-cx-collector-key-not-secret-1234")
    key.chmod(0o600)
    requests, snapshot, first_response = [], {"targets": {}, "runners": {}}, True
    class GitLab:
        def open(self, request, timeout):
            requests.append(request)
            assert request.method == "GET" and request.get_header("X-collector-key") is None
            assert request.get_header("Private-token") == "synthetic-gitlab-credential"
            if "/projects/" in request.full_url: payload = [summary()]
            elif "/managers" in request.full_url: payload = runner()["managers"]["data"]
            else: payload = runner()["detail"]["data"]
            return HTTPResponse(raw(payload))
    class CX:
        def open(self, request, timeout):
            nonlocal snapshot, first_response
            requests.append(request)
            assert request.method == "POST" and request.full_url == ENDPOINT
            assert request.get_header("Private-token") is None
            assert request.get_header("X-collector-key") == "synthetic-cx-collector-key-not-secret-1234"
            update = apply_batch(snapshot, request.data, policy(), received_at=datetime.now(timezone.utc))
            snapshot = update.snapshot
            if first_response:
                first_response = False
                raise OSError("synthetic lost response")
            assert not update.changed and update.acknowledgement["status"] == "duplicate"
            return HTTPResponse(raw(update.acknowledgement))
    def gitlab_opener(*handlers):
        assert not any(isinstance(handler, transport.HTTPSHandler) for handler in handlers)
        if use_ca:
            with pytest.raises(ssl.SSLCertVerificationError):
                memory_handshake(ssl.create_default_context(), server)
        assert dict(os.environ) == environment
        return GitLab()
    def cx_opener(*handlers):
        context = next(handler._context for handler in handlers if isinstance(handler, transport.HTTPSHandler))
        if use_ca:
            memory_handshake(context, server)
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        return CX()
    monkeypatch.setattr(gitlab, "build_opener", gitlab_opener)
    monkeypatch.setattr(transport, "build_opener", cx_opener)
    def run(*args):
        return delivery.run_once(*args, sleep=lambda _seconds: None)
    monkeypatch.setattr(cli, "run_once", run)
    assert cli.main(["init", "--config", str(path)]) == 0 and requests == []
    assert cli.main(["collect", "--config", str(path)]) == 0
    assert [r.method for r in requests] == ["GET", "GET", "GET", "POST", "POST"]
    state = json.loads((spool / "delivery.json").read_text())
    assert state["next_sequence"] == 2 and state["pending"] is None
    assert len(snapshot["runners"]) == 1 and len(snapshot["targets"]) == 1
    assert "synthetic" not in json.dumps(snapshot) + json.dumps(state)
    assert dict(os.environ) == environment


def test_empty_inventory_is_complete_not_failure(monkeypatch):
    monkeypatch.setattr(Client, "inventory", lambda _self: [])
    value, calls = collect()
    assert value["targets"][0]["inventory"]["data"] == [] and value["runners"] == []
    assert calls == []


def test_surrogate_response_text_is_observation_failure():
    with pytest.raises(gitlab.ObservationError, match="invalid_response"):
        gitlab.runner_record(summary(description="\ud800"))
