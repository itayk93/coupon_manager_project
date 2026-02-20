import hmac
import logging
import re
import time

from flask import current_app, request, session

from app.extensions import cache
from app.models import AdminSettings

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)
_DOLLAR_AMOUNT_PATTERN = re.compile(r"\$\s?\d")
_MULTI_ASTERISK_PATTERN = re.compile(r"\*{2,}")
_HIGH_DIGIT_PATTERN = re.compile(r"\d{4,}")
_LETTER_PATTERN = re.compile(r"[A-Za-z\u0590-\u05FF]")
_SPAM_KEYWORDS = (
    "confirm",
    "transfer",
    "transaction",
    "salary",
    "deposit",
    "credit",
    "payment",
    "account",
)


def _to_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def get_client_ip():
    for header in ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_public_registration_enabled():
    cache_key = "settings:public_registration_enabled:v1"
    try:
        cached_value = cache.get(cache_key)
        if cached_value is not None:
            return bool(cached_value)
    except Exception as exc:
        logger.warning(
            "Failed reading registration setting from cache '%s': %s",
            cache_key,
            exc,
        )

    default = current_app.config.get("PUBLIC_REGISTRATION_ENABLED", True)
    try:
        setting_value = AdminSettings.get_setting("public_registration_enabled", default)
    except Exception as exc:
        logger.warning(
            "Failed reading 'public_registration_enabled' setting from database: %s",
            exc,
        )
        return default
    enabled = _to_bool(setting_value, default)
    try:
        cache.set(cache_key, enabled, timeout=30)
    except Exception as exc:
        logger.warning(
            "Failed writing registration setting to cache '%s': %s",
            cache_key,
            exc,
        )
    return enabled


def is_api_registration_token_valid(provided_token):
    expected_token = current_app.config.get("API_REGISTRATION_TOKEN")
    if not expected_token:
        return True
    return hmac.compare_digest(provided_token or "", expected_token)


def mark_register_form_rendered():
    session["register_form_loaded_at"] = int(time.time())


def is_register_submission_too_fast():
    min_seconds = max(
        int(current_app.config.get("REGISTRATION_MIN_FORM_FILL_SECONDS", 3)), 0
    )
    if min_seconds == 0:
        return False

    loaded_at = session.get("register_form_loaded_at")
    if loaded_at is None:
        return True

    try:
        elapsed_seconds = int(time.time()) - int(loaded_at)
    except (TypeError, ValueError):
        return True

    return elapsed_seconds < min_seconds


def is_honeypot_triggered(value):
    return bool((value or "").strip())


def is_registration_payload_suspicious(first_name, last_name, email):
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    full_name_lower = full_name.lower()

    max_name_length = max(
        int(current_app.config.get("REGISTRATION_MAX_NAME_LENGTH", 60)),
        2,
    )

    if not first_name or not last_name:
        return True, "missing_name_parts"

    if len(first_name) > max_name_length or len(last_name) > max_name_length:
        return True, "name_too_long"

    if not _LETTER_PATTERN.search(full_name):
        return True, "name_without_letters"

    if _URL_PATTERN.search(full_name_lower):
        return True, "name_contains_url"

    if _DOLLAR_AMOUNT_PATTERN.search(full_name):
        return True, "name_contains_amount"

    if "💳" in full_name:
        return True, "name_contains_credit_card_emoji"

    if _MULTI_ASTERISK_PATTERN.search(full_name):
        return True, "name_contains_repeated_asterisk"

    if _HIGH_DIGIT_PATTERN.search(full_name):
        return True, "name_contains_many_digits"

    if any(keyword in full_name_lower for keyword in _SPAM_KEYWORDS):
        return True, "name_contains_spam_keyword"

    normalized_email = (email or "").strip().lower()
    if len(normalized_email) > 150:
        return True, "email_too_long"

    return False, ""


def check_registration_rate_limits(ip_address, email):
    ip_address = ip_address or "unknown"
    normalized_email = (email or "").strip().lower()

    checks = [
        (
            f"registration:attempt:ip:10m:{ip_address}",
            int(current_app.config.get("REGISTRATION_MAX_ATTEMPTS_PER_IP_10_MIN", 3)),
            10 * 60,
            "בוצעו יותר מדי ניסיונות הרשמה מה-IP הזה. נסה שוב בעוד כמה דקות.",
        ),
        (
            f"registration:attempt:ip:1h:{ip_address}",
            int(current_app.config.get("REGISTRATION_MAX_ATTEMPTS_PER_IP_HOUR", 10)),
            60 * 60,
            "בוצעו יותר מדי ניסיונות הרשמה מה-IP הזה בשעה האחרונה.",
        ),
        (
            f"registration:attempt:ip:1d:{ip_address}",
            int(current_app.config.get("REGISTRATION_MAX_ATTEMPTS_PER_IP_DAY", 25)),
            24 * 60 * 60,
            "בוצעו יותר מדי ניסיונות הרשמה מה-IP הזה היום.",
        ),
        (
            "registration:attempt:global:10m",
            int(
                current_app.config.get(
                    "REGISTRATION_MAX_ATTEMPTS_GLOBAL_10_MIN", 150
                )
            ),
            10 * 60,
            "יש עומס חריג על הרשמות כרגע. נסה שוב בעוד כמה דקות.",
        ),
    ]

    if normalized_email:
        checks.append(
            (
                f"registration:attempt:email:1d:{normalized_email}",
                int(
                    current_app.config.get(
                        "REGISTRATION_MAX_ATTEMPTS_PER_EMAIL_DAY", 5
                    )
                ),
                24 * 60 * 60,
                "בוצעו יותר מדי ניסיונות הרשמה עבור כתובת האימייל הזו היום.",
            )
        )

    for key, limit, ttl, message in checks:
        if limit <= 0:
            continue
        attempts = _increment_counter(key, ttl)
        if attempts > limit:
            return True, message

    return False, ""


def _increment_counter(key, ttl):
    try:
        current_value = cache.get(key)
        if current_value is None:
            cache.set(key, 1, timeout=ttl)
            return 1

        next_value = int(current_value) + 1
        cache.set(key, next_value, timeout=ttl)
        return next_value
    except Exception as exc:
        # Fail-open so that cache/network issues don't block legitimate users.
        logger.warning(
            "Failed to update registration rate-limit counter '%s': %s",
            key,
            exc,
        )
        return 1
