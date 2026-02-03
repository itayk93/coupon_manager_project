from __future__ import annotations

from datetime import datetime

from flask import current_app, request
from sqlalchemy.sql import text

from app.extensions import db
from app.models import OptOut


def _get_client_ip() -> str | None:
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr


def _parse_user_agent() -> tuple[str | None, str | None]:
    ua_string = request.headers.get("User-Agent", "")
    if not ua_string:
        return None, None
    device = ua_string[:50]
    browser = ua_string.split(" ")[0][:50] if ua_string else None
    return device, browser


def log_activity(
    *,
    action: str,
    user_id: int | None,
    coupon_id: int | None = None,
    respect_opt_out: bool = True,
) -> None:
    """
    Write a minimal activity row to `user_activities`.

    Notes:
    - Inserts only common columns (works even if the table has additional columns).
    - Does not depend on consent, but can respect Opt-Out.
    """
    try:
        if not action:
            return

        if respect_opt_out and user_id is not None:
            opt_out = OptOut.query.filter_by(user_id=user_id).first()
            if opt_out and opt_out.opted_out:
                return

        ip_address = _get_client_ip()
        device, browser = _parse_user_agent()

        db.session.execute(
            text(
                """
                INSERT INTO user_activities
                    (user_id, coupon_id, timestamp, action, device, browser, ip_address)
                VALUES
                    (:user_id, :coupon_id, :timestamp, :action, :device, :browser, :ip_address)
                """
            ),
            {
                "user_id": user_id,
                "coupon_id": coupon_id,
                "timestamp": datetime.utcnow(),
                "action": action,
                "device": device,
                "browser": browser,
                "ip_address": (ip_address[:45] if ip_address else None),
            },
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(f"Failed to log activity [{action}]: {exc}")

