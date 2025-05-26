# Flask-WTF
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired

# WTForms - Fields
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    BooleanField,
    DecimalField,
    DateField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
    HiddenField,
    IntegerField,
    FloatField,
    FieldList,
    FormField,
    RadioField,
)

# WTForms - Validators
from wtforms.validators import (
    DataRequired,
    Optional,
    Email,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    Regexp,
    ValidationError,
    URL,
)

# WTForms - Widgets
from wtforms import widgets

# Additional imports
from wtforms.fields import DateField  # Additional date field import

# Additional models
from app.models import Coupon


class CouponForm(FlaskForm):
    company_id = SelectField(
        "שם החברה",
        choices=[],  # הבחירות ימולאו בנתיב
        validators=[DataRequired(message="יש לבחור חברה.")],
    )
    other_company = StringField(
        "שם חברה חדשה", validators=[Optional(), Length(max=255)]
    )
    source = StringField(
        "מאיפה קיבלת את הקופון", validators=[Optional(), Length(max=255)]
    )
    # NEW: BuyMe Coupon URL field – will capture the URL for BuyMe coupon
    buyme_coupon_url = StringField(
        "הכתובת של הקופון מBuyMe",
        validators=[Optional(), URL(message="בבקשה להקליד url תקין"), Length(max=255)],
    )
    tag_id = SelectField(
        "תגית", choices=[], validators=[Optional()]  # הבחירות ימולאו בנתיב
    )
    other_tag = StringField("תגית חדשה", validators=[Optional(), Length(max=255)])
    code = StringField(
        "קוד קופון", validators=[DataRequired(message="חובה למלא קוד קופון.")]
    )
    value = FloatField(
        "כמה הקופון שווה בפועל",
        validators=[
            Optional(),  # שנהנו מ-DataRequired ל-Optional
            NumberRange(min=0, message="המחיר חייב להיות חיובי."),
        ],
    )
    cost = FloatField(
        "כמה שילמת על הקופון",
        validators=[
            Optional(),  # שנהנו מ-DataRequired ל-Optional
            NumberRange(min=0, message="הערך חייב להיות חיובי."),
        ],
    )
    discount_percentage = FloatField(
        "אחוז הנחה",
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="אחוז ההנחה חייב להיות בין 0 ל-100."),
        ],
    )
    expiration = DateField("תאריך תפוגה", validators=[Optional()])
    description = TextAreaField("תיאור הקופון", validators=[Optional()])
    is_one_time = BooleanField("קוד לשימוש חד פעמי")
    purpose = StringField("מטרת הקופון", validators=[Optional(), Length(max=255)])
    coupon_image = FileField("תמונה של הקופון", validators=[Optional()])
    upload_image = SubmitField("העלה תמונה")  # כפתור להעלאת תמונה

    # Relevant for specific coupons
    cvv = StringField(
        "CVV",
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות."),
        ],
    )
    card_exp = StringField(
        "תאריך כרטיס (MM/YY)",
        validators=[
            Optional(),
            Regexp(
                r"^(0[1-9]|1[0-2])/[0-9]{2}$",
                message="יש להזין תאריך בפורמט MM/YY (לדוגמה: 12/29).",
            ),
        ],
    )

    submit_coupon = SubmitField("הוספת קופון")  # כפתור להוספת קופון

    def validate(self, extra_validators=None):
        if not super(CouponForm, self).validate(extra_validators=extra_validators):
            return False

        fields_filled = [
            bool(self.cost.data),
            bool(self.value.data),
            bool(self.discount_percentage.data),
        ]
        if fields_filled.count(True) < 2:
            error_message = (
                "יש למלא לפחות שניים מהשדות: מחיר קופון, ערך קופון, אחוז הנחה."
            )
            self.cost.errors.append(error_message)
            self.value.errors.append(error_message)
            self.discount_percentage.errors.append(error_message)
            return False
        return True


class BulkCouponForm(FlaskForm):
    company_id = SelectField(
        "שם החברה",
        choices=[],
        coerce=str,
        validators=[DataRequired(message="יש לבחור חברה.")],
    )
    other_company = StringField(
        "שם חברה חדשה", validators=[Optional(), Length(max=255)]
    )
    tag_id = SelectField("תגית", choices=[], coerce=str, validators=[Optional()])
    other_tag = StringField("תגית חדשה", validators=[Optional(), Length(max=255)])
    code = StringField(
        "קוד קופון", validators=[DataRequired(message="חובה למלא קוד קופון.")]
    )
    value = FloatField(
        "ערך הקופון",
        validators=[
            DataRequired(message="חובה למלא ערך קופון."),
            NumberRange(min=0, message="הערך חייב להיות חיובי."),
        ],
    )
    cost = FloatField(
        "עלות הקופון",
        validators=[
            DataRequired(message="חובה למלא את העלות."),
            NumberRange(min=0, message="העלות חייבת להיות חיובית."),
        ],
    )
    expiration = DateField("תאריך תפוגה", validators=[Optional()])
    is_one_time = BooleanField("קוד לשימוש חד פעמי")
    purpose = StringField("מטרת הקופון", validators=[Optional(), Length(max=255)])

    # שדות חדשים:
    source = StringField(
        "מאיפה קיבלת את הקופון", validators=[Optional(), Length(max=255)]
    )
    buyme_coupon_url = StringField(
        "הכתובת של הקופון מBuyMe",
        validators=[Optional(), URL(message="בבקשה להקליד url תקין"), Length(max=255)],
    )

    cvv = StringField(
        "CVV",
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות."),
        ],
    )
    card_exp = StringField(
        "תאריך כרטיס (MM/YY)",
        validators=[
            Optional(),
            Regexp(
                r"^(0[1-9]|1[0-2])/[0-9]{2}$",
                message="יש להזין תאריך כרטיס בפורמט MM/YY.",
            ),
        ],
    )
    submit = SubmitField("הוספת קופונים")


class AddCouponsBulkForm(FlaskForm):
    coupons = FieldList(FormField(CouponForm), min_entries=1)
    cvv = StringField("CVV", validators=[Optional()])
    card_exp = StringField("תוקף כרטיס", validators=[Optional()])
    submit = SubmitField("הוספת קופונים")


class UploadCouponsForm(FlaskForm):
    file = FileField(
        "בחר קובץ Excel להעלאה (קובץ מסוג xlsx):",
        validators=[
            FileRequired(message="יש לבחור קובץ להעלאה."),
            FileAllowed(["xlsx"], "רק קבצי Excel (.xlsx) מותרים."),
        ],
    )
    submit = SubmitField("העלה קובץ")


class DeleteCouponForm(FlaskForm):
    submit = SubmitField("מחק קופון")


class ConfirmDeleteForm(FlaskForm):
    submit = SubmitField("אשר מחיקה")
    cancel = SubmitField("ביטול")


class DeleteCouponsForm(FlaskForm):
    coupon_ids = SelectMultipleField(
        "בחר קופונים למחיקה",
        coerce=int,  # מוודא שה-ID יהיה מסוג int
        option_widget=widgets.CheckboxInput(),
        widget=widgets.ListWidget(prefix_label=False),
        default=[],  # הגדרת ברירת מחדל לרשימה ריקה
    )
    submit = SubmitField("מחק קופונים")


class SellCouponForm(FlaskForm):
    company_select = SelectField(
        "איזה קופון תרצו למכור?",
        choices=[],
        validators=[DataRequired(message="יש לבחור חברה.")],
    )
    other_company = StringField(
        "שם חברה חדשה", validators=[Optional(), Length(max=255)]
    )
    tag_select = SelectField("קטגוריה", choices=[], validators=[Optional()])
    other_tag = StringField("קטגוריה חדשה", validators=[Optional(), Length(max=255)])
    code = StringField("קוד קופון (לא חובה למלא כרגע)", validators=[Optional()])
    cost = DecimalField(
        "כמה הקופון שווה בפועל?",
        validators=[
            DataRequired(message="חובה למלא את המחיר."),
            NumberRange(min=0, message="המחיר חייב להיות חיובי."),
        ],
        places=2,
    )
    value = DecimalField(
        "כמה היית רוצה לקבל על הקופון?",
        validators=[
            DataRequired(message="חובה למלא את הערך."),
            NumberRange(min=0, message="הערך חייב להיות חיובי."),
        ],
        places=2,
    )
    discount_percentage = DecimalField(
        "אחוז הנחה",
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="אחוז ההנחה חייב להיות בין 0 ל-100."),
        ],
        places=2,
    )
    expiration = DateField("תאריך תפוגה", format="%Y-%m-%d", validators=[Optional()])
    description = TextAreaField("תיאור הקופון", validators=[Optional()])
    is_one_time = BooleanField("קופון חד פעמי")
    purpose = StringField("מטרת הקופון", validators=[Optional(), Length(max=255)])

    # Relevant for specific coupons
    cvv = StringField(
        "CVV",
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות."),
        ],
    )
    card_exp = StringField(
        "תאריך כרטיס (MM/YY)",
        validators=[
            Optional(),
            Regexp(
                r"^(0[1-9]|1[0-2])/[0-9]{2}$",
                message="יש להזין תאריך כרטיס בפורמט MM/YY.",
            ),
        ],
    )
    submit = SubmitField("הוספת קופון למכירה")

    def validate(self, **kwargs):
        if not super(SellCouponForm, self).validate(**kwargs):
            return False

        fields_filled = [
            bool(self.cost.data),
            bool(self.value.data),
            bool(self.discount_percentage.data),
        ]
        if fields_filled.count(True) < 2:
            error_message = (
                "יש למלא לפחות שניים מהשדות: מחיר קופון, ערך קופון, אחוז הנחה."
            )
            self.cost.errors.append(error_message)
            self.value.errors.append(error_message)
            self.discount_percentage.errors.append(error_message)
            return False
        return True


class EditCouponForm(FlaskForm):
    company_id = SelectField("חברה", choices=[], validators=[DataRequired()])
    other_company = StringField("חברה אחרת")
    code = StringField(
        "קוד קופון:", validators=[InputRequired(message="חובה למלא את קוד הקופון.")]
    )
    value = FloatField(
        'ערך הקופון (בש"ח):',
        validators=[
            InputRequired(message="חובה למלא את ערך הקופון."),
            NumberRange(min=0, message="הערך חייב להיות 0 או גדול ממנו."),
        ],
    )
    cost = FloatField(
        'כמה שילמת עבור הקופון (בש"ח):',
        validators=[
            InputRequired(message="חובה למלא את העלות."),
            NumberRange(min=0, message="העלות חייבת להיות 0 או גדולה ממנה."),
        ],
    )
    # שדה חדש להוספה - אחוז הנחה
    discount_percentage = FloatField(
        "אחוז הנחה",
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="אחוז ההנחה חייב להיות בין 0 ל-100."),
        ],
    )
    # שדה חדש להוספה - קישור לקופון BuyMe
    buyme_coupon_url = StringField(
        "הכתובת של הקופון מBuyMe",
        validators=[Optional(), URL(message="בבקשה להקליד url תקין"), Length(max=255)],
    )
    expiration = DateField("תאריך תפוגה:", format="%Y-%m-%d", validators=[Optional()])
    tags = StringField("תגיות (הפרד עם פסיק):", validators=[Optional()])
    description = TextAreaField("תיאור הקופון:", validators=[Optional()])
    is_one_time = BooleanField("קוד לשימוש חד פעמי")
    purpose = StringField("מטרת הקופון:", validators=[Optional()])

    # Relevant for specific coupons
    cvv = StringField(
        "CVV",
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות."),
        ],
    )
    card_exp = StringField(
        "תאריך כרטיס (MM/YY)",
        validators=[
            Optional(),
            Regexp(
                r"^(0[1-9]|1[0-2])/[0-9]{2}$", message="יש להזין תאריך בפורמט MM/YY."
            ),
        ],
    )

    submit = SubmitField("שמור שינויים")

    def validate(self, extra_validators=None):
        if not super(EditCouponForm, self).validate(extra_validators=extra_validators):
            return False

        fields_filled = [
            bool(self.cost.data),
            bool(self.value.data),
            bool(self.discount_percentage.data),
        ]
        if fields_filled.count(True) < 2:
            error_message = (
                "יש למלא לפחות שניים מהשדות: מחיר קופון, ערך קופון, אחוז הנחה."
            )
            self.cost.errors.append(error_message)
            self.value.errors.append(error_message)
            self.discount_percentage.errors.append(error_message)
            return False
        return True


class RegisterForm(FlaskForm):
    first_name = StringField(
        "שם פרטי", validators=[DataRequired(), Length(min=2, max=150)]
    )
    last_name = StringField(
        "שם משפחה", validators=[DataRequired(), Length(min=2, max=150)]
    )
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(message="אימייל לא תקין"), Length(max=150)],
    )
    password = PasswordField(
        "סיסמה",
        validators=[DataRequired(), Length(min=8, message="סיסמה חייבת לפחות 8 תווים")],
    )
    confirm_password = PasswordField(
        "אישור סיסמה",
        validators=[DataRequired(), EqualTo("password", message="סיסמאות לא תואמות")],
    )

    # gender - ערך חובה
    gender = SelectField(
        "מין",
        choices=[("male", "זכר"), ("female", "נקבה"), ("other", "אחר")],
        validators=[DataRequired(message="יש לבחור מין")],
    )

    submit = SubmitField("הרשמה")


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[InputRequired(), Email(message="אימייל לא תקין"), Length(max=150)],
    )
    password = PasswordField("סיסמה", validators=[InputRequired()])
    remember = BooleanField("זכור אותי")
    submit = SubmitField("התחברות")


class ProfileForm(FlaskForm):
    first_name = StringField("שם פרטי", validators=[DataRequired()])
    last_name = StringField("שם משפחה", validators=[DataRequired()])
    age = IntegerField("גיל", validators=[Optional()])
    gender = SelectField(
        "מין",
        # הערך (value) הוא באנגלית, התווית (label) בעברית
        choices=[("male", "זכר"), ("female", "נקבה"), ("other", "אחר")],
        validators=[Optional()],
    )
    usage_explanation = TextAreaField("Usage Explanation")  # Add this if missing
    submit = SubmitField("שמור")


class ApproveTransactionForm(FlaskForm):
    seller_phone = StringField(
        "מספר טלפון",
        validators=[
            DataRequired(message="יש להזין מספר טלפון."),
            Regexp(
                r"^0\d{2}-\d{7}$", message="מספר הטלפון חייב להיות בפורמט 0xx-xxxxxxx."
            ),
        ],
    )

    code = StringField(
        "קוד קופון", validators=[Optional(), Length(max=255)]
    )  # קוד קופון לא חובה

    cvv = StringField(
        "CVV",
        validators=[
            Optional(),
            Length(min=3, max=4, message="CVV צריך להיות בין 3 ל-4 ספרות."),
        ],
    )

    card_exp = StringField(
        "תאריך כרטיס (MM/YY)",
        validators=[
            Optional(),
            Regexp(
                r"^(0[1-9]|1[0-2])/[0-9]{2}$",
                message="יש להזין תאריך בפורמט MM/YY (לדוגמה: 12/29).",
            ),
        ],
    )

    submit = SubmitField("אשר עסקה")

    def validate_code(self, field):
        if field.data and Coupon.query.filter_by(code=field.data.strip()).first():
            raise ValidationError("קוד קופון זה כבר קיים. אנא בחר קוד אחר.")


class SellerAddCouponCodeForm(FlaskForm):
    coupon_code = StringField(
        "קוד קופון",
        validators=[
            DataRequired(
                message="חובה עליך להקליד קוד קופון כי העסקה כבר בוצעה והקונה אישר את העברת הכסף"
            ),
            Length(min=4, max=20),
        ],
    )
    card_exp = StringField(
        "תוקף הכרטיס (MM/YY)",
        validators=[
            Optional(),
            Regexp(r"^\d{2}/\d{2}$", message="פורמט חייב להיות MM/YY"),
        ],
    )
    cvv = StringField(
        "CVV",
        validators=[
            Optional(),
            Regexp(r"^\d{3,4}$", message="ה-CVV חייב להיות 3 או 4 ספרות"),
        ],
    )
    submit = SubmitField("שמור קוד קופון")


class MarkCouponAsUsedForm(FlaskForm):
    submit = SubmitField("סימון הקופון כנוצל")


class UpdateCouponUsageForm(FlaskForm):
    used_amount = FloatField(
        "כמות שימוש", validators=[DataRequired(), NumberRange(min=0.0)]
    )
    submit = SubmitField("עדכון אוטומטי")


class BuySlotsForm(FlaskForm):
    slot_amount = HiddenField("slot_amount", validators=[DataRequired()])
    submit = SubmitField("רכישת סלוטים")


class RequestCouponForm(FlaskForm):
    company = SelectField(
        "שם החברה",
        choices=[],  # הבחירות ימולאו בצד השרת
        validators=[DataRequired(message="יש לבחור חברה.")],
    )
    other_company = StringField(
        "שם חברה חדשה", validators=[Optional(), Length(max=255)]
    )
    cost = DecimalField(
        "מחיר קופון (עלות)",
        validators=[
            DataRequired(message="חובה למלא את העלות."),
            NumberRange(min=0, message="העלות חייבת להיות חיובית."),
        ],
        places=2,
    )
    value = DecimalField(
        "ערך מבוקש",
        validators=[Optional(), NumberRange(min=0, message="הערך חייב להיות חיובי.")],
        places=2,
    )
    discount_percentage = DecimalField(
        "אחוז הנחה מבוקש",
        validators=[
            Optional(),
            NumberRange(min=0, max=100, message="אחוז ההנחה חייב להיות בין 0 ל-100."),
        ],
        places=2,
    )
    code = StringField(
        "קוד קופון", validators=[Optional(), Length(max=255)]  # קוד אינו חובה
    )
    description = TextAreaField(
        "הסבר נוסף על הבקשה", validators=[Optional(), Length(max=1000)]
    )
    submit = SubmitField("בקש קופון")

    def validate(self, extra_validators=None):
        if not super(RequestCouponForm, self).validate(
            extra_validators=extra_validators
        ):
            return False

        # וידוא שמולאו לפחות שניים מהשדות: cost, value, discount_percentage
        fields_filled = [
            bool(self.cost.data),
            bool(self.value.data),
            bool(self.discount_percentage.data),
        ]
        if fields_filled.count(True) < 2:
            error_message = (
                "יש למלא לפחות שניים מהשדות: מחיר קופון, ערך מבוקש, אחוז הנחה מבוקש."
            )
            self.cost.errors.append(error_message)
            self.value.errors.append(error_message)
            self.discount_percentage.errors.append(error_message)
            return False

        return True


class UpdateMultipassForm(FlaskForm):
    submit = SubmitField("עדכון נתונים מ-Multipass")


class SMSInputForm(FlaskForm):
    sms_text = TextAreaField("תוכן ההודעה שהתקבלה ב-SMS:", validators=[Optional()])
    submit_sms = SubmitField("הבא")


class DeleteCouponRequestForm(FlaskForm):
    submit = SubmitField("מחק בקשה")


class ImageUploadForm(FlaskForm):
    image_file = FileField("בחר תמונה", validators=[Optional()])
    submit_image = SubmitField("שלח תמונה")


class UploadImageForm(FlaskForm):
    coupon_image = FileField(
        "העלה תמונה של הקופון",
        validators=[
            FileAllowed(["jpg", "jpeg", "png", "gif"], "רק קבצי תמונה מותרים!"),
            FileRequired("חובה להעלות תמונה."),
        ],
    )
    submit_upload_image = SubmitField("שלח תמונה")


class MarkCouponAsFullyUsedForm(FlaskForm):
    submit = SubmitField('סימן הקופון כ"נוצל לגמרי"')


class TagManagementForm(FlaskForm):
    name = StringField(
        "שם התגית",
        validators=[
            DataRequired(message="חובה למלא שם תגית."),
            Length(max=50, message="שם התגית לא יכול להיות ארוך מ-50 תווים."),
        ],
    )
    submit = SubmitField("צור תגית חדשה")


class DeleteTagForm(FlaskForm):
    tag_id = HiddenField("Tag ID", validators=[DataRequired()])
    submit = SubmitField("מחק תגית")


class CompanyManagementForm(FlaskForm):
    name = StringField(
        "שם החברה",
        validators=[
            DataRequired(message="חובה למלא שם חברה."),
            Length(max=255, message="שם החברה לא יכול להיות ארוך מ-255 תווים."),
        ],
    )
    submit = SubmitField("צור חברה חדשה")


class DeleteCompanyForm(FlaskForm):
    company_id = HiddenField("Company ID", validators=[DataRequired()])
    submit = SubmitField("מחק חברה")


class CouponTagForm(FlaskForm):
    coupon_id = SelectField(
        "בחר קופון", coerce=int, validators=[DataRequired(message="חובה לבחור קופון.")]
    )
    tag_id = SelectField(
        "בחר תגית", coerce=int, validators=[DataRequired(message="חובה לבחור תגית.")]
    )
    submit = SubmitField("עדכן תגית")


class ManageCouponTagForm(FlaskForm):
    coupon_id = HiddenField("Coupon ID", validators=[DataRequired()])
    tag_id = SelectField("תגית", coerce=int, validators=[DataRequired()])
    submit = SubmitField("עדכן תגית")
    auto_download_details = SelectField(
        "הורדה אוטומטית", choices=[], coerce=str
    )  # שדה חדש


class UserProfileForm(FlaskForm):
    """
    Form for updating user profile (short description + option to upload an image).
    """

    profile_description = TextAreaField("ספר על עצמך בקצרה", validators=[Optional()])
    profile_image = FileField(
        "העלה תמונת פרופיל",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png", "gif"], "רק קבצי תמונה מותרים!"),
        ],
    )
    submit = SubmitField("שמור פרופיל")


class RateUserForm(FlaskForm):
    """
    User rating form + comment addition (all at once).
    """

    rating = IntegerField(
        "דירוג (1-5)",
        validators=[
            DataRequired(message="חובה לתת דירוג"),
            NumberRange(min=1, max=5, message="הדירוג חייב להיות בין 1 ל-5"),
        ],
    )
    comment = TextAreaField("הערה (אופציונלי)", validators=[Optional()])
    submit = SubmitField("שלח דירוג")


from flask_wtf import FlaskForm
from wtforms import IntegerField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional, Length


class ReviewSellerForm(FlaskForm):
    rating = IntegerField(
        "דירוג (1-5)",
        validators=[
            DataRequired(message="חובה להזין דירוג"),
            NumberRange(min=1, max=5, message="הדירוג חייב להיות בין 1 ל-5"),
        ],
    )
    comment = TextAreaField(
        "הערה (אופציונלי)", validators=[Optional(), Length(max=1000)]
    )
    submit = SubmitField("שלח ביקורת")


class OfferCouponForm(FlaskForm):
    seller_message = TextAreaField(
        "הודעה למבקש הקופון (אופציונלי)", validators=[Optional()]  # לא חובה
    )
    # רדיובטן לבחירה בין "existing" או "new"
    offer_choice = RadioField(
        "בחר אופן הצעת קופון",
        choices=[("existing", "קופון קיים"), ("new", "קופון חדש")],
        default="existing",
        validators=[DataRequired(message="יש לבחור קופון קיים או חדש.")],
    )

    # שדות כשבוחרים "new"
    company_select = SelectField("שם החברה", choices=[], validators=[Optional()])
    other_company = StringField(
        "שם חברה חדשה", validators=[Optional(), Length(max=255)]
    )
    value = FloatField(
        'ערך מקורי (בש"ח)',
        validators=[Optional(), NumberRange(min=0, message="הערך חייב להיות >= 0.")],
    )
    cost = FloatField(
        'מחיר מבוקש (בש"ח)',
        validators=[Optional(), NumberRange(min=0, message="המחיר חייב להיות >= 0.")],
    )

    submit = SubmitField("שלח הצעה")


class ForgotPasswordForm(FlaskForm):
    email = StringField(
        "אימייל", validators=[DataRequired(), Email(message="כתובת אימייל לא תקינה")]
    )
    submit = SubmitField("שליחת הבקשה לשחזור הסיסמה")


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        "סיסמה חדשה",
        validators=[
            DataRequired(),
            Length(min=8, message="הסיסמה צריכה להיות באורך של 8 תווים לפחות."),
        ],
    )
    confirm_password = PasswordField(
        "אישור סיסמה חדשה",
        validators=[DataRequired(), EqualTo("password", message="הסיסמאות לא תואמות.")],
    )
    submit = SubmitField("אפס סיסמה")


class UsageExplanationForm(FlaskForm):
    usage_explanation = TextAreaField("פירוט שימוש", validators=[DataRequired()])
    submit_usage_explanation = SubmitField("שלח")


class AdminMessageForm(FlaskForm):
    message_text = TextAreaField("תוכן ההודעה", validators=[DataRequired()])
    link_url = StringField(
        "קישור (אופציונלי)", validators=[Optional(), URL(message="כתובת לא תקינה")]
    )
    link_text = StringField("טקסט לכפתור (אופציונלי)", validators=[Optional()])
    submit = SubmitField("שמור הודעה")


class CoffeeOfferForm(FlaskForm):
    discount_percent = DecimalField(
        "אחוז הנחה",
        validators=[Optional(), NumberRange(min=0, max=100)],
        default=None,  # Use None instead of 0 to avoid automatic value
    )
    customer_group = SelectField(
        "דרגת חבר מועדון",
        choices=[
            ("Connoisseur", "Connoisseur"),
            ("Expert", "Expert"),
            ("Ambassador", "Ambassador"),
        ],
        validators=[Optional()],
    )
    points_offered = IntegerField("נקודות נספרסו", validators=[Optional()])
    expiration_date = DateField(
        "תאריך תפוגה", format="%Y-%m-%d", validators=[DataRequired()]
    )
    description = TextAreaField("תיאור", validators=[Optional()])

    # ✅ Missing fields:
    is_buy_offer = BooleanField("האם מדובר בבקשת רכישה?")
    desired_discount = DecimalField(
        "אחוז הנחה מבוקש", validators=[Optional(), NumberRange(min=0, max=100)]
    )
    buyer_description = TextAreaField("תיאור הבקשה", validators=[Optional()])

    offer_type = HiddenField("offer_type")  # To store whether it's a seller or buyer


class SellerAddCoffeeOfferCodeForm(FlaskForm):
    coffee_offer_code = StringField(
        "קוד הצעת קפה", validators=[DataRequired(), Length(min=4, max=20)]
    )
    submit = SubmitField("שמור קוד הצעה")


class CoffeeImageUploadForm(FlaskForm):
    offer_image = FileField(
        "העלה תמונה של הצעת הקפה",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png", "gif"], "רק קבצי תמונה מותרים!"),
        ],
    )
    submit_upload = SubmitField("העלה תמונה")


class DeleteOfferForm(FlaskForm):
    submit = SubmitField("מחק הצעה")


class ConfirmTransferForm(FlaskForm):
    """Form for confirming monetary transfer by the buyer"""

    submit = SubmitField("אשר העברה")


from flask_wtf import FlaskForm
from wtforms import HiddenField


class CancelTransactionForm(FlaskForm):
    csrf_token = HiddenField()


from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Regexp


class ApproveCoffeeTransactionForm(FlaskForm):
    seller_phone = StringField(
        "מספר טלפון (עם קפה)",
        validators=[
            DataRequired(message="יש להזין מספר טלפון"),
            Regexp(r"^0\d{2}-\d{7}$", message="יש להזין מספר טלפון בפורמט 0xx-xxxxxxx"),
        ],
    )
    submit = SubmitField("אשר עסקה")


# הוסף את הטפסים הבאים לקובץ forms.py שלך


class EditTagForm(FlaskForm):
    """Form for editing tag name"""

    name = StringField(
        "שם חדש לתגית",
        validators=[
            DataRequired(message="חובה למלא שם תגית."),
            Length(max=50, message="שם התגית לא יכול להיות ארוך מ-50 תווים."),
        ],
    )
    submit = SubmitField("עדכן")


class TransferCouponsForm(FlaskForm):
    """Form for transferring coupons from one tag to another"""

    source_tag_id = HiddenField("מזהה תגית מקור", validators=[DataRequired()])
    target_tag_id = SelectField(
        "העבר קופונים לתגית",
        coerce=int,
        validators=[DataRequired(message="חובה לבחור תגית יעד.")],
    )
    submit = SubmitField("העבר קופונים")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "סיסמא נוכחית", validators=[DataRequired(message="נא להזין את הסיסמא הנוכחית")]
    )
    new_password = PasswordField(
        "סיסמא חדשה",
        validators=[
            DataRequired(message="נא להזין סיסמא חדשה"),
            Length(min=8, message="הסיסמא חייבת להכיל לפחות 8 תווים"),
            Regexp(
                r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d@$!%*#?&]{8,}$",
                message="הסיסמא חייבת להכיל לפחות אות אחת ומספר אחד",
            ),
        ],
    )
    confirm_password = PasswordField(
        "אימות סיסמא חדשה",
        validators=[
            DataRequired(message="נא לאמת את הסיסמא החדשה"),
            EqualTo("new_password", message="הסיסמאות אינן תואמות"),
        ],
    )
