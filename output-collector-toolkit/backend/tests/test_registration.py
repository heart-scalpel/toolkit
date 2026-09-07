import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.application import create_app
from app.config import BACKEND_ROOT, Settings
from app.database import create_database_engine, migrate
from app.models import LoginSession, User, Workspace
from app.security import COOKIE_NAME
from app.validation import empty_workspace

PASSWORD = "root1234"
HEADERS = {"X-Collector-Request": "1", "Origin": "http://testserver"}


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None, environment="test", data_dir=tmp_path, public_origin="http://testserver"
    )
    with TestClient(create_app(settings)) as client:
        yield client


def register(client, email="person@unverified.invalid", **extra):
    return client.post(
        "/api/auth/register", headers=HEADERS, json={"email": email, "password": PASSWORD, **extra}
    )


def sign_in(client, email, password=PASSWORD):
    return client.post("/api/auth/login", headers=HEADERS, json={"email": email, "password": password})


def test_email_signup_immediately_logs_in_without_verification(client):
    response = register(client, "  Person+work@Unverified.invalid  ")
    assert response.status_code == 201
    auth = response.json()
    user = auth["user"]
    assert user["email"] == "person+work@unverified.invalid"
    assert user["is_admin"] is False and user["active"] is True
    assert client.get("/api/auth/me").json()["user"]["id"] == user["id"]
    assert client.get("/api/workspace").json()["state"] == empty_workspace()
    assert "httponly" in response.headers["set-cookie"].lower()
    assert PASSWORD not in response.text
    headers = {**HEADERS, "X-CSRF-Token": auth["csrf_token"]}
    assert client.post("/api/auth/logout", headers=headers, json={}).status_code == 200
    assert sign_in(client, "PERSON+WORK@unverified.invalid").json()["user"]["id"] == user["id"]
    assert client.get("/api/admin/users").status_code == 403


def test_duplicate_email_does_not_reset_account_or_password(client):
    first = register(client).json()
    headers = {**HEADERS, "X-CSRF-Token": first["csrf_token"]}
    snapshot = empty_workspace()
    assert (
        client.put(
            "/api/workspace",
            headers=headers,
            json={
                "account_id": first["user"]["id"],
                "revision": 0,
                "state": snapshot,
            },
        ).status_code
        == 200
    )
    duplicate = client.post(
        "/api/auth/register",
        headers=HEADERS,
        json={
            "email": "PERSON@UNVERIFIED.INVALID",
            "password": "a-different-password",
        },
    )
    assert duplicate.status_code == 409
    assert client.get("/api/workspace").json()["revision"] == 1
    assert sign_in(client, "person@unverified.invalid", "a-different-password").status_code == 401
    assert sign_in(client, "person@unverified.invalid").json()["user"]["id"] == first["user"]["id"]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Workspace)) == 1


def test_two_registered_accounts_have_separate_workspaces_and_sessions(client):
    first = register(client, "first@example.com").json()
    first_token = client.cookies.get(COOKIE_NAME)
    headers = {**HEADERS, "X-CSRF-Token": first["csrf_token"]}
    assert (
        client.put(
            "/api/workspace",
            headers=headers,
            json={
                "account_id": first["user"]["id"],
                "revision": 0,
                "state": empty_workspace(),
            },
        ).status_code
        == 200
    )
    second = register(client, "second@another.org").json()
    assert first["user"]["id"] != second["user"]["id"]
    saved = client.get("/api/workspace").json()
    assert saved["account_id"] == second["user"]["id"] and saved["revision"] == 0
    assert (
        client.put(
            "/api/workspace",
            headers={**HEADERS, "X-CSRF-Token": second["csrf_token"]},
            json={
                "account_id": first["user"]["id"],
                "revision": 1,
                "state": empty_workspace(),
            },
        ).status_code
        == 409
    )
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, first_token)
    assert client.get("/api/auth/me").status_code == 401
    assert sign_in(client, "first@example.com").status_code == 200
    assert client.get("/api/workspace").json()["revision"] == 1


def test_long_email_and_different_providers_are_supported(client):
    email = "a" * 60 + "@" + "b" * 60 + ".example"
    response = register(client, email)
    assert response.status_code == 201
    assert response.json()["user"]["email"] == email
    assert sign_in(client, email).status_code == 200


@pytest.mark.parametrize("email", ["not-an-email", "a@@example.com", "a b@example.com", "a@", "@example.com"])
def test_invalid_email_is_rejected_without_creating_an_account(client, email):
    assert register(client, email).status_code == 422
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(User)) is None


@pytest.mark.parametrize("password", ["", "secret" * 22])
def test_registration_cannot_set_privileges_or_skip_password_rules(client, password):
    assert register(client, is_admin=True).status_code == 422
    assert register(client, active=True).status_code == 422
    response = client.post(
        "/api/auth/register", headers=HEADERS, json={"email": "person@example.com", "password": password}
    )
    assert response.status_code == 422 and "secret" not in response.text
    assert sign_in(client, "missing@example.com").status_code == 401
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(User)) is None


def test_registration_keeps_origin_check_and_rate_limit(client):
    body = {"email": "person@example.com", "password": PASSWORD}
    assert client.post("/api/auth/register", json=body).status_code == 403
    assert (
        client.post(
            "/api/auth/register", headers={**HEADERS, "Origin": "http://other-host"}, json=body
        ).status_code
        == 403
    )
    assert register(client).status_code == 201
    for _ in range(9):
        assert register(client).status_code == 409
    assert register(client).status_code == 429


def test_concurrent_duplicate_registration_is_atomic(client):
    # Use independent cookie jars against the initialized app without re-running lifespan.
    def submit_without_lifespan():
        independent = TestClient(client.app)
        try:
            return register(independent, "same@example.com").status_code
        finally:
            independent.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit_without_lifespan(), range(2)))
    assert sorted(results) == [201, 409]
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(Workspace)) == 1
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 1


def test_email_migration_preserves_legacy_accounts_and_materials(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    engine = create_database_engine(settings)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    user_id = str(uuid.uuid4())
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260907_0001")
        connection.execute(
            text("INSERT INTO users VALUES (:id, 'legacy', '旧账号', 'old-hash', 0, 1, 1)"), {"id": user_id}
        )
        connection.execute(
            text("INSERT INTO workspaces VALUES (:id, 7, :state, 1)"),
            {"id": user_id, "state": json.dumps(empty_workspace())},
        )
        connection.execute(
            text("INSERT INTO sessions VALUES ('old-token-hash', :id, 'old-csrf', 9999999999)"),
            {"id": user_id},
        )
    migrate(engine)
    with Session(engine) as db:
        user = db.get(User, user_id)
        assert user.email is None and user.username == "legacy" and user.password_hash == "old-hash"
        assert db.get(Workspace, user_id).revision == 7
        assert db.get(LoginSession, "old-token-hash").user_id == user_id
    engine.dispose()
