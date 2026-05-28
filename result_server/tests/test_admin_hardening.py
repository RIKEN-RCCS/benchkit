"""Tests for admin route hardening."""

import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_support import build_portal_route_app, install_portal_test_stubs

install_portal_test_stubs()

from utils.admin_policy import is_valid_email


class _Store:
    def __init__(self):
        self._users = {}
        self.invitations = []

    def create_user(self, email, totp_secret, affiliations):
        self._users[email] = {
            "email": email,
            "totp_secret": totp_secret,
            "affiliations": list(affiliations),
        }

    def get_user(self, email):
        return self._users.get(email)

    def delete_user(self, email):
        return self._users.pop(email, None) is not None

    def list_users(self):
        return list(self._users.values())

    def update_affiliations(self, email, affiliations):
        if email in self._users:
            self._users[email]["affiliations"] = list(affiliations)
            return True
        return False

    def user_exists(self, email):
        return email in self._users

    def get_affiliations(self, email):
        user = self._users.get(email)
        return user["affiliations"] if user else []

    def has_totp_secret(self, email):
        user = self._users.get(email)
        return bool(user and user.get("totp_secret"))

    def clear_totp_secret(self, email):
        if email in self._users:
            self._users[email]["totp_secret"] = ""
            return True
        return False

    def create_invitation(self, email, affiliations):
        self.invitations.append({"email": email, "affiliations": list(affiliations)})
        return "token-1"


def _admin_app(store=None, allowed_affiliations=frozenset({"admin", "dev", "riken"})):
    received = tempfile.mkdtemp()
    estimated = tempfile.mkdtemp()
    app = build_portal_route_app(
        templates_dir=os.path.join(os.path.dirname(__file__), "..", "templates"),
        received_dir=received,
        estimated_dir=estimated,
        user_store=store or _Store(),
    )
    if allowed_affiliations is not None:
        app.config["ALLOWED_AFFILIATIONS"] = allowed_affiliations
    return app, (received, estimated)


def _login_admin(client, email="admin@test.com"):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = email
        sess["user_affiliations"] = ["admin"]


def _cleanup(paths):
    for path in paths:
        shutil.rmtree(path)


@pytest.mark.parametrize(
    "email",
    [
        "user@example.com",
        "first.last@example.co.jp",
        "u+tag@example.com",
        "user_name-123@a-b.example",
    ],
)
def test_is_valid_email_accepts_well_formed_addresses(email):
    assert is_valid_email(email)


@pytest.mark.parametrize(
    "email",
    [
        "evil';alert(1);//@x.com",
        'user"@x.com',
        "<script>@x.com",
        "user @x.com",
        "user\nname@x.com",
        "",
        "  ",
        "no-at-sign",
        "two@@at.com",
        "user@.tld",
        ("a" * 260) + "@x.com",
    ],
)
def test_is_valid_email_rejects_dangerous_or_malformed_addresses(email):
    assert not is_valid_email(email)


def test_add_user_rejects_unknown_affiliation():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/users/add",
                data={"email": "new@test.com", "affiliations": "dev,../../bad"},
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert not store.user_exists("new@test.com")
        assert store.invitations == []
        assert b"Invalid affiliations" in resp.data
    finally:
        _cleanup(temp_dirs)


def test_add_user_rejects_xss_email_payload():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/users/add",
                data={"email": "evil';alert(1);//@x.com", "affiliations": "dev"},
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert not store.user_exists("evil';alert(1);//@x.com")
        assert store.invitations == []
        assert b"Invalid email address" in resp.data
    finally:
        _cleanup(temp_dirs)


def test_update_affiliations_rejects_unknown_affiliation():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    store.create_user("user@test.com", "SECRET2", ["dev"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/users/user@test.com/affiliations",
                data={"affiliations": "riken,invalid/value"},
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert store.get_affiliations("user@test.com") == ["dev"]
        assert b"Invalid affiliations" in resp.data
    finally:
        _cleanup(temp_dirs)


def test_update_affiliations_accepts_allowed_deduplicated_values():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    store.create_user("user@test.com", "SECRET2", ["dev"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/users/user@test.com/affiliations",
                data={"affiliations": "riken, dev, riken"},
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert store.get_affiliations("user@test.com") == ["riken", "dev"]
    finally:
        _cleanup(temp_dirs)


def test_add_user_accepts_arbitrary_safe_affiliation_without_allowlist():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    app, temp_dirs = _admin_app(store, allowed_affiliations=None)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/users/add",
                data={
                    "email": "new+portal@test.example",
                    "affiliations": "project+gpu@riken.example, team name #1",
                },
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert store.invitations == [
            {
                "email": "new+portal@test.example",
                "affiliations": ["project+gpu@riken.example", "team name #1"],
            }
        ]
        assert b"Invalid affiliations" not in resp.data
    finally:
        _cleanup(temp_dirs)


def test_admin_users_template_does_not_embed_email_in_inline_submit_handler():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    store.create_user("evil';alert(1);x='@x.com", "SECRET2", ["dev"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.get("/admin/users")

        html = resp.data.decode()
        assert resp.status_code == 200
        assert "onsubmit=" not in html
        assert "data-confirm-message" in html
        assert "evil';alert(1);x='" not in html
    finally:
        _cleanup(temp_dirs)


def test_admin_email_routes_reject_path_segments():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post("/admin/users/admin@test.com/extra/delete")

        assert resp.status_code == 404
    finally:
        _cleanup(temp_dirs)


def test_delete_only_admin_is_rejected():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client, email="operator@test.com")
            resp = client.post(
                "/admin/users/admin@test.com/delete",
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert store.user_exists("admin@test.com")
        assert b"only admin user" in resp.data
    finally:
        _cleanup(temp_dirs)


def test_delete_one_of_multiple_admins_is_allowed():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    store.create_user("second-admin@test.com", "SECRET2", ["admin"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/users/second-admin@test.com/delete",
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert not store.user_exists("second-admin@test.com")
        assert store.user_exists("admin@test.com")
    finally:
        _cleanup(temp_dirs)


def test_update_cannot_remove_admin_from_only_admin_user():
    store = _Store()
    store.create_user("admin@test.com", "SECRET", ["admin"])
    app, temp_dirs = _admin_app(store)
    try:
        with app.test_client() as client:
            _login_admin(client)
            resp = client.post(
                "/admin/users/admin@test.com/affiliations",
                data={"affiliations": "dev"},
                follow_redirects=True,
            )

        assert resp.status_code == 200
        assert store.get_affiliations("admin@test.com") == ["admin"]
        assert b"only admin user" in resp.data
    finally:
        _cleanup(temp_dirs)


def test_create_admin_rejects_invalid_affiliation_before_redis(monkeypatch, capsys):
    import create_admin

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_admin.py",
            "admin@test.com",
            "--affiliations",
            "admin,../../bad",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        create_admin.main()

    assert excinfo.value.code == 2
    assert "Invalid affiliations" in capsys.readouterr().err
