# app/config.py
import os
import logging

LOGGING_CONFIG = None
LOG_LEVEL = logging.DEBUG


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI", "postgresql+psycopg2://postgres.dugjsiyenazpsoiyduuz:ZQCBKYkI1eB6f2sW@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "default_salt")
    UPLOAD_FOLDER = "uploads"
    # ALLOWED_EXTENSIONS = {'xlsx'}  # אם תרצה
    # Telegram Bot Configuration
    TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    # Telegram Bot Security Settings
    TELEGRAM_VERIFICATION_ENABLED = True  # ביטול אימות קוד
    TELEGRAM_BLOCKING_ENABLED = False      # ביטול חסימת משתמשים
    TELEGRAM_IP_TRACKING = False           # ביטול מעקב IP
    TELEGRAM_DEVICE_TRACKING = True       # ביטול מעקב מכשירים
    TELEGRAM_TOKEN_EXPIRY = False          # ביטול תפוגת קוד
    TELEGRAM_ATTEMPT_LIMIT = False         # ביטול הגבלת ניסיונות
    TELEGRAM_CSRF_PROTECTION = True       # ביטול הגנת CSRF
    TELEGRAM_LOGGING = True               # ביטול תיעוד פעולות
