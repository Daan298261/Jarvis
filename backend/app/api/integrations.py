from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..integrations.setup import (
    IntegrationSetupError,
    WHATSAPP_PAIRING,
    configure_gmail,
    email_status,
)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class GmailSetupBody(BaseModel):
    account_name: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=1, max_length=128)
    app_password: str = Field(min_length=1, max_length=160)


@router.get("/status")
async def integration_status():
    return {"email": email_status(), "whatsapp": WHATSAPP_PAIRING.status()}


@router.post("/email/configure")
async def configure_email(body: GmailSetupBody):
    try:
        result = await configure_gmail(body.account_name, body.email, body.full_name, body.app_password)
        return {"ok": True, "email": result}
    except IntegrationSetupError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/whatsapp/pair")
async def start_whatsapp_pairing():
    try:
        return {"ok": True, "whatsapp": await WHATSAPP_PAIRING.start()}
    except IntegrationSetupError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/whatsapp/pair")
async def whatsapp_pairing_status():
    return {"whatsapp": WHATSAPP_PAIRING.status()}


@router.delete("/whatsapp/pair")
async def cancel_whatsapp_pairing():
    return {"ok": True, "whatsapp": await WHATSAPP_PAIRING.cancel()}


@router.get("/whatsapp/contact")
async def whatsapp_contact_card():
    """Desktop/portal contact card for messaging the linked WhatsApp session."""
    from ..integrations.whatsapp_bridge import jarvis_whatsapp_contact

    status = WHATSAPP_PAIRING.status()
    if not bool(status.get("paired") or status.get("state") == "connected"):
        return {
            "available": False,
            "reason": "WhatsApp is not connected. Connect WhatsApp in Setup, then try again.",
        }
    try:
        return await jarvis_whatsapp_contact()
    except HTTPException as exc:
        if exc.status_code in {400, 502, 504}:
            return {"available": False, "reason": str(exc.detail)}
        raise

