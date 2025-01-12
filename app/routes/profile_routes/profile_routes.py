# /routes/profile_routes/profile_routes.py
from app.forms import ReviewSellerForm
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models import User, UserRating
from datetime import datetime, timezone
import os
from werkzeug.utils import secure_filename

from app.forms import UserProfileForm, RateUserForm
from sqlalchemy.sql import text

profile_bp = Blueprint('profile', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


from app.models import User, UserReview  # במקום UserRating


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


