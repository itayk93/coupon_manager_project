# app/utils/tokens.py
"""
טוקנים חתומים לקישורי מייל (ביטול הרשמה / העדפות).

חייבים להיות דטרמיניסטיים בין תהליכים ובין הפעלות שרת — לכן HMAC על
SECRET_KEY ולא hash() של פייתון (שמקבל seed אקראי בכל תהליך).
"""
import hashlib
import hmac

from flask import current_app


def _sign(payload: str) -> str:
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def generate_unsubscribe_token(user) -> str:
    """טוקן לביטול הרשמה לניוזלטר"""
    return _sign(f"unsubscribe:{user.id}:{user.email}")


def generate_preferences_token(user) -> str:
    """טוקן לעדכון העדפות דיוור"""
    return _sign(f"preferences:{user.id}:{user.email}")


def verify_token(expected: str, provided: str) -> bool:
    """השוואה בטוחה (constant-time) של טוקנים"""
    return hmac.compare_digest(str(expected), str(provided or ""))
