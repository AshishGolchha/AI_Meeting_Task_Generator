import smtplib
from email.mime.text import MIMEText


def send_task_email(to_email, task_title, deadline):

    subject = f"New Task Assigned: {task_title}"

    body = f"""
You have been assigned a new task.

Task: {task_title}
Deadline: {deadline}

Please login to the dashboard.
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = "noreply@company.com"
    msg["To"] = to_email

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login("YOUR_EMAIL", "APP_PASSWORD")

    server.send_message(msg)
    server.quit()
