from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, DecimalField, DateField, TextAreaField, SelectField, FileField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import (
    SubmitField, StringField, DecimalField, TextAreaField, BooleanField,
    DateField, SelectMultipleField, widgets, HiddenField, PasswordField,
    IntegerField, SelectField, FloatField, FieldList, FormField
)
from wtforms.validators import (
    DataRequired, Optional, Email, EqualTo, InputRequired, Length, NumberRange
)
from wtforms import Form  # Importing Form for subforms
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import (
    SubmitField, StringField, DecimalField, TextAreaField, BooleanField,
    DateField, HiddenField, FloatField, FieldList, FormField
)
from wtforms.validators import DataRequired, Optional, Email, EqualTo, InputRequired, Length, NumberRange

from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional
from flask_wtf.file import FileField, FileAllowed

# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    SubmitField, StringField, DecimalField, TextAreaField, BooleanField,
    DateField, SelectField, FloatField, IntegerField, HiddenField
)
from wtforms.validators import (
    DataRequired, Optional, Email, EqualTo, InputRequired, Length, NumberRange
)

# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    SubmitField, StringField, DecimalField, TextAreaField, BooleanField,
    DateField, SelectField, FloatField, IntegerField, HiddenField
)
from wtforms.validators import (
    DataRequired, Optional, Email, EqualTo, InputRequired, Length, NumberRange
)

# forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, FloatField, TextAreaField, BooleanField, DateField, SelectField, SubmitField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange

from flask_wtf import FlaskForm
from wtforms import (
    SubmitField, StringField, DecimalField, TextAreaField, BooleanField,
    DateField, SelectField
)
from wtforms.validators import (
    DataRequired, Optional, Length, NumberRange
)

from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, SubmitField, SelectField
from wtforms.validators import DataRequired, Optional

# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    SubmitField, StringField, SelectField, FloatField, DecimalField
)
from wtforms.validators import (
    DataRequired, Optional, Length, NumberRange, ValidationError
)

from flask_wtf import FlaskForm
from wtforms import SubmitField

# forms.py

from flask_wtf import FlaskForm
from wtforms import FloatField, SubmitField
from wtforms.validators import DataRequired, NumberRange

# forms.py
# forms.py

from flask_wtf import FlaskForm
from wtforms import SubmitField

from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import DataRequired

from flask_wtf import FlaskForm
from wtforms import SubmitField
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, FloatField, BooleanField, DateField, FormField, FieldList
from wtforms.validators import DataRequired, Optional

from flask_wtf import FlaskForm
from wtforms import (
    SubmitField, StringField, DecimalField, TextAreaField, BooleanField,
    DateField, SelectField, FloatField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange, ValidationError


# forms.py


class CouponForm(FlaskForm):
    company_id = SelectField(
        'שם החברה',
        choices=[],  # הבחירות ימולאו בנתיב
        validators=[DataRequired(message="יש לבחור חברה.")]
    )
    other_company = StringField(
        'שם חברה חדשה',
        validators=[Optional(), Length(max=255)]
    )
    tag_id = SelectField(
        'תגית',
        choices=[],  # הבחירות ימולאו בנתיב
        validators=[Optional()]
    )
    other_tag = StringField(
        'תגית חדשה',
        validators=[Optional(), Length(max=255)]
    )
    code = StringField(
        'קוד קופון (שם מוצר)',
        validators=[DataRequired(message="חובה למלא קוד קופון.")]
    )
    value = FloatField(
        'כמה הקופון שווה בפועל',
        validators=[
            Optional(),  # שנהנו מ-DataRequired ל-Optional
            NumberRange(min=0, message="המחיר חייב להיות חיובי.")
        ]
    )
    cost = FloatField(
        'כמה שילמת על הקופון',
        validators=[
            Optional(),  # שנהנו מ-DataRequired ל-Optional
            NumberRange(min=0, message="הערך חייב להיות חיובי.")
        ]
    )
    discount_percentage = FloatField(
        'אחוז הנחה',
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="אחוז ההנחה חייב להיות בין 0 ל-100.")
        ]
    )
    expiration = DateField(
        'תאריך תפוגה',
        validators=[Optional()]
    )
    description = TextAreaField(
        'תיאור הקופון',
        validators=[Optional()]
    )
    is_one_time = BooleanField('קוד לשימוש חד פעמי')
    purpose = StringField(
        'מטרת הקופון',
        validators=[Optional(), Length(max=255)]
    )
    coupon_image = FileField('תמונה של הקופון', validators=[Optional()])  # הוסף שדה העלאת תמונה
    upload_image = SubmitField('העלה תמונה')  # כפתור להעלאת תמונה
    submit_coupon = SubmitField('הוסף קופון')  # כפתור להוספת קופון

    def validate(self, extra_validators=None):
        if not super(CouponForm, self).validate(extra_validators=extra_validators):
            return False

        fields_filled = [
            bool(self.cost.data),
            bool(self.value.data),
            bool(self.discount_percentage.data)
        ]
        if fields_filled.count(True) < 2:
            error_message = 'יש למלא לפחות שניים מהשדות: מחיר קופון, ערך קופון, אחוז הנחה.'
            self.cost.errors.append(error_message)
            self.value.errors.append(error_message)
            self.discount_percentage.errors.append(error_message)
            return False
        return True


class BulkCouponForm(FlaskForm):
    company_id = SelectField(
        'שם החברה',
        choices=[],
        coerce=str,
        validators=[DataRequired(message="יש לבחור חברה.")]
    )
    other_company = StringField(
        'שם חברה חדשה',
        validators=[Optional(), Length(max=255)]
    )
    tag_id = SelectField(
        'תגית',
        choices=[],
        coerce=str,
        validators=[DataRequired(message="יש לבחור תגית.")]
    )
    other_tag = StringField(
        'תגית חדשה',
        validators=[Optional(), Length(max=255)]
    )
    code = StringField(
        'קוד קופון',
        validators=[DataRequired(message="חובה למלא קוד קופון.")]
    )
    value = FloatField(
        'ערך הקופון',
        validators=[
            DataRequired(message="חובה למלא ערך קופון."),
            NumberRange(min=0, message="הערך חייב להיות חיובי.")
        ]
    )
    cost = FloatField(
        'עלות הקופון',
        validators=[
            DataRequired(message="חובה למלא את העלות."),
            NumberRange(min=0, message="העלות חייבת להיות חיובית.")
        ]
    )
    expiration = DateField(
        'תאריך תפוגה',
        validators=[Optional()]
    )
    is_one_time = BooleanField(
        'קוד לשימוש חד פעמי'
    )
    purpose = StringField(
        'מטרת הקופון',
        validators=[Optional(), Length(max=255)]
    )


class AddCouponsBulkForm(FlaskForm):
    coupons = FieldList(FormField(CouponForm), min_entries=1)
    submit = SubmitField('הוסף קופונים')


class UploadCouponsForm(FlaskForm):
    file = FileField('בחר קובץ Excel להעלאה (קובץ מסוג xlsx):', validators=[
        FileRequired(message='יש לבחור קובץ להעלאה.'),
        FileAllowed(['xlsx'], 'רק קבצי Excel (.xlsx) מותרים.')
    ])
    submit = SubmitField('העלה קובץ')


class DeleteCouponForm(FlaskForm):
    submit = SubmitField('מחק קופון')


class ConfirmDeleteForm(FlaskForm):
    submit = SubmitField('אשר מחיקה')
    cancel = SubmitField('ביטול')


class DeleteCouponsForm(FlaskForm):
    coupon_ids = SelectMultipleField(
        'בחר קופונים למחיקה',
        coerce=int,  # מוודא שה-ID יהיה מסוג int
        option_widget=widgets.CheckboxInput(),
        widget=widgets.ListWidget(prefix_label=False),
        default=[]  # הגדרת ברירת מחדל לרשימה ריקה
    )
    submit = SubmitField('מחק קופונים')


# forms.py

class SellCouponForm(FlaskForm):
    company_select = SelectField(
        'איזה קופון תרצו למכור?',
        choices=[],
        validators=[DataRequired(message="יש לבחור חברה.")]
    )
    other_company = StringField(
        'שם חברה חדשה',
        validators=[Optional(), Length(max=255)]
    )
    tag_select = SelectField(
        'קטגוריה',
        choices=[],
        validators=[Optional()]
    )
    other_tag = StringField(
        'קטגוריה חדשה',
        validators=[Optional(), Length(max=255)]
    )
    code = StringField(
        'קוד קופון (לא חובה למלא כרגע)',
        validators=[Optional()]
    )
    cost = DecimalField(
        'כמה היית רוצה לקבל על הקופון?',
        validators=[
            DataRequired(message="חובה למלא את המחיר."),
            NumberRange(min=0, message="המחיר חייב להיות חיובי.")
        ],
        places=2
    )
    value = DecimalField(
        'כמה הקופון שווה בפועל?',
        validators=[
            DataRequired(message="חובה למלא את הערך."),
            NumberRange(min=0, message="הערך חייב להיות חיובי.")
        ],
        places=2
    )
    discount_percentage = DecimalField(
        'אחוז הנחה',
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="אחוז ההנחה חייב להיות בין 0 ל-100.")
        ],
        places=2
    )
    expiration = DateField(
        'תאריך תפוגה',
        format='%Y-%m-%d',
        validators=[Optional()]
    )
    description = TextAreaField(
        'תיאור הקופון',
        validators=[Optional()]
    )
    is_one_time = BooleanField('קופון חד פעמי')
    purpose = StringField(
        'מטרת הקופון',
        validators=[Optional(), Length(max=255)]
    )
    submit = SubmitField('הוסף קופון למכירה')

    def validate(self, **kwargs):
        if not super(SellCouponForm, self).validate(**kwargs):
            return False

        fields_filled = [
            bool(self.cost.data),
            bool(self.value.data),
            bool(self.discount_percentage.data)
        ]
        if fields_filled.count(True) < 2:
            error_message = 'יש למלא לפחות שניים מהשדות: מחיר קופון, ערך קופון, אחוז הנחה.'
            self.cost.errors.append(error_message)
            self.value.errors.append(error_message)
            self.discount_percentage.errors.append(error_message)
            return False
        return True
    
class EditCouponForm(FlaskForm):
    company = StringField('שם החברה:', validators=[InputRequired(message="חובה למלא את שם החברה.")])
    code = StringField('קוד קופון (שם מוצר):', validators=[InputRequired(message="חובה למלא את קוד הקופון.")])
    value = FloatField('ערך הקופון (בש"ח):', validators=[InputRequired(message="חובה למלא את ערך הקופון."),
                                                         NumberRange(min=0, message="הערך חייב להיות 0 או גדול ממנו.")])
    cost = FloatField('כמה שילמת עבור הקופון (בש"ח):', validators=[InputRequired(message="חובה למלא את העלות."),
                                                                   NumberRange(min=0,
                                                                               message="העלות חייבת להיות 0 או גדולה ממנה.")])
    expiration = DateField('תאריך תפוגה:', format='%Y-%m-%d', validators=[Optional()])
    tags = StringField('תגיות (הפרד עם פסיק):', validators=[Optional()])
    description = TextAreaField('תיאור הקופון:', validators=[Optional()])
    is_one_time = BooleanField('קוד לשימוש חד פעמי')
    purpose = StringField('מטרת הקופון:', validators=[Optional()])
    submit = SubmitField('שמור שינויים')


class RegisterForm(FlaskForm):
    first_name = StringField('שם פרטי', validators=[InputRequired(), Length(min=2, max=150)])
    last_name = StringField('שם משפחה', validators=[InputRequired(), Length(min=2, max=150)])
    email = StringField('Email', validators=[InputRequired(), Email(message='אימייל לא תקין'), Length(max=150)])
    password = PasswordField('סיסמה',
                             validators=[InputRequired(), Length(min=8, message='סיסמה חייבת להכיל לפחות 8 תווים')])
    confirm_password = PasswordField('אישור סיסמה',
                                     validators=[InputRequired(), EqualTo('password', message='הסיסמאות לא תואמות')])
    submit = SubmitField('הרשמה')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[InputRequired(), Email(message='אימייל לא תקין'), Length(max=150)])
    password = PasswordField('סיסמה', validators=[InputRequired()])
    remember = BooleanField('זכור אותי')
    submit = SubmitField('התחברות')


class ProfileForm(FlaskForm):
    first_name = StringField('שם פרטי', validators=[DataRequired()])  # שם פרטי
    last_name = StringField('שם משפחה', validators=[DataRequired()])  # שם משפחה
    age = IntegerField('גיל', validators=[Optional()])
    gender = SelectField('מין', choices=[
        ('male', 'זכר'),
        ('female', 'נקבה'),
        ('other', 'אחר')
    ], validators=[Optional()])
    submit = SubmitField('שמור')


from app.models import Coupon  # הוסף שורה זו בראש הקובץ, יחד עם שאר הייבואים.

class ApproveTransactionForm(FlaskForm):
    seller_phone = StringField('מספר טלפון', validators=[DataRequired()])
    code = StringField('קוד קופון', validators=[DataRequired(), Length(max=255)])
    submit = SubmitField('אשר עסקה')

    def validate_code(self, field):
        if Coupon.query.filter_by(code=field.data.strip()).first():
            raise ValidationError('קוד קופון זה כבר קיים. אנא בחר קוד אחר.')


class MarkCouponAsUsedForm(FlaskForm):
    submit = SubmitField('סמן כנוצל')


class UpdateCouponUsageForm(FlaskForm):
    used_amount = FloatField('כמות שימוש', validators=[DataRequired(), NumberRange(min=0.0)])
    submit = SubmitField('עדכן שימוש עם MultiPass')


class BuySlotsForm(FlaskForm):
    slot_amount = HiddenField('slot_amount', validators=[DataRequired()])
    submit = SubmitField('רכוש סלוטים')


# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    SubmitField, StringField, DecimalField, SelectField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange

class RequestCouponForm(FlaskForm):
    company = SelectField(
        'שם החברה',
        choices=[],  # הבחירות ימולאו בצד השרת
        validators=[DataRequired(message="יש לבחור חברה.")]
    )
    other_company = StringField(
        'שם חברה חדשה',
        validators=[Optional(), Length(max=255)]
    )
    cost = DecimalField(
        'מחיר קופון (עלות)',
        validators=[
            DataRequired(message="חובה למלא את העלות."),
            NumberRange(min=0, message="העלות חייבת להיות חיובית.")
        ],
        places=2
    )
    value = DecimalField(
        'ערך מבוקש',
        validators=[
            Optional(),
            NumberRange(min=0, message="הערך חייב להיות חיובי.")
        ],
        places=2
    )
    discount_percentage = DecimalField(
        'אחוז הנחה מבוקש',
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="אחוז ההנחה חייב להיות בין 0 ל-100.")
        ],
        places=2
    )
    code = StringField(
        'קוד קופון',
        validators=[Optional(), Length(max=255)]  # קוד אינו חובה
    )
    submit = SubmitField('בקש קופון')

    def validate(self, extra_validators=None):
        if not super(RequestCouponForm, self).validate(extra_validators=extra_validators):
            return False

        # וידוא שמולאו לפחות שניים מהשדות: cost, value, discount_percentage
        fields_filled = [
            bool(self.cost.data),
            bool(self.value.data),
            bool(self.discount_percentage.data)
        ]
        if fields_filled.count(True) < 2:
            error_message = 'יש למלא לפחות שניים מהשדות: מחיר קופון, ערך מבוקש, אחוז הנחה מבוקש.'
            self.cost.errors.append(error_message)
            self.value.errors.append(error_message)
            self.discount_percentage.errors.append(error_message)
            return False

        return True


class UpdateMultipassForm(FlaskForm):
    submit = SubmitField('עדכן נתונים מ-Multipass')

class SMSInputForm(FlaskForm):
    sms_text = TextAreaField('תוכן ההודעה שקיבלת ב-SMS:', validators=[Optional()])
    submit_sms = SubmitField('הבא')


class DeleteCouponRequestForm(FlaskForm):
    submit = SubmitField('מחק בקשה')

from flask_wtf import FlaskForm
from wtforms import FileField, SubmitField
from wtforms.validators import DataRequired

class ImageUploadForm(FlaskForm):
    image_file = FileField('בחר תמונה', validators=[Optional()])
    submit_image = SubmitField('שלח תמונה')

class UploadImageForm(FlaskForm):
    coupon_image = FileField(
        'העלה תמונה של הקופון',
        validators=[
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'רק קבצי תמונה מותרים!'),
            FileRequired('חובה להעלות תמונה.')
        ]
    )
    submit_upload_image = SubmitField('שלח תמונה')

# forms.py
from flask_wtf import FlaskForm
from wtforms import SubmitField

class MarkCouponAsFullyUsedForm(FlaskForm):
    submit = SubmitField('סימן הקופון כ"נוצל לגמרי"')

class TagManagementForm(FlaskForm):
    name = StringField(
        'שם התגית',
        validators=[
            DataRequired(message="חובה למלא שם תגית."),
            Length(max=50, message="שם התגית לא יכול להיות ארוך מ-50 תווים.")
        ]
    )
    submit = SubmitField('צור תגית חדשה')

# forms.py

from flask_wtf import FlaskForm
from wtforms import SubmitField, HiddenField
from wtforms.validators import DataRequired

class DeleteTagForm(FlaskForm):
    tag_id = HiddenField('Tag ID', validators=[DataRequired()])
    submit = SubmitField('מחק תגית')

from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, HiddenField
from wtforms.validators import DataRequired, Length

class CompanyManagementForm(FlaskForm):
    name = StringField(
        'שם החברה',
        validators=[
            DataRequired(message="חובה למלא שם חברה."),
            Length(max=255, message="שם החברה לא יכול להיות ארוך מ-255 תווים.")
        ]
    )
    submit = SubmitField('צור חברה חדשה')

class DeleteCompanyForm(FlaskForm):
    company_id = HiddenField('Company ID', validators=[DataRequired()])
    submit = SubmitField('מחק חברה')

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField, HiddenField
from wtforms.validators import DataRequired

from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import DataRequired

class CouponTagForm(FlaskForm):
    coupon_id = SelectField(
        'בחר קופון',
        coerce=int,
        validators=[DataRequired(message="חובה לבחור קופון.")]
    )
    tag_id = SelectField(
        'בחר תגית',
        coerce=int,
        validators=[DataRequired(message="חובה לבחור תגית.")]
    )
    submit = SubmitField('עדכן תגית')

# app/forms.py

from flask_wtf import FlaskForm
from wtforms import SelectField, HiddenField, SubmitField
from wtforms.validators import DataRequired

class ManageCouponTagForm(FlaskForm):
    coupon_id = HiddenField('Coupon ID', validators=[DataRequired()])
    tag_id = SelectField('תגית', coerce=int, validators=[DataRequired()])
    submit = SubmitField('עדכן תגית')

# app/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, IntegerField, FileField
from wtforms.validators import DataRequired, NumberRange, Optional
from flask_wtf.file import FileAllowed

class UserProfileForm(FlaskForm):
    """
    טופס לעדכון פרופיל משתמש (תיאור קצר + אפשרות להעלאת תמונה).
    """
    profile_description = TextAreaField('ספר על עצמך בקצרה', validators=[Optional()])
    profile_image = FileField(
        'העלה תמונת פרופיל',
        validators=[
            Optional(),
            FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'רק קבצי תמונה מותרים!')
        ]
    )
    submit = SubmitField('שמור פרופיל')


class RateUserForm(FlaskForm):
    """
    טופס דירוג משתמש + הוספת הערה (בפעם אחת).
    """
    rating = IntegerField('דירוג (1-5)', validators=[
        DataRequired(message='חובה לתת דירוג'),
        NumberRange(min=1, max=5, message='הדירוג חייב להיות בין 1 ל-5')
    ])
    comment = TextAreaField('הערה (אופציונלי)', validators=[Optional()])
    submit = SubmitField('שלח דירוג')

# forms.py

from flask_wtf import FlaskForm
from wtforms import IntegerField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional

class ReviewSellerForm(FlaskForm):
    rating = IntegerField(
        'דירוג (1 עד 5)',
        validators=[
            DataRequired(message="חובה להזין דירוג"),
            NumberRange(min=1, max=5, message="הדירוג צריך להיות בין 1 ל-5")
        ]
    )
    comment = TextAreaField('הערה (אופציונלי)', validators=[Optional()])
    submit = SubmitField('שלח ביקורת')
