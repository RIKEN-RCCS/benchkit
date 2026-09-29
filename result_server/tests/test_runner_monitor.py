"""Runner reads, credential boundaries and observation semantics."""

from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import runner_monitor as monitor  # noqa: E402
from utils.runner_observations import collect, presentation, relative_age  # noqa: E402
from utils.budget_runner_choices import runner_choices  # noqa: E402


NOW = "2026-01-01T12:00:00+00:00"
LATER = "2026-01-01T12:05:00+00:00"


def target(name="first", server="https://gitlab.example.org"):
    return monitor.MonitorTarget(name, server, "group/" + name, Path("/example/credential"))


def row(runner_id=7, **overrides):
    return {"id": runner_id, "description": "Example runner", "runner_type": "instance_type",
            "status": "online", "paused": False, **overrides}


class FakeClient:
    calls = []
    inventory_errors = set()
    detail_errors = set()
    manager_errors = set()
    rows = [row()]

    def __init__(self, target):
        self.target = target

    def inventory(self):
        self.calls.append((self.target.id, "inventory"))
        if self.target.id in self.inventory_errors:
            raise monitor.ObservationError("http_403")
        return deepcopy(self.rows)

    def detail(self, runner_id):
        self.calls.append((self.target.id, "detail", runner_id))
        if self.target.id in self.detail_errors:
            raise monitor.ObservationError("http_403")
        return row(runner_id, tag_list=["example-run"], contacted_at=NOW, access_level="not_protected")

    def managers(self, runner_id):
        self.calls.append((self.target.id, "managers", runner_id))
        if self.target.id in self.manager_errors:
            raise monitor.ObservationError("http_403")
        return [{"id": 3, "system_id": "example-manager", "status": "online", "version": "example",
                 "platform": "linux", "architecture": "arm64", "contacted_at": NOW}]


@pytest.fixture(autouse=True)
def reset_fake():
    FakeClient.calls = []
    FakeClient.inventory_errors = set()
    FakeClient.detail_errors = set()
    FakeClient.manager_errors = set()
    FakeClient.rows = [row()]


def choice_connection(**overrides):
    return dict(dict(id="connection", available=True, server_url="https://gitlab.example.org",
                     project_path="group/first", target_id="first"), **overrides)


@pytest.mark.parametrize("change", [
    {"server_url": "https://other.example.org"}, {"project_path": "group/other"},
    {"target_id": "second"}, {"available": False},
])
def test_budget_runner_choices_do_not_cross_connection_identity(change):
    snapshot = collect([target(), target("second")], {}, client_factory=FakeClient, now=NOW)
    choices = runner_choices([choice_connection(**change)], snapshot, now=datetime.fromisoformat(NOW))
    assert choices["connection"] == {"state": "not_observed", "runners": []}


def test_budget_runner_choices_match_manual_connections_and_deduplicate_shared_runners():
    other = monitor.MonitorTarget("alias", target().server, target().project, target().token_file)
    snapshot = collect([target(), other], {}, client_factory=FakeClient, now=NOW)
    runner = next(iter(snapshot["runners"].values()))
    runner["detail"]["data"].update(paused=True, status="offline", access_level="ref_protected")
    choices = runner_choices([choice_connection(target_id="", server_url="https://GITLAB.example.org/")],
                             snapshot, now=datetime.fromisoformat(NOW))["connection"]
    assert choices["state"] == "current"
    assert len(choices["runners"]) == 1
    selected = choices["runners"][0]
    assert selected["fresh"] and selected["paused"] and selected["protected"]
    assert selected["heartbeat"] == "offline"
    assert selected["tags"] == ["example-run"]
    assert "managers" not in selected and "server" not in selected


@pytest.mark.parametrize("failure", ["inventory", "detail", "expired"])
def test_budget_runner_choices_preserve_but_disable_unverified_tags(failure):
    snapshot = collect([target(), target("second")], {}, client_factory=FakeClient, now=NOW)
    if failure == "inventory":
        snapshot["targets"]["first"]["inventory"]["error"] = "http_403"
    elif failure == "detail":
        next(iter(snapshot["runners"].values()))["detail"]["error"] = "http_403"
    now = datetime.fromisoformat("2026-01-02T12:00:00+00:00" if failure == "expired" else NOW)
    selected = runner_choices([choice_connection()], snapshot, now=now)["connection"]["runners"][0]
    assert selected["tags"] == ["example-run"]
    assert not selected["fresh"] and selected["heartbeat"] == "unknown"


def test_shared_runner_is_observed_once_but_projects_stay_distinct():
    snapshot = collect([target(), target("second")], {}, client_factory=FakeClient, now=NOW)
    assert len(snapshot["runners"]) == 1
    runner = next(iter(snapshot["runners"].values()))
    assert runner["targets"] == ["first", "second"]
    assert sum(call[1] == "detail" for call in FakeClient.calls) == 1
    assert sum(call[1] == "managers" for call in FakeClient.calls) == 1
    assert sum(call[1] == "inventory" for call in FakeClient.calls) == 2


def test_same_id_on_different_servers_is_not_shared():
    snapshot = collect([target(), target("second", "https://other.example.org")], {}, client_factory=FakeClient, now=NOW)
    assert len(snapshot["runners"]) == 2


def test_failed_inventory_retains_previous_relationships_without_current_heartbeat():
    before = collect([target()], {}, client_factory=FakeClient, now=NOW)
    FakeClient.inventory_errors = {"first"}
    after = collect([target()], before, client_factory=FakeClient, now=LATER)
    observation = after["targets"]["first"]["inventory"]
    assert observation["data"] == before["targets"]["first"]["inventory"]["data"]
    assert observation["last_success_at"] == NOW
    assert observation["attempted_at"] == LATER
    page = presentation(after, now=datetime.fromisoformat(LATER))
    assert page["targets"][0]["state"] == "unavailable"
    assert page["runners"][0]["heartbeat"] == "unknown"
    assert page["runners"][0]["record"]["status"] == "online"
    assert before["targets"]["first"]["inventory"]["error"] == ""


def test_successful_empty_inventory_removes_relationship_and_orphan():
    before = collect([target()], {}, client_factory=FakeClient, now=NOW)
    FakeClient.rows = []
    after = collect([target()], before, client_factory=FakeClient, now=LATER)
    assert after["runners"] == {}
    assert after["targets"]["first"]["inventory"]["data"] == []
    assert after["targets"]["first"]["inventory"]["error"] == ""


def test_removed_or_changed_target_does_not_reuse_old_project_data():
    before = collect([target()], {}, client_factory=FakeClient, now=NOW)
    assert collect([], before, client_factory=FakeClient, now=LATER)["runners"] == {}
    FakeClient.inventory_errors = {"first"}
    after = collect([target(server="https://other.example.org")], before, client_factory=FakeClient, now=LATER)
    assert after["runners"] == {}
    assert "data" not in after["targets"]["first"]["inventory"]


def test_manager_failure_is_separate_and_shared_credential_can_retry_details():
    FakeClient.detail_errors = {"first"}
    FakeClient.manager_errors = {"first", "second"}
    snapshot = collect([target(), target("second")], {}, client_factory=FakeClient, now=NOW)
    page = presentation(snapshot, now=datetime.fromisoformat(NOW))
    assert page["runners"][0]["heartbeat"] == "online"
    assert page["runners"][0]["manager_state"] == "unavailable"
    assert ("second", "detail", 7) in FakeClient.calls


def test_expired_observations_do_not_claim_runner_is_online():
    snapshot = collect([target()], {}, client_factory=FakeClient, now=NOW)
    page = presentation(snapshot, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert page["runners"][0]["state"] == "expired"
    assert page["runners"][0]["heartbeat"] == "unknown"
    assert page["targets"][0]["state"] == "expired"


@pytest.mark.parametrize("value, expected", [(None, "Never"), (NOW, "Just now"),
    ("2026-01-01T11:57:00+00:00", "3 min ago"), ("2026-01-01T10:00:00+00:00", "2 h ago"),
    ("2025-12-31T12:00:00+00:00", "1 day ago"), (LATER, "Clock mismatch")])
def test_relative_age_keeps_missing_and_future_times_distinct(value, expected):
    assert relative_age(value, datetime.fromisoformat(NOW)) == expected


def test_monitor_config_reuses_existing_targets_without_trigger_credentials():
    env = {"RESULT_SERVER_GITLAB_TARGETS": "example=gitlab.example.org/group/project",
           "RESULT_SERVER_RUNNER_MONITOR_TARGETS": json.dumps({"example": {
               "token_file": "/example/read.token", "runner_types": ["project_type"]}}),
           "RESULT_SERVER_GITLAB_TRIGGER_TOKEN_EXAMPLE": "not-a-monitor-credential"}
    result = monitor.configured_monitor_targets(env)
    assert result[0].server == "https://gitlab.example.org"
    assert result[0].project == "group/project"
    assert result[0].runner_types == {"project_type"}
    assert "read.token" not in repr(result[0])
    env.pop("RESULT_SERVER_RUNNER_MONITOR_TARGETS")
    with pytest.raises(monitor.ObservationError, match="invalid_configuration"):
        monitor.configured_monitor_targets(env)


@pytest.mark.parametrize("repo", ["https://gitlab.example.org/a/b", "user:pass@gitlab.example.org/a/b",
                                 "gitlab.example.org/a/../b", "gitlab.example.org/a/b?token=secret"])
def test_unsafe_monitor_destination_is_rejected(repo):
    with pytest.raises(monitor.ObservationError, match="invalid_configuration"):
        monitor.configured_monitor_targets({"RESULT_SERVER_GITLAB_TARGETS": "example=" + repo,
            "RESULT_SERVER_RUNNER_MONITOR_TARGETS": '{"example":{"token_file":"/example/read.token"}}'})


@pytest.fixture
def credential(tmp_path):
    directory = tmp_path / "credentials"
    directory.mkdir(mode=0o700)
    path = directory / "read.token"
    path.write_text("fixture-monitor-credential", encoding="ascii")
    path.chmod(0o600)
    return path


def client(credential):
    return monitor.RunnerClient(monitor.MonitorTarget("example", "https://gitlab.example.org", "group/project", credential))


def test_credential_permissions_and_symlinks(credential):
    assert monitor.read_monitor_token(credential) == "fixture-monitor-credential"
    credential.chmod(0o644)
    with pytest.raises(monitor.ObservationError, match="credential_unavailable"):
        monitor.read_monitor_token(credential)
    credential.chmod(0o600)
    alias = credential.parent / "alias"
    alias.symlink_to(credential)
    with pytest.raises(monitor.ObservationError):
        monitor.read_monitor_token(alias)


def test_transport_is_get_only_no_redirect_and_drops_private_fields(credential, monkeypatch):
    calls = []
    class Response(BytesIO):
        headers = {"X-Next-Page": ""}
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return Response(json.dumps([row(description="fixture-monitor-credential", ip_address="private", token="private")]).encode())
    def opener(handler):
        assert handler.redirect_request(None, None, 302, None, {}, "https://other.example.org") is None
        return Opener()
    monkeypatch.setattr(monitor, "build_opener", opener)
    result = client(credential).inventory()
    assert calls[0].method == "GET"
    assert "group%2Fproject" in calls[0].full_url
    assert "fixture-monitor-credential" not in calls[0].full_url
    assert result[0]["description"] == "[REDACTED]"
    assert "ip_address" not in result[0] and "token" not in result[0]


def test_http_error_does_not_include_body_or_url(credential, monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise HTTPError("https://private.example.org", 403, "secret", {}, BytesIO(b"secret"))
    monkeypatch.setattr(monitor, "build_opener", lambda _: Opener())
    with pytest.raises(monitor.ObservationError) as error:
        client(credential).inventory()
    assert str(error.value) == "http_403"


def test_pagination_is_complete_or_fails(credential, monkeypatch):
    reader = client(credential)
    pages = iter([([row()], 2), ([row(8)], None)])
    monkeypatch.setattr(reader, "_get", lambda *args: next(pages))
    assert [item["id"] for item in reader.inventory()] == [7, 8]
    monkeypatch.setattr(reader, "_get", lambda *args: ([row()], 1))
    with pytest.raises(monitor.ObservationError, match="pagination_limit"):
        reader.inventory()


@pytest.mark.parametrize("invalid", [None, {}, [None], [row(id=True)], [row(paused="false")], [row(), row()]])
def test_malformed_inventory_is_not_an_empty_success(credential, monkeypatch, invalid):
    reader = client(credential)
    monkeypatch.setattr(reader, "_get", lambda *args: (invalid, None))
    with pytest.raises(monitor.ObservationError):
        reader.inventory()


def test_unknown_heartbeat_is_not_inferred_from_paused():
    assert monitor.runner_record(row(status="paused", paused=True))["status"] == "unknown"


def test_detail_and_manager_projection_excludes_host_addresses(credential, monkeypatch):
    reader = client(credential)
    monkeypatch.setattr(reader, "_get", lambda *args: (row(tag_list=["build"], contacted_at=NOW,
                        ip_address="private", projects=[{"secret": "private"}], run_untagged=False), None))
    detail = reader.detail(7)
    assert detail["tag_list"] == ["build"]
    assert "projects" not in detail and "ip_address" not in detail
    monkeypatch.setattr(reader, "_get", lambda *args: ([{"id": 1, "status": "online", "ip_address": "private"}], None))
    assert "ip_address" not in reader.managers(7)[0]
