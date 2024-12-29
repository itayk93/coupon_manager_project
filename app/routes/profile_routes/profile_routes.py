# /routes/profile_routes/profile_routes.py

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, UserRating
from datetime import datetime, timezone
import os
from werkzeug.utils import secure_filename

from app.forms import UserProfileForm, RateUserForm

profile_bp = Blueprint('profile', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@profile_bp.route('/profile/<int:user_id>', methods=['GET'])
def profile_view(user_id):
    """
    צפייה בפרופיל של משתמש אחר או של עצמך (כולל הצגת דירוגים והערות).
    """
    user = User.query.get_or_404(user_id)

    # שליפת כל הדירוגים שהמשתמש קיבל
    all_ratings = UserRating.query.filter_by(rated_user_id=user.id).all()

    # חישוב ממוצע דירוג (אם תרצה)
    if len(all_ratings) > 0:
        avg_rating = sum([r.rating_value for r in all_ratings]) / len(all_ratings)
    else:
        avg_rating = None

    return render_template(
        'profile/user_profile.html',
        user=user,
        ratings=all_ratings,
        avg_rating=avg_rating
    )


@profile_bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """
    עריכת פרופיל המשתמש המחובר: תיאור קצר + תמונת פרופיל.
    """
    form = UserProfileForm()

    if request.method == 'POST':
        if form.validate_on_submit():
            # עדכון התיאור
            current_user.profile_description = form.profile_description.data

            # העלאת תמונה (אם הועלתה)
            if form.profile_image.data:
                file = form.profile_image.data
                if allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # שמירה בנתיב קבוע בתוך static/uploads, למשל
                    upload_path = os.path.join('app', 'static', 'uploads', 'profiles')
                    os.makedirs(upload_path, exist_ok=True)
                    save_path = os.path.join(upload_path, filename)
                    file.save(save_path)

                    # שמירת הנתיב בבסיס הנתונים
                    current_user.profile_image = f'static/uploads/profiles/{filename}'
                else:
                    flash('סוג קובץ לא תקין. יש להעלות תמונה בפורמט jpg/png/gif', 'danger')
                    return redirect(url_for('profile.edit_profile'))

            db.session.commit()
            flash('פרופיל עודכן בהצלחה!', 'success')
            return redirect(url_for('profile.profile_view', user_id=current_user.id))
        else:
            flash('נא לתקן את השגיאות בטופס.', 'danger')

    # מילוי ערכים קיימים
    if request.method == 'GET':
        form.profile_description.data = current_user.profile_description

    return render_template('profile/edit_profile.html', form=form)


@profile_bp.route('/rate_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def rate_user(user_id):
    """
    כתיבת דירוג למשתמש אחר. משתמש יכול לדרג משתמש אחר רק פעם אחת.
    """
    if user_id == current_user.id:
        flash('אינך יכול לדרג את עצמך!', 'warning')
        return redirect(url_for('profile.profile_view', user_id=user_id))

    user_to_rate = User.query.get_or_404(user_id)
    form = RateUserForm()

    # בדיקה האם כבר קיים דירוג של current_user -> user_id
    existing_rating = UserRating.query.filter_by(
        rated_user_id=user_to_rate.id,
        rating_user_id=current_user.id
    ).first()
    if existing_rating:
        flash('כבר דירגת את המשתמש הזה בעבר.', 'warning')
        return redirect(url_for('profile.profile_view', user_id=user_to_rate.id))

    if form.validate_on_submit():
        rating_value = form.rating_value.data
        rating_comment = form.rating_comment.data

        new_rating = UserRating(
            rated_user_id=user_to_rate.id,
            rating_user_id=current_user.id,
            rating_value=rating_value,
            rating_comment=rating_comment
        )
        db.session.add(new_rating)
        db.session.commit()

        flash('הדירוג נשלח בהצלחה!', 'success')
        return redirect(url_for('profile.profile_view', user_id=user_to_rate.id))

    return render_template('profile/rate_user.html', form=form, user_to_rate=user_to_rate)
