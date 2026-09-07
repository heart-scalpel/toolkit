import copy
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application import create_app
from app.config import Settings
from app.database import create_database_engine, migrate
from app.manage import backup_database
from app.models import LoginSession, User
from app.security import COOKIE_NAME, token_hash
from app.validation import empty_workspace

ADMIN_PASSWORD = "test-admin-password-2026"
MEMBER_PASSWORD = "test-member-password-2026"
WRITE_HEADERS = {"X-Collector-Request": "1", "Origin": "http://testserver"}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path,
        public_origin="http://testserver",
        cookie_secure=False,
        bootstrap_admin_password=SecretStr(ADMIN_PASSWORD),
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def login(client, username="admin", password=ADMIN_PASSWORD):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}, headers=WRITE_HEADERS
    )
    assert response.status_code == 200, response.text
    result = response.json()
    return result, {**WRITE_HEADERS, "X-CSRF-Token": result["csrf_token"]}


def create_member(client, headers, username="alice"):
    response = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "username": username,
            "display_name": username.title(),
            "password": MEMBER_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def workspace(question="测试问题"):
    state = empty_workspace()
    state["questions"] = [
        {
            "case_id": "S01-Q001",
            "id_prefix": "S01",
            "question": {
                "local_id": "Q001",
                "user_input": question,
                "user_profile": {"stage": None, "locale": "zh-CN", "baby_age_days": 30, "background": []},
                "source_ids": [],
                "pair_key": None,
                "changed_factor": None,
            },
        }
    ]
    state["reviews"] = [
        {
            "case_id": "S01-Q001",
            "safety": {"candidate_class": "general_health", "boundary_note": ""},
            "initial_assessment": "测试评估",
            "possible_consultation_response": "测试回复",
            "follow_ups": [],
        }
    ]
    return state


def put(client, auth, headers, state, revision=0, **extra):
    return client.put(
        "/api/workspace",
        headers=headers,
        json={
            "account_id": auth["user"]["id"],
            "revision": revision,
            "state": state,
            **extra,
        },
    )


def test_public_page_health_and_private_endpoints(client):
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert "进入你的工作空间" in page.text
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert page.headers["Cache-Control"] == "no-store"
    for path in ["/api/auth/me", "/api/workspace", "/api/admin/users"]:
        assert client.get(path).status_code == 401
    for path in ["/.env", "/backend/data/collector.db", "/backend/app/main.py"]:
        assert client.get(path).status_code == 404


def test_login_hashing_cookie_and_logout(client):
    auth, headers = login(client)
    token = client.cookies.get(COOKIE_NAME)
    assert auth["user"]["is_admin"]
    assert "password" not in json.dumps(auth)
    with Session(client.app.state.engine) as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert ADMIN_PASSWORD not in user.password_hash
        assert db.get(LoginSession, token_hash(token)) is not None
        assert db.get(LoginSession, token) is None
    assert client.post("/api/auth/logout", headers=headers, json={}).status_code == 200
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/workspace").status_code == 401


def test_personal_data_same_case_id_and_admin_isolation(client):
    admin, admin_headers = login(client)
    create_member(client, admin_headers)
    create_member(client, admin_headers, "bob")
    alice, alice_headers = login(client, "ALICE", MEMBER_PASSWORD)
    assert client.get("/api/workspace").json()["state"] == empty_workspace()
    assert put(client, alice, alice_headers, workspace("Alice 的材料")).status_code == 200
    bob, bob_headers = login(client, "bob", MEMBER_PASSWORD)
    assert client.get("/api/workspace").json()["state"] == empty_workspace()
    assert put(client, bob, bob_headers, workspace("Bob 的材料")).status_code == 200
    # Client-supplied ownership cannot redirect a write.
    assert put(client, bob, bob_headers, workspace("越权"), account_id=alice["user"]["id"]).status_code == 409
    login(client)
    assert client.get("/api/workspace").json()["state"] == empty_workspace()
    login(client, "alice", MEMBER_PASSWORD)
    assert client.get("/api/workspace").json()["state"] == workspace("Alice 的材料")


def test_optimistic_lock_prevents_old_tab_overwrite(client):
    auth, headers = login(client)
    assert put(client, auth, headers, workspace("新版")).json()["revision"] == 1
    assert put(client, auth, headers, workspace("旧窗口")).status_code == 409
    assert client.get("/api/workspace").json()["state"] == workspace("新版")
    assert put(client, auth, headers, empty_workspace(), revision=1).status_code == 200
    assert client.get("/api/workspace").json()["revision"] == 2


@pytest.mark.parametrize("corruption", ["prefix", "schema", "duplicate", "review", "owner", "version"])
def test_invalid_backups_leave_saved_state_untouched(client, corruption):
    auth, headers = login(client)
    assert put(client, auth, headers, workspace()).status_code == 200
    bad = copy.deepcopy(workspace())
    if corruption == "prefix":
        bad["questions"][0]["case_id"] = "someone-else"
    elif corruption == "schema":
        bad["questions"][0]["question"]["user_profile"]["baby_age_days"] = -1
    elif corruption == "duplicate":
        bad["questions"].append(copy.deepcopy(bad["questions"][0]))
    elif corruption == "review":
        bad["reviews"][0]["safety"]["candidate_class"] = "invented"
    elif corruption == "owner":
        bad["user_id"] = "other-user"
    else:
        bad["version"] = True
    assert put(client, auth, headers, bad, revision=1).status_code == 422
    saved = client.get("/api/workspace").json()
    assert saved["revision"] == 1
    assert saved["state"] == workspace()


def test_orphan_reviews_and_missing_reviews_can_be_saved(client):
    auth, headers = login(client)
    orphan = workspace()
    orphan["questions"] = []
    assert put(client, auth, headers, orphan).status_code == 200
    missing = workspace()
    missing["reviews"] = []
    assert put(client, auth, headers, missing, revision=1).status_code == 200


def test_csrf_origin_and_account_switch_protection(client):
    auth, headers = login(client)
    create_member(client, headers)
    data = {"account_id": auth["user"]["id"], "revision": 0, "state": workspace()}
    assert client.put("/api/workspace", json=data).status_code == 403
    assert client.put("/api/workspace", headers=WRITE_HEADERS, json=data).status_code == 403
    assert (
        client.put(
            "/api/workspace", headers={**headers, "Origin": "https://evil.example"}, json=data
        ).status_code
        == 403
    )
    login(client, "alice", MEMBER_PASSWORD)
    assert client.put("/api/workspace", headers=headers, json=data).status_code == 403
    assert client.get("/api/workspace").json()["state"] == empty_workspace()


def test_member_cannot_manage_accounts_and_admin_cannot_be_disabled(client):
    admin, headers = login(client)
    member = create_member(client, headers)
    assert (
        client.patch(
            "/api/admin/users/" + admin["user"]["id"], headers=headers, json={"active": False}
        ).status_code
        == 400
    )
    _, headers = login(client, "alice", MEMBER_PASSWORD)
    assert client.get("/api/admin/users").status_code == 403
    assert (
        client.post(
            "/api/admin/users",
            headers=headers,
            json={"username": "mallory", "display_name": "M", "password": MEMBER_PASSWORD},
        ).status_code
        == 403
    )
    assert (
        client.patch("/api/admin/users/" + member["id"], headers=headers, json={"active": True}).status_code
        == 403
    )


def test_duplicate_and_short_password_do_not_leak_password(client):
    _, headers = login(client)
    create_member(client, headers)
    duplicate = client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "ALICE", "display_name": "Other", "password": MEMBER_PASSWORD},
    )
    assert duplicate.status_code == 409
    short = client.post(
        "/api/admin/users",
        headers=headers,
        json={"username": "short", "display_name": "Short", "password": "secret"},
    )
    assert short.status_code == 422
    assert "secret" not in short.text


def test_disable_reenable_and_reset_revoke_sessions_preserve_data(client):
    _, admin_headers = login(client)
    admin_token = client.cookies.get(COOKIE_NAME)
    member = create_member(client, admin_headers)
    client.cookies.clear()
    auth, member_headers = login(client, "alice", MEMBER_PASSWORD)
    member_token = client.cookies.get(COOKIE_NAME)
    assert put(client, auth, member_headers, workspace()).status_code == 200
    # Switching cookies simulates independent browsers, unlike logging in again.
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, admin_token)
    assert (
        client.patch(
            "/api/admin/users/" + member["id"], headers=admin_headers, json={"active": False}
        ).status_code
        == 200
    )
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, member_token)
    assert client.get("/api/workspace").status_code == 401
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, admin_token)
    assert (
        client.patch(
            "/api/admin/users/" + member["id"],
            headers=admin_headers,
            json={"active": True, "password": "new-member-password-2026"},
        ).status_code
        == 200
    )
    bad = client.post(
        "/api/auth/login", headers=WRITE_HEADERS, json={"username": "alice", "password": MEMBER_PASSWORD}
    )
    assert bad.status_code == 401
    login(client, "alice", "new-member-password-2026")
    assert client.get("/api/workspace").json()["state"] == workspace()


def test_password_change_rotates_session_and_survives_restart(client, settings):
    auth, headers = login(client)
    old_token = client.cookies.get(COOKIE_NAME)
    assert put(client, auth, headers, workspace()).status_code == 200
    response = client.post(
        "/api/auth/password",
        headers=headers,
        json={"current_password": ADMIN_PASSWORD, "new_password": "new-admin-password-2026"},
    )
    assert response.status_code == 200
    assert response.json()["csrf_token"] != headers["X-CSRF-Token"]
    new_token = client.cookies.get(COOKIE_NAME)
    assert new_token != old_token
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(COOKIE_NAME, old_token)
        assert restarted.get("/api/workspace").status_code == 401
        restarted.cookies.set(COOKIE_NAME, new_token)
        assert restarted.get("/api/workspace").json()["state"] == workspace()
        # Bootstrap never resets an existing administrator's password.
        login(restarted, "admin", "new-admin-password-2026")


def test_expired_sessions_are_rejected(client):
    login(client)
    token = client.cookies.get(COOKIE_NAME)
    with Session(client.app.state.engine) as db:
        db.get(LoginSession, token_hash(token)).expires_at = int(time.time()) - 1
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limited(client):
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/login", headers=WRITE_HEADERS, json={"username": "admin", "password": "bad"}
            ).status_code
            == 401
        )
    response = client.post(
        "/api/auth/login", headers=WRITE_HEADERS, json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"


def test_size_limit_is_enforced(settings):
    settings.max_body_bytes = 1024
    with TestClient(create_app(settings)) as client:
        auth, headers = login(client)
        assert put(client, auth, headers, workspace("x" * 2048)).status_code == 413
        assert client.get("/api/workspace").json()["revision"] == 0


def test_production_https_uses_secure_cookie(settings):
    settings.environment = "production"
    settings.public_origin = "https://testserver"
    settings.cookie_secure = True
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        response = client.post(
            "/api/auth/login",
            headers={**WRITE_HEADERS, "Origin": "https://testserver"},
            json={"username": "admin", "password": ADMIN_PASSWORD},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_production_internal_http_login_and_save(settings):
    origin = "http://172.17.23.51:3722"
    settings = Settings(
        _env_file=None,
        environment="production",
        data_dir=settings.data_dir,
        public_origin=origin,
        cookie_secure=False,
        bootstrap_admin_password=SecretStr(ADMIN_PASSWORD),
    )
    with TestClient(create_app(settings), base_url=origin) as client:
        response = client.post(
            "/api/auth/login",
            headers={**WRITE_HEADERS, "Origin": origin},
            json={"username": "admin", "password": ADMIN_PASSWORD},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "secure" not in cookie and "httponly" in cookie and "samesite=lax" in cookie
        auth = response.json()
        headers = {**WRITE_HEADERS, "Origin": origin, "X-CSRF-Token": auth["csrf_token"]}
        assert client.get("/api/auth/me").json()["user"]["username"] == "admin"
        assert put(client, auth, headers, workspace()).status_code == 200
        assert client.get("/api/workspace").json()["state"] == workspace()
        assert (
            client.put(
                "/api/workspace",
                headers={**headers, "Origin": "http://172.17.23.51:9999"},
                json={"account_id": auth["user"]["id"], "revision": 1, "state": empty_workspace()},
            ).status_code
            == 403
        )
        assert client.post("/api/auth/logout", headers=headers, json={}).status_code == 200
        assert client.get("/api/workspace").status_code == 401


@pytest.mark.parametrize("scheme,secure", [("http", False), ("https", True)])
def test_cookie_security_follows_origin_and_rejects_mismatch(scheme, secure):
    settings = Settings(_env_file=None, environment="production", public_origin=f"{scheme}://example.com")
    assert settings.cookie_secure is secure
    with pytest.raises(ValidationError, match="COLLECTOR_COOKIE_SECURE"):
        Settings(
            _env_file=None,
            environment="production",
            public_origin=f"{scheme}://example.com",
            cookie_secure=not secure,
        )


def test_empty_database_starts_without_bootstrap_password(settings):
    settings.bootstrap_admin_password = None
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        with Session(client.app.state.engine) as db:
            assert db.scalar(select(User)) is None


def test_migration_and_online_backup(client, settings, tmp_path):
    auth, headers = login(client)
    assert put(client, auth, headers, workspace()).status_code == 200
    engine = create_database_engine(settings)
    migrate(engine)
    migrate(engine)
    engine.dispose()
    destination = tmp_path / "backup.db"
    backup_database(settings.database_path, destination)
    with sqlite3.connect(destination) as db:
        state, revision = db.execute("SELECT state, revision FROM workspaces").fetchone()
        assert json.loads(state) == workspace()
        assert revision == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260907_0002"
    with pytest.raises(ValueError, match="已存在"):
        backup_database(settings.database_path, destination)
