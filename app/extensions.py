from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

# Initialize Extensions without binding to app
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# app/extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

migrate = Migrate()
