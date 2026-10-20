"""Outgoing email, through Resend (one API key) or your own SMTP server. Off until one of them is set; credentials come
only from the environment and never appear in errors.

Resend wins when RESEND_API_KEY is set. Without a verified domain it sends from onboarding@resend.dev and only to the
address the Resend account was created with — enough for your own reports; verify a domain to mail anyone else."""
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
import httpx
from .domain import Denied

ADDRESS = re.compile(r"[^@\s<>\"',;]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}")
RESEND_URL = "https://api.resend.com/emails"
RESEND_DEFAULT_FROM = "DOT <onboarding@resend.dev>"


def provider():
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"):
        return "smtp"
    return None


def configured():
    return provider() is not None


def valid_address(value):
    return isinstance(value, str) and len(value) <= 254 and ADDRESS.fullmatch(value) is not None


def send(to, subject, text, html=None):
    way = provider()
    if not way:
        raise Denied("email is not configured; set RESEND_API_KEY, or SMTP_HOST and SMTP_FROM, in .env", "email_unconfigured")
    if not valid_address(to) or "\n" in subject or "\r" in subject:
        raise Denied("invalid email address or subject", "email_invalid")
    (_resend if way == "resend" else _smtp)(to, subject[:200], text, html)
    return {"sent": True, "to": to}


def _resend(to, subject, text, html):
    body = {"from": os.getenv("RESEND_FROM") or RESEND_DEFAULT_FROM, "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    try:
        r = httpx.post(RESEND_URL, json=body, timeout=20,
                       headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "User-Agent": "dot-remittance-agent"})
    except httpx.HTTPError as exc:
        raise Denied(f"email could not be sent ({type(exc).__name__})", "email_failed") from None
    if r.status_code < 300:
        return
    try:
        message = str(r.json().get("message", ""))
    except ValueError:
        message = ""
    # The usual first stumble: no verified domain yet, so Resend only delivers to the account's own address.
    if r.status_code == 403 and re.search(r"own email address|verify a domain|testing emails", message, re.I):
        raise Denied("without a verified domain, Resend only sends to the address you signed up with", "email_testing_only")
    if r.status_code in (401, 403):
        raise Denied("the Resend API key was refused", "email_key")
    raise Denied(f"email could not be sent (Resend {r.status_code})", "email_failed")


def _smtp(to, subject, text, html):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ["SMTP_FROM"], to, subject
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
