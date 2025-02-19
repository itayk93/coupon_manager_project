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
from wtforms.validators import DataRequired, Optional, Length, NumberRange, Regexp

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
        'קוד קופון',
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
    coupon_image = FileField('תמונה של הקופון', validators=[Optional()])
    upload_image = SubmitField('העלה תמונה')  # כפתור להעלאת תמונה
    
    # Relevant for specific coupons
    cvv = StringField(
        'CVV',
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות.")
        ]
    )
    card_exp = StringField(
        'תאריך כרטיס (MM/YY)',
        validators=[
            Optional(),
            Regexp(r'^(0[1-9]|1[0-2])/[0-9]{2}$',
                   message="יש להזין תאריך בפורמט MM/YY (לדוגמה: 12/29).")
        ]
    )

    submit_coupon = SubmitField('הוספת קופון')  # כפתור להוספת קופון

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
        validators=[Optional()]
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

    # Relevant for specific coupons
    cvv = StringField(
        'CVV',
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות.")
        ]
    )
    card_exp = StringField(
        'תאריך כרטיס (MM/YY)',
        validators=[
            Optional(),
            Regexp(r'^(0[1-9]|1[0-2])/[0-9]{2}$',
                   message="יש להזין תאריך כרטיס בפורמט MM/YY.")
        ]
    )

class AddCouponsBulkForm(FlaskForm):
    coupons = FieldList(FormField(CouponForm), min_entries=1)
    cvv = StringField('CVV', validators=[Optional()])
    card_exp = StringField('תוקף כרטיס', validators=[Optional()])
    submit = SubmitField('הוספת קופונים')


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
        'כמה הקופון שווה בפועל?',
        validators=[
            DataRequired(message="חובה למלא את המחיר."),
            NumberRange(min=0, message="המחיר חייב להיות חיובי.")
        ],
        places=2
    )
    value = DecimalField(
        'כמה היית רוצה לקבל על הקופון?',
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

    # Relevant for specific coupons
    cvv = StringField(
        'CVV',
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות.")
        ]
    )
    card_exp = StringField(
        'תאריך כרטיס (MM/YY)',
        validators=[
            Optional(),
            Regexp(r'^(0[1-9]|1[0-2])/[0-9]{2}$',
                   message="יש להזין תאריך כרטיס בפורמט MM/YY.")
        ]
    )
    submit = SubmitField('הוספת קופון למכירה')

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
    company_id = SelectField("חברה", choices=[], validators=[DataRequired()])
    other_company = StringField("חברה אחרת")
    code = StringField('קוד קופון:', validators=[InputRequired(message="חובה למלא את קוד הקופון.")])
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
    
    # Relevant for specific coupons
    cvv = StringField(
        'CVV',
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות.")
        ]
    )
    card_exp = StringField(
        'תאריך כרטיס (MM/YY)',
        validators=[
            Optional(),
            Regexp(r'^(0[1-9]|1[0-2])/[0-9]{2}$',
                   message="יש להזין תאריך בפורמט MM/YY.")
        ]
    )

    submit = SubmitField('שמור שינויים')


# forms.py

class RegisterForm(FlaskForm):
    first_name = StringField('שם פרטי', validators=[DataRequired(), Length(min=2, max=150)])
    last_name = StringField('שם משפחה', validators=[DataRequired(), Length(min=2, max=150)])
    email = StringField('Email', validators=[DataRequired(), Email(message='אימייל לא תקין'), Length(max=150)])
    password = PasswordField('סיסמה', validators=[DataRequired(), Length(min=8, message='סיסמה חייבת לפחות 8 תווים')])
    confirm_password = PasswordField('אישור סיסמה',
                                     validators=[DataRequired(), EqualTo('password', message='סיסמאות לא תואמות')])

    # gender - ערך חובה
    gender = SelectField(
        'מין',
        choices=[
            ('male', 'זכר'),
            ('female', 'נקבה'),
            ('other', 'אחר')
        ],
        validators=[DataRequired(message="יש לבחור מין")]
    )

    submit = SubmitField('הרשמה')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[InputRequired(), Email(message='אימייל לא תקין'), Length(max=150)])
    password = PasswordField('סיסמה', validators=[InputRequired()])
    remember = BooleanField('זכור אותי')
    submit = SubmitField('התחברות')


class ProfileForm(FlaskForm):
    first_name = StringField('שם פרטי', validators=[DataRequired()])
    last_name = StringField('שם משפחה', validators=[DataRequired()])
    age = IntegerField('גיל', validators=[Optional()])
    gender = SelectField(
        'מין',
        # הערך (value) הוא באנגלית, התווית (label) בעברית
        choices=[
            ('male', 'זכר'),
            ('female', 'נקבה'),
            ('other', 'אחר')
        ],
        validators=[Optional()]
    )
    usage_explanation = TextAreaField('Usage Explanation')  # Add this if missing
    submit = SubmitField('שמור')


from app.models import Coupon 
from wtforms.validators import DataRequired, Optional, Length, Regexp, ValidationError

class ApproveTransactionForm(FlaskForm):
    seller_phone = StringField(
        'מספר טלפון',
        validators=[
            DataRequired(message="יש להזין מספר טלפון."),
            Regexp(r'^0\d{2}-\d{7}$', message="מספר הטלפון חייב להיות בפורמט 0xx-xxxxxxx.")
        ]
    )
    
    code = StringField('קוד קופון', validators=[Optional(), Length(max=255)])  # קוד קופון לא חובה
    
    cvv = StringField(
        'CVV',
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות.")
        ]
    )
    
    card_exp = StringField(
        'תאריך כרטיס (MM/YY)',
        validators=[
            Optional(),
            Regexp(r'^(0[1-9]|1[0-2])/[0-9]{2}$', message="יש להזין תאריך בפורמט MM/YY (לדוגמה: 12/29).")
        ]
    )
    
    submit = SubmitField('אשר עסקה')

    def validate_code(self, field):
        if field.data and Coupon.query.filter_by(code=field.data.strip()).first():
            raise ValidationError('קוד קופון זה כבר קיים. אנא בחר קוד אחר.')


from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp, Optional

class SellerAddCouponCodeForm(FlaskForm):
    coupon_code = StringField(
        'קוד קופון',
        validators=[
            DataRequired(message="חובה עליך להקליד קוד קופון כי העסקה כבר בוצעה והקונה אישר את העברת הכסף"),
            Length(min=4, max=20)
        ]
    )
    card_exp = StringField(
        'תוקף הכרטיס (MM/YY)',
        validators=[
            Optional(),
            Regexp(r'^\d{2}/\d{2}$', message="פורמט חייב להיות MM/YY")
        ]
    )
    cvv = StringField(
        'CVV',
        validators=[
            Optional(),
            Regexp(r'^\d{3,4}$', message="ה-CVV חייב להיות 3 או 4 ספרות")
        ]
    )
    submit = SubmitField('שמור קוד קופון')

class MarkCouponAsUsedForm(FlaskForm):
    submit = SubmitField('סמן כנוצל')


class UpdateCouponUsageForm(FlaskForm):
    used_amount = FloatField('כמות שימוש', validators=[DataRequired(), NumberRange(min=0.0)])
    submit = SubmitField('עדכון אוטומטי')


class BuySlotsForm(FlaskForm):
    slot_amount = HiddenField('slot_amount', validators=[DataRequired()])
    submit = SubmitField('רכישת סלוטים')


# forms.py

from flask_wtf import FlaskForm
from wtforms import (
    SubmitField, StringField, DecimalField, SelectField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange

from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, TextAreaField, SelectField, SubmitField
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
    description = TextAreaField(
        'הסבר נוסף על הבקשה',
        validators=[Optional(), Length(max=1000)]
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
    submit = SubmitField('עדכון נתונים מ-Multipass')

class SMSInputForm(FlaskForm):
    sms_text = TextAreaField('תוכן ההודעה שהתקבלה ב-SMS:', validators=[Optional()])
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
    auto_download_details = SelectField("הורדה אוטומטית", choices=[], coerce=str)  # שדה חדש

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

# app/forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, FloatField, RadioField, TextAreaField, SelectField, SubmitField
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange

class OfferCouponForm(FlaskForm):
    seller_message = TextAreaField(
        "הודעה למבקש הקופון (אופציונלי)",
        validators=[Optional()]  # לא חובה
    )
    # רדיובטן לבחירה בין "existing" או "new"
    offer_choice = RadioField(
        "בחר אופן הצעת קופון",
        choices=[('existing', 'קופון קיים'), ('new', 'קופון חדש')],
        default='existing',
        validators=[DataRequired(message="יש לבחור קופון קיים או חדש.")]
    )

    # שדות כשבוחרים "new"
    company_select = SelectField(
        'שם החברה',
        choices=[],
        validators=[Optional()]
    )
    other_company = StringField(
        'שם חברה חדשה',
        validators=[Optional(), Length(max=255)]
    )
    value = FloatField(
        "ערך מקורי (בש\"ח)",
        validators=[
            Optional(),
            NumberRange(min=0, message="הערך חייב להיות >= 0.")
        ]
    )
    cost = FloatField(
        "מחיר מבוקש (בש\"ח)",
        validators=[
            Optional(),
            NumberRange(min=0, message="המחיר חייב להיות >= 0.")
        ]
    )

    submit = SubmitField("שלח הצעה")

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length

class ForgotPasswordForm(FlaskForm):
    email = StringField('אימייל', validators=[DataRequired(), Email(message="כתובת אימייל לא תקינה")])
    submit = SubmitField('שליחת הבקשה לשחזור הסיסמה')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('סיסמה חדשה', validators=[
        DataRequired(),
        Length(min=8, message='הסיסמה צריכה להיות באורך של 8 תווים לפחות.')
    ])
    confirm_password = PasswordField('אישור סיסמה חדשה', validators=[
        DataRequired(),
        EqualTo('password', message='הסיסמאות לא תואמות.')
    ])
    submit = SubmitField('אפס סיסמה')

# forms.py
class UsageExplanationForm(FlaskForm):
    usage_explanation = TextAreaField('פירוט שימוש', validators=[DataRequired()])
    submit_usage_explanation = SubmitField('שלח')

from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import DataRequired
from flask_wtf import FlaskForm
from wtforms import TextAreaField, StringField, SubmitField
from wtforms.validators import DataRequired, Optional, URL

class AdminMessageForm(FlaskForm):
    message_text = TextAreaField("תוכן ההודעה", validators=[DataRequired()])
    link_url = StringField("קישור (אופציונלי)", validators=[Optional(), URL(message="כתובת לא תקינה")])
    link_text = StringField("טקסט לכפתור (אופציונלי)", validators=[Optional()])
    submit = SubmitField("שמור הודעה")

from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, DecimalField, IntegerField, RadioField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional

from wtforms.fields import DateField  # ייבוא שדה תאריך

# טפסים עבור תהליכי הצעות קפה

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, BooleanField, DecimalField, IntegerField, DateField, \
    HiddenField
from wtforms.validators import DataRequired, Optional, NumberRange


class CoffeeOfferForm(FlaskForm):
    discount_percent = DecimalField("אחוז הנחה", validators=[Optional(), NumberRange(min=0, max=100)])
    customer_group = SelectField("דרגת חבר מועדון", choices=[("Connoisseur", "Connoisseur"), ("Expert", "Expert"),
                                                             ("Ambassador", "Ambassador")], validators=[Optional()])
    points_offered = IntegerField("נקודות נספרסו", validators=[Optional()])
    expiration_date = DateField("תאריך תפוגה", format="%Y-%m-%d", validators=[DataRequired()])
    description = TextAreaField("תיאור", validators=[Optional()])

    # ✅ השדות החסרים:
    is_buy_offer = BooleanField("האם מדובר בבקשת רכישה?")
    desired_discount = DecimalField("אחוז הנחה מבוקש", validators=[Optional(), NumberRange(min=0, max=100)])
    buyer_description = TextAreaField("תיאור הבקשה", validators=[Optional()])

    offer_type = HiddenField("offer_type")  # כדי לאחסן אם מדובר במוכר או קונה


class ApproveCoffeeTransactionForm(FlaskForm):
    seller_phone = StringField(
        'מספר טלפון',
        validators=[DataRequired(), Regexp(r'^0\d{2}-\d{7}$', message="פורמט: 0xx-xxxxxxx")]
    )
    submit = SubmitField('אשר עסקה')


class SellerAddCoffeeOfferCodeForm(FlaskForm):
    coffee_offer_code = StringField('קוד הצעת קפה', validators=[DataRequired(), Length(min=4, max=20)])
    submit = SubmitField('שמור קוד הצעה')


class CoffeeImageUploadForm(FlaskForm):
    offer_image = FileField('העלה תמונה של הצעת הקפה', validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'רק קבצי תמונה מותרים!')])
    submit_upload = SubmitField('העלה תמונה')
