# app/config.py
import os
import logging

LOGGING_CONFIG = None
LOG_LEVEL = logging.DEBUG


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
    # Modify the database URI to handle SSL properly
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///default.db")
    if DATABASE_URL.startswith('postgresql://'):
        DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg2://', 1)
        if '?' not in DATABASE_URL:
            DATABASE_URL += '?sslmode=require'
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "default_salt")
    UPLOAD_FOLDER = "uploads"
    # ALLOWED_EXTENSIONS = {'xlsx'}  # אם תרצה
    # Telegram Bot Configuration
    TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
