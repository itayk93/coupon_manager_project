import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
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

_db_file = Path(tempfile.gettempdir()) / "coupon_manager_authz_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file}"

from app import create_app
from app.extensions import db
from app.models import User, Coupon, CouponRequest, CouponShares


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
            email="a@example.com",
            first_name="User",
            last_name="A",
            is_confirmed=True,
            is_admin=False,
        )
        user_a.set_password("StrongPass123!")

        user_b = User(
            email="b@example.com",
            first_name="User",
            last_name="B",
            is_confirmed=True,
            is_admin=False,
        )
        user_b.set_password("StrongPass123!")

        admin = User(
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
            is_confirmed=True,
            is_admin=True,
        )
        admin.set_password("StrongPass123!")

        db.session.add_all([user_a, user_b, admin])
        db.session.commit()

        coupon_b = Coupon(
            code="B-COUPON-AUTHZ-001",
            description="Private coupon B",
            value=100,
            cost=75,
            company="AuthzCo",
            user_id=user_b.id,
            status="פעיל",
        )
        db.session.add(coupon_b)
        db.session.flush()

        req_b = CouponRequest(
            company="AuthzCo",
            value=100,
            cost=80,
            user_id=user_b.id,
            date_requested=datetime.utcnow(),
            fulfilled=False,
        )
        db.session.add(req_b)
        db.session.commit()

    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _api_login(client, email, password="StrongPass123!"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_coupon_request_detail_denies_non_owner(client, app):
    with app.app_context():
        req_b = CouponRequest.query.filter_by(user_id=User.query.filter_by(email="b@example.com").first().id).first()

    _api_login(client, "a@example.com")
    res = client.get(f"/coupon_request/{req_b.id}")

    assert res.status_code == 302


def test_delete_coupon_request_denies_non_owner(client, app):
    with app.app_context():
        user_b = User.query.filter_by(email="b@example.com").first()
        req_b = CouponRequest.query.filter_by(user_id=user_b.id).first()
        req_id = req_b.id

    _api_login(client, "a@example.com")
    res = client.post(f"/delete_coupon_request/{req_id}")

    assert res.status_code == 302

    with app.app_context():
        still_exists = CouponRequest.query.get(req_id)
        assert still_exists is not None


def test_track_and_get_viewers_forbidden_without_coupon_access(client, app):
    with app.app_context():
        user_b = User.query.filter_by(email="b@example.com").first()
        coupon_b = Coupon.query.filter_by(user_id=user_b.id).first()

    _api_login(client, "a@example.com")

    track = client.post(
        f"/track_coupon_viewer/{coupon_b.id}",
        json={"session_id": "sess-a"},
    )
    assert track.status_code == 403

    viewers = client.get(f"/get_active_viewers/{coupon_b.id}")
    assert viewers.status_code == 403


def test_track_viewer_allowed_for_shared_coupon(client, app):
    with app.app_context():
        user_a = User.query.filter_by(email="a@example.com").first()
        user_b = User.query.filter_by(email="b@example.com").first()
        coupon_b = Coupon.query.filter_by(user_id=user_b.id).first()
        coupon_id = coupon_b.id

        share = CouponShares(
            coupon_id=coupon_id,
            shared_by_user_id=user_b.id,
            shared_with_user_id=user_a.id,
            share_token="token-shared-authz",
            status="accepted",
            share_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            accepted_at=datetime.now(timezone.utc),
        )
        db.session.add(share)
        db.session.commit()

    _api_login(client, "a@example.com")
    track = client.post(
        f"/track_coupon_viewer/{coupon_id}",
        json={"session_id": "sess-shared"},
    )

    assert track.status_code == 200
    payload = track.get_json()
    assert payload.get("success") is True


def test_admin_email_report_endpoint_protected(client):
    unauth = client.get("/admin/email/view-full-report")
    assert unauth.status_code == 302

    _api_login(client, "a@example.com")
    non_admin = client.get("/admin/email/view-full-report")
    assert non_admin.status_code == 302

    _api_login(client, "admin@example.com")
    admin = client.get("/admin/email/view-full-report")
    assert admin.status_code == 200
