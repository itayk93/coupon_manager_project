# app/config.py
import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'default_secret_key')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///default.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SECURITY_PASSWORD_SALT = os.getenv('SECURITY_PASSWORD_SALT', 'default_salt')
    UPLOAD_FOLDER = 'uploads'
    # ALLOWED_EXTENSIONS = {'xlsx'}  # אם תרצה
