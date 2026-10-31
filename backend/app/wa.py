"""WhatsApp Cloud API client: send messages, fetch media, verify webhook signatures."""
import hashlib
import hmac

import httpx

from app.config import settings


def _graph() -> str:
    return f"https://graph.facebook.com/{settings.wa_graph_version}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.wa_token}"}


def signature_ok(body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(settings.wa_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(settings.wa_app_secret) and hmac.compare_digest(header or "", expected)


async def send(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{_graph()}/{settings.wa_phone_number_id}/messages", headers=_headers(),
                         json={"messaging_product": "whatsapp", "recipient_type": "individual", **payload})
        r.raise_for_status()
        return r.json()


async def send_text(to: str, text: str) -> dict:
    return await send({"to": to, "type": "text", "text": {"body": text[:4096]}})


async def send_buttons(to: str, text: str, buttons: list[tuple[str, str]]) -> dict:
    return await send({"to": to, "type": "interactive", "interactive": {
        "type": "button", "body": {"text": text[:1024]},
        "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]]}}})


async def send_document(to: str, link: str, filename: str, caption: str = "") -> dict:
    return await send({"to": to, "type": "document",
                       "document": {"link": link, "filename": filename, "caption": caption[:1024]}})


async def mark_read(message_id: str) -> None:
    try:
        await send({"status": "read", "message_id": message_id})
    except httpx.HTTPError:
        pass  # read receipts are cosmetic


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Meta media URLs expire within minutes: call this as soon as the webhook arrives."""
    async with httpx.AsyncClient(timeout=60) as c:
        meta = (await c.get(f"{_graph()}/{media_id}", headers=_headers())).raise_for_status().json()
        data = (await c.get(meta["url"], headers=_headers())).raise_for_status().content
        return data, meta.get("mime_type", "")
