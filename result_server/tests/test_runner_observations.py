"""SQLCipher persistence and operator-only observation views."""

import fcntl
from html.parser import HTMLParser
from pathlib import Path
import sys

import pytest

pytest.importorskip("sqlcipher3")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.encrypted_sqlite import EncryptedDatabaseError, generate_key  # noqa: E402
from utils.runner_observations import RunnerObservations, collect  # noqa: E402
from test_runner_monitor import FakeClient, NOW, target, reset_fake  # noqa: E402, F401
from test_support import build_portal_route_app, install_portal_test_stubs  # noqa: E402

install_portal_test_stubs()
from routes.runner_monitor import register_runner_monitor  # noqa: E402
from utils.portal_access import register_public_portal_guard, classify_endpoint  # noqa: E402
from runner_monitor import main  # noqa: E402


@pytest.fixture
def observations(tmp_path):
    for name in ("db", "keys", "backup"):
        (tmp_path / name).mkdir(mode=0o700)
    key = tmp_path / "keys" / "read.key"
    generate_key(key)
    store = RunnerObservations(tmp_path / "db" / "observations.db", key)
    store.initialize()
    store.save(collect([target(), target("second")], {}, client_factory=FakeClient, now=NOW))
    return store


def test_encrypted_snapshot_backup_and_wrong_key(observations, tmp_path):
    data = observations.storage.path.read_bytes()
    assert not data.startswith(b"SQLite format 3")
    assert b"Example runner" not in data
    assert observations.read()["targets"].keys() == {"first", "second"}
    backup = tmp_path / "backup" / "snapshot.db"
    observations.storage.backup(backup)
    assert RunnerObservations(backup, observations.storage.key_file).read() == observations.read()
    wrong = tmp_path / "keys" / "wrong.key"
    generate_key(wrong)
    with pytest.raises(EncryptedDatabaseError):
        RunnerObservations(observations.storage.path, wrong).read()
    with pytest.raises(EncryptedDatabaseError):
        observations.initialize()


def test_missing_database_is_not_created(tmp_path, observations):
    path = tmp_path / "db" / "missing.db"
    with pytest.raises(EncryptedDatabaseError):
        RunnerObservations(path, observations.storage.key_file).read()
    assert not path.exists()


def test_collector_lock_prevents_overlapping_writes(observations, monkeypatch, capsys):
    monkeypatch.setenv("RESULT_SERVER_GITLAB_TARGETS", "example=gitlab.example.org/group/project")
    monkeypatch.setenv("RESULT_SERVER_RUNNER_MONITOR_TARGETS", '{"example":{"token_file":"/example/read.token"}}')
    with observations.storage.path.open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert main(["collect", "--database", str(observations.storage.path),
                     "--key-file", str(observations.storage.key_file)]) == 0
    assert "already running" in capsys.readouterr().out


class Users:
    exists = True
    admin = True
    unavailable = False

    def user_exists(self, _principal):
        if self.unavailable:
            raise RuntimeError("private-backend-information")
        return self.exists

    def get_affiliations(self, _principal):
        return ["admin"] if self.admin else []


@pytest.fixture
def portal(observations, tmp_path, monkeypatch):
    users = Users()
    monkeypatch.setenv("RESULT_SERVER_RUNNER_MONITOR_DB_PATH", str(observations.storage.path))
    monkeypatch.setenv("RESULT_SERVER_RUNNER_MONITOR_KEY_FILE", str(observations.storage.key_file))
    app = build_portal_route_app(templates_dir=str(Path(__file__).resolve().parents[1] / "templates"),
                                received_dir=str(tmp_path / "received"), estimated_dir=str(tmp_path / "estimated"),
                                user_store=users)
    register_runner_monitor(app)
    register_public_portal_guard(app)
    return app, users


def login(client):
    with client.session_transaction() as session:
        session.update(authenticated=True, user_email="admin@example.org", user_affiliations=["admin"])


def test_routes_require_live_administrator_and_hide_public_surface(portal):
    app, users = portal
    client = app.test_client()
    assert classify_endpoint("runner_monitor.index") == "operator"
    assert client.get("/runners/").status_code == 302
    login(client)
    response = client.get("/runners/")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_data(as_text=True).count('class="runner-name"') == 1
    users.admin = False
    assert client.get("/runners/").status_code == 403
    users.admin = True
    users.exists = False
    assert client.get("/runners/").status_code == 403
    users.unavailable = True
    response = client.get("/runners/")
    assert response.status_code == 503
    assert b"private-backend" not in response.data
    app.config["PUBLIC_PORTAL_MODE"] = True
    assert client.get("/runners/").status_code == 404


def test_filters_escaping_and_no_gitlab_requests_on_view(portal, observations, monkeypatch):
    from utils.runner_monitor import RunnerClient
    monkeypatch.setattr(RunnerClient, "_get", lambda *args: pytest.fail("UI must not call GitLab"))
    snapshot = observations.read()
    next(iter(snapshot["runners"].values()))["detail"]["data"]["description"] = "<script>alert(1)</script>"
    observations.save(snapshot)
    app, _ = portal
    client = app.test_client()
    login(client)
    response = client.get("/runners/?target=second&q=example-run")
    assert response.status_code == 200
    assert b"&lt;script&gt;" in response.data
    assert b"<script>alert" not in response.data
    assert b"No runners match" in client.get("/runners/?target=missing").data
    assert b"No runners match" in client.get("/runners/?q=nonexistent").data
    assert client.post("/runners/").status_code == 405


def test_missing_store_is_generic_503_and_registration_does_not_open_database(portal, tmp_path):
    app, _ = portal
    app.config["RUNNER_MONITOR_DB_PATH"] = str(tmp_path / "missing.db")
    client = app.test_client()
    login(client)
    response = client.get("/runners/")
    assert response.status_code == 503
    assert str(tmp_path) not in response.get_data(as_text=True)
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.parametrize("prefix", ["", "/preview/console"])
def test_runner_styles_are_embedded_without_relying_on_shared_static_routes(portal, tmp_path, prefix):
    class Styles(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_style = False
            self.css = []
            self.external = []

        def handle_starttag(self, tag, attrs):
            if tag == "style":
                self.in_style = True
            if tag == "link" and dict(attrs).get("rel") == "stylesheet":
                self.external.append(dict(attrs).get("href"))

        def handle_endtag(self, tag):
            if tag == "style":
                self.in_style = False

        def handle_data(self, data):
            if self.in_style:
                self.css.append(data)

    _app, users = portal
    app = build_portal_route_app(templates_dir=str(Path(__file__).resolve().parents[1] / "templates"),
                                received_dir=str(tmp_path / "received"), estimated_dir=str(tmp_path / "estimated"),
                                user_store=users)
    register_runner_monitor(app, prefix)
    client = app.test_client()
    login(client)
    response = client.get(prefix + "/runners/")
    assert response.status_code == 200
    parser = Styles()
    parser.feed(response.get_data(as_text=True))
    css = "".join(parser.css)
    assert ".runner-summary-grid" in css and "grid-template-columns" in css
    assert not parser.external


@pytest.mark.parametrize("error, expected", [("", "Out of date"), ("http_403", "Unavailable")])
def test_collapsed_rows_keep_observation_warnings_but_hide_investigation_fields(portal, observations, error, expected):
    class Summaries(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside = False
            self.text = []
            self.expanded = []

        def handle_starttag(self, tag, attrs):
            if tag == "summary":
                self.inside = True
            if tag == "details":
                self.expanded.append("open" in dict(attrs))

        def handle_endtag(self, tag):
            if tag == "summary":
                self.inside = False

        def handle_data(self, text):
            if self.inside:
                self.text.append(text)

    snapshot = observations.read()
    runner = next(iter(snapshot["runners"].values()))
    runner["detail"]["error"] = error
    runner["managers"]["error"] = "http_403"
    runner["detail"]["data"]["tag_list"] = ["tag-first", "tag-second", "tag-third"]
    observations.save(snapshot)
    app, _ = portal
    client = app.test_client()
    login(client)
    page = client.get("/runners/")
    parser = Summaries()
    parser.feed(page.get_data(as_text=True))
    summary = " ".join(parser.text)
    assert expected in summary
    assert "Managers: Unavailable" in summary
    assert "example-manager" not in summary
    assert "https://gitlab.example.org" not in summary
    assert NOW not in summary
    assert "tag-first" in summary and "tag-third" not in summary
    assert b"tag-third" in page.data and b"example-manager" in page.data
    assert parser.expanded and not any(parser.expanded)
