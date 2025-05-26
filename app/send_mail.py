import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint


def send_html_email(
    api_key: str,
    sender_email: str,
    sender_name: str,
    recipient_email: str,
    recipient_name: str,
    subject: str,
    html_content: str,
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

    Returns:
    - dict: API response if successful.
    - None: If an exception occurs.
    """
    # Configure API key authorization
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = api_key

    # Create an instance of the TransactionalEmailsApi
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    # Define the email parameters
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": recipient_email, "name": recipient_name}],
        sender={"email": sender_email, "name": sender_name},
        subject=subject,
        html_content=html_content,
    )

    try:
        # Send the email
        api_response = api_instance.send_transac_email(send_smtp_email)
        pprint(api_response)
        return api_response
    except ApiException as e:
        print(
            "Exception when calling TransactionalEmailsApi->send_transac_email: %s\n"
            % e
        )
        return None
