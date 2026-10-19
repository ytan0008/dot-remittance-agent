"""Outgoing email over SMTP. Off until SMTP_HOST and SMTP_FROM are set; credentials come only from the environment."""
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from .domain import Denied

ADDRESS = re.compile(r"[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}")


def configured():
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def valid_address(value):
    return isinstance(value, str) and len(value) <= 254 and ADDRESS.fullmatch(value) is not None


def send(to, subject, text, html=None):
    if not configured():
        raise Denied("email is not configured; set SMTP_HOST and SMTP_FROM in .env", "email_unconfigured")
    if not valid_address(to) or "\n" in subject or "\r" in subject:
        raise Denied("invalid email address or subject", "email_invalid")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ["SMTP_FROM"], to, subject[:200]
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT") or 587)
    security = (os.getenv("SMTP_SECURITY") or ("ssl" if port == 465 else "starttls")).lower()
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            if os.getenv("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        # The server's reply can echo the login; report only the error class.
        raise Denied(f"email could not be sent ({type(exc).__name__})", "email_failed") from None
    return {"sent": True, "to": to}
