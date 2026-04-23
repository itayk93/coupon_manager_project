import os
import tempfile
from pathlib import Path
import sys

from cryptography.fernet import Fernet
import pytest

# Ensure project root is importable.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure required env vars exist before importing app modules.
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
os.environ.setdefault("ALLOW_INSECURE_OAUTH_TRANSPORT", "0")
os.environ.setdefault("ENABLE_EXTERNAL_WIDGET", "0")

_db_file = Path(tempfile.gettempdir()) / "coupon_manager_security_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file}"

from app import create_app
from app.extensions import db
from app.models import User, Coupon


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        LOGIN_MAX_ATTEMPTS=3,
        LOGIN_WINDOW_SECONDS=300,
        LOGIN_LOCK_SECONDS=600,
    )

    with app.app_context():
        db.drop_all()
        db.create_all()

        user_a = User(
            email="alice@example.com",
            first_name="Alice",
            last_name="A",
            is_confirmed=True,
            is_deleted=False,
            is_admin=False,
        )
        user_a.set_password("StrongPass123!")

        user_b = User(
            email="bob@example.com",
            first_name="Bob",
            last_name="B",
            is_confirmed=True,
            is_deleted=False,
            is_admin=False,
        )
        user_b.set_password("StrongPass123!")

        db.session.add_all([user_a, user_b])
        db.session.commit()

        coupon_b = Coupon(
            code="B-COUPON-001",
            description="Private coupon",
            value=100,
            cost=80,
            company="TestCo",
            user_id=user_b.id,
            status="פעיל",
        )
        db.session.add(coupon_b)
        db.session.commit()

    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _api_login(client, email, password):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )


def test_security_headers_exist(client):
    res = client.get("/auth/login")
    assert res.status_code == 200
    assert "Content-Security-Policy" in res.headers
    assert "X-Frame-Options" in res.headers
    assert "X-Content-Type-Options" in res.headers
    assert "Referrer-Policy" in res.headers
    assert "Permissions-Policy" in res.headers


def test_robots_and_sitemap_exist(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert b"Sitemap:" in robots.data

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert b"<urlset" in sitemap.data


def test_login_rate_limit_blocks_after_repeated_failures(client):
    for _ in range(3):
        res = _api_login(client, "alice@example.com", "bad-password")
        assert res.status_code == 401

    blocked = _api_login(client, "alice@example.com", "bad-password")
    assert blocked.status_code == 429


def test_user_cannot_access_other_users_data(client, app):
    with app.app_context():
        user_a = User.query.filter_by(email="alice@example.com").first()
        user_b = User.query.filter_by(email="bob@example.com").first()

    login_res = _api_login(client, "alice@example.com", "StrongPass123!")
    assert login_res.status_code == 200

    own_coupons = client.get(f"/api/coupons/user/{user_a.id}")
    assert own_coupons.status_code == 200

    other_coupons = client.get(f"/api/coupons/user/{user_b.id}")
    assert other_coupons.status_code == 403

    other_stats = client.get(f"/api/statistics/user/{user_b.id}")
    assert other_stats.status_code == 403


def test_debug_user_endpoint_admin_only_and_no_password_exposure(client, app):
    with app.app_context():
        user_a = User.query.filter_by(email="alice@example.com").first()
        user_b = User.query.filter_by(email="bob@example.com").first()

    login_res = _api_login(client, "alice@example.com", "StrongPass123!")
    assert login_res.status_code == 200

    not_admin = client.get(f"/api/debug/user/{user_b.id}")
    assert not_admin.status_code == 403

    with app.app_context():
        user_a = User.query.filter_by(email="alice@example.com").first()
        user_a.is_admin = True
        db.session.commit()

    admin_allowed = client.get(f"/api/debug/user/{user_b.id}")
    assert admin_allowed.status_code == 200
    payload = admin_allowed.get_json()
    assert "password_hash" not in payload.get("user", {})
