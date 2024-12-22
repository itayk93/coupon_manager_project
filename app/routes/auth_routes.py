# app/routes/auth_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from itsdangerous import SignatureExpired, BadTimeSignature
from app.extensions import db
from app.models import User
from app.forms import LoginForm, RegisterForm
from app.helpers import generate_confirmation_token, confirm_token

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = confirm_token(token)
    except SignatureExpired:
        flash('קישור האישור פג תוקף.', 'error')
        return redirect(url_for('auth.login'))
    except BadTimeSignature:
        flash('קישור האישור אינו תקין.', 'error')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()

    if user.is_confirmed:
        flash('החשבון כבר אושר. אנא התחבר.', 'success')
    else:
        user.is_confirmed = True
        user.confirmed_on = datetime.now()
        db.session.add(user)
        db.session.commit()
        flash('חשבון האימייל שלך אושר בהצלחה!', 'success')

    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        # חיפוש המשתמש לפי האימייל
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            if not user.is_confirmed:
                flash('עליך לאשר את חשבונך לפני התחברות.', 'error')
                return redirect(url_for('auth.login'))
            login_user(user, remember=form.remember.data)
            return redirect(url_for('profile.index'))
        else:
            flash('אימייל או סיסמה שגויים.', 'error')
    return render_template('login.html', form=form)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        print(f"Email entered: {form.email.data}")
        email = form.email.data.strip().lower()  # נרמול האימייל
        existing_user = User.query.filter_by(email=email).first()
        print(f"Existing user: {existing_user}")
        if existing_user:
            flash('אימייל זה כבר רשום במערכת.', 'error')
            return redirect(url_for('auth.register'))

        # יצירת משתמש חדש
        new_user = User(
            email=email,
            password=generate_password_hash(form.password.data),
            first_name=form.first_name.data.strip(),
            last_name=form.last_name.data.strip(),
            is_confirmed=False  # המשתמש עדיין לא אישר את המייל
        )
        try:
            db.session.add(new_user)
            db.session.commit()
            print(f"New user created: {new_user}")
        except Exception as e:
            db.session.rollback()
            flash('אירעה שגיאה בעת יצירת החשבון שלך.', 'error')
            print(f"Error during user creation: {e}")
            return redirect(url_for('auth.register'))

        # יצירת טוקן אישור
        token = generate_confirmation_token(new_user.email)

        # קישור לאישור
        confirm_url = url_for('auth.confirm_email', token=token, _external=True)

        # תוכן המייל
        html = render_template('emails/account_confirmation.html', user=new_user, confirmation_link=confirm_url)

        # קביעת המשתנים למייל
        sender_email = 'itayk93@gmail.com'  # כתובת המייל של השולח
        sender_name = 'MaCoupon'
        recipient_email = new_user.email  # ללא פסיק בסוף
        recipient_name = new_user.first_name  # ללא פסיק בסוף
        subject = 'אישור חשבון ב-MaCoupon'

        # קריאה לפונקציה לשליחת המייל
        try:
            send_email(
                sender_email=sender_email,
                sender_name=sender_name,
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                subject=subject,
                html_content=html
            )
            flash('נשלח אליך מייל לאישור החשבון. אנא בדוק את תיבת הדואר שלך.', 'success')
        except Exception as e:
            print(f"Error sending email: {e}")
            flash('אירעה שגיאה בשליחת המייל. נסה שוב מאוחר יותר.', 'error')

        return redirect(url_for('auth.login'))
    else:
        print("Form validation failed.")
        print(form.errors)
    return render_template('register.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('התנתקת בהצלחה.', 'info')
    return redirect(url_for('auth.login'))
