# app/routes/usage_data_routes.py

import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_login import current_user  # <-- ייבוא Flask-Login
from sqlalchemy import func

from app.extensions import db
from app.models import User, UserConsent, UserActivity, OptOut


usage_data_bp = Blueprint("usage_data_bp", __name__)


def get_client_ip():
    """
    מחזיר את כתובת ה-IP של המשתמש (במידת האפשר).
    """
    if request.headers.get('X-Forwarded-For'):
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    return request.remote_addr


def parse_user_agent():
    """
    ניתוח דפדפן ומכשיר בסיסי מתוך ה-User-Agent.
    אפשר להרחיב עם ספרייה כמו 'user_agents' למידע מפורט יותר.
    """
    ua_string = request.headers.get('User-Agent', '')
    device = "Desktop"
    browser = "UnknownBrowser"

    if "Mobile" in ua_string:
        device = "Mobile"
    if "Chrome" in ua_string:
        browser = "Chrome"
    elif "Firefox" in ua_string:
        browser = "Firefox"
    elif "Safari" in ua_string:
        browser = "Safari"

    return device, browser


def user_is_opted_out(user_id):
    """
    בודק אם המשתמש סימן Opt-Out.
    """
    opt_out_record = OptOut.query.filter_by(user_id=user_id).first()
    return bool(opt_out_record and opt_out_record.opted_out)


@usage_data_bp.route("/register_user", methods=["POST"])
def register_user():
    """
    רישום משתמש חדש (אם אין לך כבר Route כזה).
    מצפה ל-JSON בפורמט: { "email": "user@example.com" }
    """
    data = request.get_json()
    email = data.get("email")
    if not email:
        return jsonify({"error": "Missing 'email' field"}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"message": "User already exists", "user_id": existing_user.id}), 200

    new_user = User(email=email)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User registered", "user_id": new_user.id}), 201


@usage_data_bp.route("/consent", methods=["POST"])
def consent():
    """
    שמירת הסכמה או אי-הסכמה לאיסוף נתונים.
    מצפה ל-JSON: { "user_id": 123, "consent_status": true/false, "version": "1.0" }
    """
    data = request.get_json()
    user_id = data.get("user_id")
    consent_status = data.get("consent_status")
    version = data.get("version", "1.0")

    if user_id is None or consent_status is None:
        return jsonify({"error": "Missing user_id or consent_status"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    new_consent = UserConsent(
        user_id=user_id,
        consent_status=consent_status,
        version=version
    )
    db.session.add(new_consent)
    db.session.commit()

    return jsonify({"message": "Consent saved"}), 200


@usage_data_bp.route("/opt_out", methods=["POST"])
def opt_out():
    """
    משתמש יכול לבצע Opt-Out מאיסוף הנתונים.
    מצפה ל-JSON: { "user_id": 123 }
    """
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    opt_out_record = OptOut.query.filter_by(user_id=user_id).first()
    if not opt_out_record:
        opt_out_record = OptOut(user_id=user_id, opted_out=True)
        db.session.add(opt_out_record)
    else:
        opt_out_record.opted_out = True

    db.session.commit()
    return jsonify({"message": "User opted out successfully"}), 200


@usage_data_bp.route("/cancel_opt_out", methods=["POST"])
def cancel_opt_out():
    """
    משתמש יכול לבטל Opt-Out ולחזור לאיסוף נתונים.
    מצפה ל-JSON: { "user_id": 123 }
    """
    data = request.get_json()
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    opt_out_record = OptOut.query.filter_by(user_id=user_id).first()
    if not opt_out_record:
        opt_out_record = OptOut(user_id=user_id, opted_out=False)
        db.session.add(opt_out_record)
    else:
        opt_out_record.opted_out = False

    db.session.commit()
    return jsonify({"message": "User cancel opt-out successfully"}), 200


@usage_data_bp.route("/track_event", methods=["POST"])
def track_event():
    """
    נתיב לרישום אירועים (פעילויות משתמשים).
    מצפה ל-JSON, לדוגמה:
    {
      "user_id": 123,
      "action": "view_coupon",
      "coupon_id": 456,
      "duration": 10,
      "metadata": {"someKey": "someVal"}
    }
    """
    data = request.get_json()

    user_id = data.get("user_id")  # יכול להיות None אם אין מזהה משתמש (לא מחובר)
    action = data.get("action")
    if not action:
        return jsonify({"error": "Missing 'action' field"}), 400

    # בדיקת הסכמה עבור משתמש מחובר
    if current_user.is_authenticated:
        user_consent = UserConsent.query.filter_by(user_id=current_user.id).first()
        if not (user_consent and user_consent.consent_status):
            return jsonify({"message": "User did not consent. Event not tracked."}), 403

    # אם המשתמש לא מחובר אבל בכל זאת אנחנו רוצים לקלוט אנונימית, אפשר/לא לפי הצורך:
    # אם לא רוצים לקלוט כלום כשהמשתמש לא מחובר, אפשר להחזיר 401:
    # if not current_user.is_authenticated:
    #     return jsonify({"message": "Unauthorized - user not logged in."}), 401

    ip_address = get_client_ip()
    device, browser = parse_user_agent()

    activity = UserActivity(
        user_id=user_id,
        action=action,
        coupon_id=data.get("coupon_id"),
        timestamp=datetime.utcnow(),
        ip_address=ip_address,
        device=device,
        browser=browser,
        geo_location="",  # למילוי ע"י שירות חיצוני אם תרצה
        duration=data.get("duration"),
        extra_metadata=json.dumps(data.get("metadata")) if data.get("metadata") else None
    )
    db.session.add(activity)
    db.session.commit()

    return jsonify({"message": "Event tracked"}), 201


@usage_data_bp.route("/delete_user_data", methods=["POST"])
def delete_user_data():
    """
    מאפשר למשתמש למחוק את כל המידע האישי שלו (GDPR - Right to be forgotten).
    מצפה ל-JSON: { "user_id": 123 }
    """
    data = request.get_json()
    user_id = data.get("user_id")

    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # מוחקים פעילויות, הסכמות ו־OptOut
    UserActivity.query.filter_by(user_id=user_id).delete()
    UserConsent.query.filter_by(user_id=user_id).delete()
    OptOut.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()

    return jsonify({"message": "User data deleted successfully"}), 200


@usage_data_bp.route("/analytics/activities", methods=["GET"])
def get_all_activities():
    """
    מחזיר רשימת כל הפעילויות של משתמשים **שנתנו הסכמה**.
    """
    # בדיקת הסכמה עבור המשתמש המחובר (אם חובה שהמשתמש יצפה בדוחות רק אם הוא נתן הסכמה):
    if current_user.is_authenticated:
        user_consent = UserConsent.query.filter_by(user_id=current_user.id).first()
        if not (user_consent and user_consent.consent_status):
            return jsonify({"message": "User did not consent. Activities not returned."}), 403

    # שליפת פעילויות של משתמשים שנתנו הסכמה בלבד
    activities = (
        UserActivity.query
        .join(UserConsent, UserActivity.user_id == UserConsent.user_id)
        .filter(UserConsent.consent_status == True)
        .all()
    )

    result = []
    for a in activities:
        result.append({
            "activity_id": a.activity_id,
            "user_id": a.user_id,
            "action": a.action,
            "coupon_id": a.coupon_id,
            "timestamp": a.timestamp.isoformat(),
            "ip_address": a.ip_address,
            "device": a.device,
            "browser": a.browser,
            "geo_location": a.geo_location,
            "duration": a.duration,
            "metadata": a.extra_metadata
        })
    return jsonify(result), 200


@usage_data_bp.route("/analytics/summary", methods=["GET"])
def analytics_summary():
    """
    דוגמה לטבלת סיכום בסיסית:
    - כמות אירועים לפי פעולה
    - כמות משתמשים פעילים
    - כמות קופונים שנצפו/מומשו
    """
    # בודקים שהמשתמש המחובר הסכים או לא, לפי מדיניות האתר:
    if current_user.is_authenticated:
        user_consent = UserConsent.query.filter_by(user_id=current_user.id).first()
        if not (user_consent and user_consent.consent_status):
            return jsonify({"message": "User did not consent. Summary not returned."}), 403

    action_counts = (
        db.session.query(
            UserActivity.action,
            func.count(UserActivity.action)
        )
        .join(UserConsent, UserActivity.user_id == UserConsent.user_id)
        .filter(UserConsent.consent_status == True)
        .group_by(UserActivity.action)
        .all()
    )

    active_users = (
        db.session.query(UserActivity.user_id)
        .join(UserConsent, UserActivity.user_id == UserConsent.user_id)
        .filter(UserConsent.consent_status == True)
        .distinct()
        .count()
    )

    viewed_coupons = (
        db.session.query(UserActivity.coupon_id)
        .join(UserConsent, UserActivity.user_id == UserConsent.user_id)
        .filter(UserConsent.consent_status == True,
                UserActivity.action == "view_coupon")
        .distinct()
        .count()
    )

    redeemed_coupons = (
        db.session.query(UserActivity.coupon_id)
        .join(UserConsent, UserActivity.user_id == UserConsent.user_id)
        .filter(UserConsent.consent_status == True,
                UserActivity.action == "redeem_coupon")
        .distinct()
        .count()
    )

    data = {
        "action_counts": {action: count for action, count in action_counts},
        "active_users": active_users,
        "viewed_coupons": viewed_coupons,
        "redeemed_coupons": redeemed_coupons
    }
    return jsonify(data), 200
