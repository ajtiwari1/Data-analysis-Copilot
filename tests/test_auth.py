from datetime import UTC, date, datetime, timedelta
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pytest import approx

from middleware.config import Settings, settings
from middleware.database import Base, get_db
from middleware.main import app
from middleware.models import AuthSession, Product, SalesRecord, Site, User
from middleware.security import hash_session_token
from middleware.services.demo_data import seed_demo_data


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
        assert db.scalar(select(func.count(Site.id)).where(Site.user_id == user.id)) == 2
        assert (
            db.scalar(
                select(func.count(Product.id))
                .join(Site)
                .where(Site.user_id == user.id)
            )
            == 8
        )
        assert (
            db.scalar(
                select(func.count(SalesRecord.id))
                .join(Site)
                .where(Site.user_id == user.id)
            )
            > 700
        )

    assert client.get("/api/dashboard").status_code == 200
    assert len(client.get("/api/analytics/sites").json()) == 2
    assert len(client.get("/api/analytics/products").json()) == 8


def test_demo_seed_is_idempotent(db_session_factory):
    with db_session_factory() as db:
        user = User(email="seed@example.com", password_hash="unused")
        db.add(user)
        db.flush()

        inserted = seed_demo_data(db, user, today=date(2026, 10, 16))
        db.flush()
        inserted_on_retry = seed_demo_data(db, user, today=date(2026, 10, 16))
        db.commit()

        assert inserted > 700
        assert inserted_on_retry == 0
        assert db.scalar(select(func.count(Site.id)).where(Site.user_id == user.id)) == 2
        assert (
            db.scalar(
                select(func.count(SalesRecord.id))
                .join(Site)
                .where(Site.user_id == user.id)
            )
            == inserted
        )


def test_analytics_filters_and_prevent_cross_user_access(client: TestClient):
    first_user = client.post(
        "/api/auth/register",
        json={"email": "first@example.com", "password": "a-very-long-password"},
    )
    assert first_user.status_code == 201
    first_sites = client.get("/api/analytics/sites").json()
    first_site_id = first_sites[0]["id"]

    overview = client.get(
        "/api/analytics/overview",
        params={
            "site_id": first_site_id,
            "start_date": "2026-10-01",
            "end_date": "2026-10-16",
        },
    )
    assert overview.status_code == 200
    data = overview.json()
    assert len(data["daily_sales"]) == 16
    assert data["orders"] == sum(item["orders"] for item in data["daily_sales"])
    assert data["revenue"] > 0
    assert data["revenue"] == approx(
        sum(item["revenue"] for item in data["daily_sales"])
    )

    second_user = client.post(
        "/api/auth/register",
        json={"email": "second@example.com", "password": "a-very-long-password"},
    )
    assert second_user.status_code == 201
    assert all(
        site["id"] != first_site_id for site in client.get("/api/analytics/sites").json()
    )
    assert (
        client.get(
            "/api/analytics/overview", params={"site_id": first_site_id}
        ).status_code
        == 404
    )


def test_analytics_rejects_invalid_date_range_and_mismatched_product(client: TestClient):
    assert client.post(
        "/api/auth/register",
        json={"email": "filters@example.com", "password": "a-very-long-password"},
    ).status_code == 201
    site = client.get("/api/analytics/sites").json()[0]
    product = client.get(
        "/api/analytics/products", params={"site_id": site["id"]}
    ).json()[0]

    assert (
        client.get(
            "/api/analytics/overview",
            params={"start_date": "2026-10-20", "end_date": "2026-10-01"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/analytics/overview",
            params={"site_id": site["id"], "product_id": product["id"] + 9999},
        ).status_code
        == 404
    )


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
