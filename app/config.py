# app/config.py
import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads'
    WTF_CSRF_ENABLED = True
    SECURITY_PASSWORD_SALT = os.getenv('SECURITY_PASSWORD_SALT')
    # אפשר גם:
    # SQLALCHEMY_ECHO = True
    # ALLOWED_EXTENSIONS = {'xlsx'}
