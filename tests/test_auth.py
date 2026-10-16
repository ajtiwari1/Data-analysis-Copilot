from datetime import UTC, datetime, timedelta
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from middleware.config import Settings, settings
from middleware.database import Base, get_db
from middleware.main import app
from middleware.models import AuthSession, User
from middleware.security import hash_session_token


def test_database_url_is_derived_from_postgres_settings():
    configured = Settings(
        _env_file=None,
        database_url=None,
        postgres_db="copilot",
        postgres_user="service",
        postgres_password="p@ss/word",
        postgres_port=5544,
    )

    assert configured.sqlalchemy_database_url == (
        "postgresql+psycopg://service:p%40ss%2Fword@localhost:5544/copilot"
    )


@pytest.fixture
def db_session_factory():
    test_database_url = os.getenv("TEST_DATABASE_URL")
    if test_database_url:
        engine = create_engine(test_database_url, pool_pre_ping=True)
        with sessionmaker(bind=engine)() as db:
            db.execute(delete(AuthSession))
            db.execute(delete(User))
            db.commit()
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)

    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    yield testing_session
    if not test_database_url:
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, db_session_factory):
    def override_get_db():
        with db_session_factory() as db:
            yield db

    monkeypatch.setattr(settings, "session_cookie_secure", False)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_register_persists_hashed_password_and_issues_session(
    client: TestClient, db_session_factory
):
    response = client.post(
        "/api/auth/register",
        json={"email": "  PERSON@example.com ", "password": "a-very-long-password"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "person@example.com"
    assert response.cookies.get("mic_session")
    assert response.headers["set-cookie"].lower().find("httponly") >= 0
    assert response.headers["set-cookie"].lower().find("samesite=lax") >= 0

    with db_session_factory() as db:
        user = db.scalar(select(User).where(User.email == "person@example.com"))
        assert user is not None
        assert user.password_hash != "a-very-long-password"
        assert user.password_hash.startswith("$argon2")
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert session is not None
        assert session.token_hash != response.cookies["mic_session"]
        assert session.token_hash == hash_session_token(response.cookies["mic_session"])

    assert client.get("/api/dashboard").status_code == 200


def test_login_rejects_invalid_credentials_and_logout_invalidates_session(
    client: TestClient,
):
    client.post(
        "/api/auth/register",
        json={"email": "person@example.com", "password": "a-very-long-password"},
    )
    client.post("/api/auth/logout")

    invalid = client.post(
        "/api/auth/login",
        json={"email": "person@example.com", "password": "a-different-password"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid email or password"

    login = client.post(
        "/api/auth/login",
        json={"email": "PERSON@example.com", "password": "a-very-long-password"},
    )
    assert login.status_code == 200
    assert client.get("/api/auth/me").json()["email"] == "person@example.com"
    session_token = login.cookies["mic_session"]

    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("mic_session", session_token)
    assert client.get("/api/auth/me").status_code == 401


def test_duplicate_registration_and_unauthenticated_access(client: TestClient):
    payload = {"email": "person@example.com", "password": "a-very-long-password"}
    assert client.get("/api/dashboard").status_code == 401
    assert client.post("/api/auth/register", json=payload).status_code == 201
    duplicate = client.post("/api/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "An account with this email already exists"


def test_validation_errors_do_not_echo_password(client: TestClient):
    password = "too-short"
    response = client.post(
        "/api/auth/register",
        json={"email": "person@example.com", "password": password},
    )

    assert response.status_code == 422
    assert password not in response.text


def test_expired_session_is_not_accepted(
    client: TestClient, db_session_factory
):
    with db_session_factory() as db:
        user = User(email="person@example.com", password_hash="unused")
        db.add(user)
        db.flush()
        db.add(
            AuthSession(
                token_hash=hash_session_token("expired-token"),
                user_id=user.id,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        db.commit()

    client.cookies.set("mic_session", "expired-token")
    assert client.get("/api/auth/me").status_code == 401
