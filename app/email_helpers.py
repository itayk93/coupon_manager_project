import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from flask import current_app, render_template, url_for, request
from itsdangerous import URLSafeTimedSerializer
from pprint import pprint

load_dotenv()
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_NAME = "Coupon Master"


def _get_brevo_client():
    """Lazily import the Brevo (SendinBlue) SDK."""
    try:
        import sib_api_v3_sdk  # type: ignore
        from sib_api_v3_sdk.rest import ApiException  # type: ignore

        return sib_api_v3_sdk, ApiException
    except ImportError:
        return None, None


def send_html_email(
    api_key: str,
    sender_email: str,
    sender_name: str,
    recipient_email: str,
    recipient_name: str,
    subject: str,
    html_content: str,
    add_timestamp: bool = True,
):
    """
    Sends an HTML email using the Brevo (SendinBlue) API.

    Parameters:
    - api_key (str): Your Brevo API key.
    - sender_email (str): Sender's email address.
    - sender_name (str): Sender's name.
    - recipient_email (str): Recipient's email address.
    - recipient_name (str): Recipient's name.
    - subject (str): Subject of the email.
    - html_content (str): HTML content of the email.
    - add_timestamp (bool): Whether to add timestamp to subject line.

    Returns:
    - dict: API response if successful.
    - None: If an exception occurs.
    """
    sib_api_v3_sdk, ApiException = _get_brevo_client()
    if sib_api_v3_sdk is None or ApiException is None:
        raise ImportError(
            "sib_api_v3_sdk is not installed. Please install the Brevo SDK to send emails."
        )

    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = api_key

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    if add_timestamp:
        israel_tz = ZoneInfo("Asia/Jerusalem")
        israel_time = datetime.now(israel_tz)
        final_subject = f"{subject} - {israel_time.strftime('%d%m%Y %H:%M')}"
    else:
        final_subject = subject

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_email, "name": recipient_name}],
        sender={"email": sender_email, "name": sender_name},
        subject=final_subject,
        html_content=html_content,
    )

    try:
        api_response = api_instance.send_transac_email(send_smtp_email)
        pprint(api_response)
        return api_response
    except ApiException as e:
        print(
            "Exception when calling TransactionalEmailsApi->send_transac_email: %s\n"
            % e
        )
        return None


def send_email(
    sender_email,
    sender_name,
    recipient_email,
    recipient_name,
    subject,
    html_content,
    add_timestamp=True,
):
    """
    Sends a general email.

    :param sender_email: Sender's email address
    :param sender_name: Sender's name
    :param recipient_email: Recipient's email address
    :param recipient_name: Recipient's name
    :param subject: Subject of the email
    :param html_content: HTML content of the email
    :param add_timestamp: Whether to add timestamp to subject line
    """
    api_key = BREVO_API_KEY

    try:
        send_html_email(
            api_key=api_key,
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=subject,
            html_content=html_content,
            add_timestamp=add_timestamp,
        )
    except Exception as e:
        raise Exception(f"Error sending email: {e}")


def generate_confirmation_token(email):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return serializer.dumps(email, salt=current_app.config["SECURITY_PASSWORD_SALT"])


def confirm_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    email = serializer.loads(
        token, salt=current_app.config["SECURITY_PASSWORD_SALT"], max_age=expiration
    )
    return email


def send_password_reset_email(user):
    try:
        token = generate_confirmation_token(user.email)
        reset_url = request.host_url.rstrip("/") + url_for(
            "auth.reset_password", token=token
        )
        html = render_template(
            "emails/password_reset_email.html", user=user, reset_link=reset_url
        )

        sender_email = "noreply@couponmasteril.com"
        sender_name = "Coupon Master"
        recipient_email = user.email
        recipient_name = user.first_name
        subject = "בקשת שחזור סיסמה - Coupon Master"

        send_email(
            sender_email=sender_email,
            sender_name=sender_name,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            subject=subject,
            html_content=html,
        )

    except Exception as e:
        print(f"שגיאה בשליחת מייל שחזור סיסמה: {e}")


def generate_password_reset_token(email, expiration=3600):
    """
    Creates a Time-Limited token for password reset.
    :param email: The email to which the token is linked
    :param expiration: Token validity duration in seconds (default: 3600 = 1 hour)
    :return: Signed token
    """
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return s.dumps(email, salt=current_app.config["SECURITY_PASSWORD_SALT"])


def confirm_password_reset_token(token, expiration=3600):
    """
    Checks the validity of the token and its expiration date for password reset.

    :param token: The token received in the URL
    :param expiration: Token validity duration in seconds (default: 3600 = 1 hour)
    :return: Email address if valid, otherwise raises an exception
    """
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    email = s.loads(
        token, salt=current_app.config["SECURITY_PASSWORD_SALT"], max_age=expiration
    )
    return email


def send_coupon_purchase_request_email(seller, buyer, coupon):
    """
    Sends an email to the seller when a buyer requests to purchase a coupon.

    :param seller: The seller's User object
    :param buyer: The buyer's User object
    :param coupon: The Coupon object to be purchased
    """
    sender_email = SENDER_EMAIL
    sender_name = SENDER_NAME
    recipient_email = seller.email
    recipient_name = f"{seller.first_name} {seller.last_name}"
    subject = "בקשה חדשה לקופון שלך"

    html_content = render_template(
        "emails/new_coupon_request.html",
        seller=seller,
        buyer=buyer,
        coupon=coupon,
        buyer_gender=buyer.gender,
        seller_gender=seller.gender,
    )

    send_email(
        sender_email=sender_email,
        sender_name=sender_name,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        subject=subject,
        html_content=html_content,
    )


def send_password_change_email(user, token):
    """
    שליחת מייל אישור שינוי סיסמא.
    """
    try:
        confirmation_link = url_for(
            "profile.confirm_password_change", token=token, _external=True
        )

        html_content = render_template(
            "emails/password_change_confirmation.html",
            user=user,
            confirmation_link=confirmation_link,
        )

        send_email(
            sender_email="noreply@couponmasteril.com",
            sender_name="Coupon Master",
            recipient_email=user.email,
            recipient_name=f"{user.first_name} {user.last_name}",
            subject="אישור שינוי סיסמא - Coupon Master",
            html_content=html_content,
        )
        return True
    except Exception as e:
        current_app.logger.error(f"Error sending password change email: {str(e)}")
        return False
