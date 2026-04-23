# app/config.py
import os
import logging

LOGGING_CONFIG = None
LOG_LEVEL = logging.DEBUG


def _get_bool_env(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int_env(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class Config:
    TESTING = _get_bool_env("TESTING", False)
    SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
    # Modify the database URI to handle SSL properly
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///default.db")
    if DATABASE_URL.startswith('postgresql://'):
        DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg2://', 1)
        if '?' not in DATABASE_URL:
            DATABASE_URL += '?sslmode=require'
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "pool_size": 10,
        "max_overflow": 20,
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "default_salt")
    UPLOAD_FOLDER = "uploads"
    # ALLOWED_EXTENSIONS = {'xlsx'}  # אם תרצה
    # Telegram Bot Configuration
    TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    # API Configuration
    CRON_API_TOKEN = os.getenv("CRON_API_TOKEN", "your-secure-api-token-here")
    
    # Cache Configuration
    CACHE_TYPE = "SimpleCache" if TESTING else os.getenv("CACHE_TYPE", "RedisCache")
    CACHE_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes default
    CACHE_NO_NULL_WARNING = True

    # Cookie hardening
    SESSION_COOKIE_SECURE = _get_bool_env("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    REMEMBER_COOKIE_SECURE = _get_bool_env("REMEMBER_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = os.getenv("REMEMBER_COOKIE_SAMESITE", "Lax")

    # Security headers and feature flags
    ENABLE_SECURITY_HEADERS = _get_bool_env("ENABLE_SECURITY_HEADERS", True)
    ENABLE_EXTERNAL_WIDGET = _get_bool_env("ENABLE_EXTERNAL_WIDGET", False)
    ENABLE_SCHEDULER = _get_bool_env("ENABLE_SCHEDULER", True)
    ALLOW_INSECURE_OAUTH_TRANSPORT = _get_bool_env(
        "ALLOW_INSECURE_OAUTH_TRANSPORT", False
    )

    # Login abuse protection
    LOGIN_MAX_ATTEMPTS = _get_int_env("LOGIN_MAX_ATTEMPTS", 6)
    LOGIN_WINDOW_SECONDS = _get_int_env("LOGIN_WINDOW_SECONDS", 600)
    LOGIN_LOCK_SECONDS = _get_int_env("LOGIN_LOCK_SECONDS", 900)

    # Registration protection
    PUBLIC_REGISTRATION_ENABLED = _get_bool_env("PUBLIC_REGISTRATION_ENABLED", True)
    REGISTRATION_MIN_FORM_FILL_SECONDS = _get_int_env(
        "REGISTRATION_MIN_FORM_FILL_SECONDS", 3
    )
    REGISTRATION_MAX_ATTEMPTS_PER_IP_10_MIN = _get_int_env(
        "REGISTRATION_MAX_ATTEMPTS_PER_IP_10_MIN", 3
    )
    REGISTRATION_MAX_ATTEMPTS_PER_IP_HOUR = _get_int_env(
        "REGISTRATION_MAX_ATTEMPTS_PER_IP_HOUR", 10
    )
    REGISTRATION_MAX_ATTEMPTS_PER_IP_DAY = _get_int_env(
        "REGISTRATION_MAX_ATTEMPTS_PER_IP_DAY", 25
    )
    REGISTRATION_MAX_ATTEMPTS_PER_EMAIL_DAY = _get_int_env(
        "REGISTRATION_MAX_ATTEMPTS_PER_EMAIL_DAY", 5
    )
    REGISTRATION_MAX_ATTEMPTS_GLOBAL_10_MIN = _get_int_env(
        "REGISTRATION_MAX_ATTEMPTS_GLOBAL_10_MIN", 150
    )
    REGISTRATION_MAX_NAME_LENGTH = _get_int_env("REGISTRATION_MAX_NAME_LENGTH", 60)

    # Optional shared secret for /api/auth/register requests.
    API_REGISTRATION_TOKEN = os.getenv("API_REGISTRATION_TOKEN")
