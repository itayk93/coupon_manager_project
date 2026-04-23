import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
os.environ.setdefault("ALLOW_INSECURE_OAUTH_TRANSPORT", "0")
os.environ.setdefault("ENABLE_EXTERNAL_WIDGET", "0")

_db_file = Path(tempfile.gettempdir()) / "coupon_manager_authz_ext_test.db"
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
        LOGIN_MAX_ATTEMPTS=10,
    )

    with app.app_context():
        db.drop_all()
        db.create_all()

        user_a = User(
            email="a2@example.com",
            first_name="User",
            last_name="A2",
            is_confirmed=True,
            is_admin=False,
        )
        user_a.set_password("StrongPass123!")

        user_b = User(
            email="b2@example.com",
            first_name="User",
            last_name="B2",
            is_confirmed=True,
            is_admin=False,
        )
        user_b.set_password("StrongPass123!")

        db.session.add_all([user_a, user_b])
        db.session.commit()

        coupon_b = Coupon(
            code="B2-COUPON-001",
            description="Private coupon B2",
            value=200,
            cost=150,
            company="AuthzExtCo",
            user_id=user_b.id,
            status="פעיל",
            is_available=True,
            is_for_sale=False,
        )
        db.session.add(coupon_b)
        db.session.commit()

    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _api_login(client, email, password="StrongPass123!"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_coupon_detail_web_denies_non_owner_non_shared(client, app):
    with app.app_context():
        user_b = User.query.filter_by(email="b2@example.com").first()
        coupon_b = Coupon.query.filter_by(user_id=user_b.id).first()

    _api_login(client, "a2@example.com")
    res = client.get(f"/coupon_detail/{coupon_b.id}")
    assert res.status_code == 404


def test_api_coupon_detail_requires_login(client, app):
    with app.app_context():
        user_b = User.query.filter_by(email="b2@example.com").first()
        coupon_b = Coupon.query.filter_by(user_id=user_b.id).first()

    res = client.get(f"/api/coupon_detail/{coupon_b.id}")
    assert res.status_code == 302


def test_api_coupon_detail_cannot_be_spoofed_by_header(client, app):
    with app.app_context():
        user_b = User.query.filter_by(email="b2@example.com").first()
        coupon_b = Coupon.query.filter_by(user_id=user_b.id).first()

    _api_login(client, "a2@example.com")
    res = client.get(
        f"/api/coupon_detail/{coupon_b.id}",
        headers={"X-User-ID": str(user_b.id)},
    )
    assert res.status_code == 403


def test_api_coupon_detail_allows_owner(client, app):
    with app.app_context():
        user_b = User.query.filter_by(email="b2@example.com").first()
        coupon_b = Coupon.query.filter_by(user_id=user_b.id).first()

    _api_login(client, "b2@example.com")
    res = client.get(f"/api/coupon_detail/{coupon_b.id}")
    assert res.status_code == 200


def test_api_coupon_use_denies_non_owner(client, app):
    with app.app_context():
        user_b = User.query.filter_by(email="b2@example.com").first()
        coupon_b = Coupon.query.filter_by(user_id=user_b.id).first()

    _api_login(client, "a2@example.com")
    res = client.post(
        f"/api/coupons/{coupon_b.id}/use",
        json={"used_amount": 10},
    )
    assert res.status_code == 403
