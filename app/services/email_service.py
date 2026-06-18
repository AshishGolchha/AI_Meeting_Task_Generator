import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os


def send_invite_email(to_email, invite_link, org_name):

    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT"))

    subject = f"You’re invited to join {org_name}"

    body = f"""
    Hello,

    You have been invited to join the organization: {org_name}

    Click the link below to accept the invitation:

    {invite_link}

    If you did not expect this invite, please ignore this email.

    — AI Meeting Task Generator
    """

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    server = smtplib.SMTP(smtp_server, smtp_port)
    server.starttls()
    server.login(smtp_email, smtp_password)

    server.send_message(msg)
    server.quit()
