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
    CACHE_TYPE = "RedisCache"
    CACHE_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CACHE_DEFAULT_TIMEOUT = 300  # 5 minutes default

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
