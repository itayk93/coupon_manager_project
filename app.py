import os
import logging
from datetime import datetime, timedelta
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from app.extensions import db, login_manager, csrf
from app.models import User, Tag

# טעינת משתני סביבה
load_dotenv()

app = Flask(__name__)
# הגדרת הרמה של ה-logger של האפליקציה עצמה
app.logger.setLevel(logging.DEBUG)

# הגדרות תצורה
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['WTF_CSRF_ENABLED'] = True
app.config['SECURITY_PASSWORD_SALT'] = os.getenv('SECURITY_PASSWORD_SALT')
ALLOWED_EXTENSIONS = {'xlsx'}

# 🔥 הוסף כאן את הגדרות ה-Session וה-Cookies 🔥
from datetime import timedelta
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_TYPE'] = "filesystem"  # אפשר גם Redis/Memcached
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SECURE'] = True  # True אם האתר עובד עם HTTPS
app.config['REMEMBER_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# אתחול הרחבות
db.init_app(app)
migrate = Migrate(app, db)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'  # נניח שה-login route נמצא ב-auth_routes
csrf.init_app(app)

import logging

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ייבוא ה-Blueprints
from app.routes.auth_routes import auth_bp
from app.routes.profile_routes import profile_bp
from app.routes.coupons_routes import coupons_bp
from app.routes.marketplace_routes import marketplace_bp
from app.routes.requests_routes import requests_bp
from app.routes.transactions_routes import transactions_bp
from app.routes.export_routes import export_bp
from app.routes.uploads_routes import uploads_bp
from app.routes.admin_routes import admin_bp

# רישום ה-Blueprints
"""""""""
app.register_blueprint(auth_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(coupons_bp)
app.register_blueprint(marketplace_bp)
app.register_blueprint(requests_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(export_bp)
app.register_blueprint(uploads_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(admin_tags_bp)
"""""""""
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(profile_bp, url_prefix='/profile')
app.register_blueprint(coupons_bp, url_prefix='/coupons')
app.register_blueprint(marketplace_bp, url_prefix='/marketplace')
app.register_blueprint(requests_bp, url_prefix='/requests')
app.register_blueprint(transactions_bp, url_prefix='/transactions')
app.register_blueprint(export_bp, url_prefix='/export')
app.register_blueprint(uploads_bp, url_prefix='/uploads')
app.register_blueprint(admin_bp, url_prefix='/admin')

# יצירת תיקיית instance אם לא קיימת
if not os.path.exists('instance'):
    os.makedirs('instance')

with app.app_context():
    db.create_all()
    # תגיות מוגדרות מראש
    predefined_tags = [
        {'name': 'מבצע', 'count': 10},
        {'name': 'הנחה', 'count': 8},
        {'name': 'חדש', 'count': 5},
    ]
    for tag_data in predefined_tags:
        tag = Tag.query.filter_by(name=tag_data['name']).first()
        if not tag:
            tag = Tag(name=tag_data['name'], count=tag_data['count'])
            db.session.add(tag)
            logging.info(f"נוספה תגית חדשה: {tag.name}")
        else:
            if tag.count != tag_data['count']:
                tag.count = tag_data['count']
                logging.info(f"עודכנה ספירת תגית: {tag.name} ל-{tag.count}")
    db.session.commit()

try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    logging.info(f"יצירת תיקיית ההעלאה: {app.config['UPLOAD_FOLDER']}")
except Exception as e:
    logging.error(f"שגיאה ביצירת תיקיית ההעלאה: {e}")

# הגדרת Scheduler
scheduler = BackgroundScheduler()



if __name__ == '__main__':
    if not app.debug or os.environ.get("FLASK_ENV") == "production":
        configure_scheduler()
        logging.info("Scheduler started in production mode.")

    app.run(debug=True)
