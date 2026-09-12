"""Companion APK delivery helpers (RFC-0076 send paths)."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from fastapi import HTTPException

from ..integrations.setup import email_config_path, email_status
from . import provision
from .store import root


def _completed_apk_path(job_id: str) -> Path:
    value = provision.job(job_id)
    if value.get("state") != "completed":
        raise HTTPException(409, "APK is not ready")
    result = value.get("result") or {}
    filename = str(result.get("filename") or "")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(500, "APK filename is missing or invalid")
    path = root() / "builds" / filename
    if not path.is_file():
        raise HTTPException(404, "APK file is missing on disk")
    return path


def _load_gmail_account() -> dict[str, str]:
    status = email_status()
    if not status.get("configured"):
        raise HTTPException(400, "Gmail is not connected. Connect Gmail in Setup, then try again.")
    path = email_config_path()
    try:
        import tomllib

        with path.open("rb") as handle:
            raw = tomllib.load(handle)
        accounts = raw.get("accounts") or []
        if not accounts:
            raise HTTPException(400, "Gmail is not connected. Connect Gmail in Setup, then try again.")
        account = accounts[0]
        email = str(account.get("email") or "").strip()
        password = str(account.get("password") or "").strip()
        full_name = str(account.get("full_name") or "").strip() or "Jarvis"
        if not email or not password:
            raise HTTPException(400, "Saved Gmail credentials are incomplete. Reconnect Gmail in Setup.")
        return {"email": email, "password": password, "full_name": full_name}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Could not read the saved Gmail setup.") from exc


def send_apk_email(job_id: str, to: str | None = None) -> dict[str, str]:
    account = _load_gmail_account()
    recipient = (to or account["email"]).strip()
    if not recipient or "@" not in recipient:
        raise HTTPException(400, "Enter a valid destination email address.")
    apk = _completed_apk_path(job_id)

    message = EmailMessage()
    message["Subject"] = "Jarvis companion APK"
    message["From"] = f"{account['full_name']} <{account['email']}>"
    message["To"] = recipient
    message.set_content(
        "Your Jarvis companion APK is attached.\n\n"
        "Install it on your phone, then use Pair phone on the desktop for the 6-digit code or QR.\n"
    )
    message.add_attachment(
        apk.read_bytes(),
        maintype="application",
        subtype="vnd.android.package-archive",
        filename=apk.name,
    )

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
            smtp.login(account["email"], account["password"])
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise HTTPException(400, "Gmail rejected the sign-in. Reconnect Gmail in Setup with a fresh app password.") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(502, "Could not send the APK email. Check the internet connection and try again.") from exc

    return {"ok": "true", "channel": "email", "to": recipient, "detail": f"APK emailed to {recipient}."}


async def send_apk_whatsapp(job_id: str, to: str | None = None) -> dict[str, str]:
    """Send the completed companion APK as a WhatsApp media message."""
    apk_path = _completed_apk_path(job_id)
    from ..integrations.whatsapp_bridge import send_whatsapp_media

    return await send_whatsapp_media(
        apk_path,
        to=to,
        caption=(
            "Your Jarvis companion APK. Install it on this phone, then pair with the "
            "6-digit code or QR shown on your Jarvis desktop."
        ),
    )
