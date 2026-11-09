"""WhatsApp client: send messages, fetch media, verify webhook signatures.

Two interchangeable backends behind one module, selected by MESSAGE_CHANNEL:
  - "meta":   WhatsApp Cloud API (Graph API). Bearer token, media upload,
              native multi-screen Flows.
  - "twilio": Twilio Programmable Messaging. Basic auth, no media upload API
              (media is fetched from our own public URL), no Flows (buttons
              via a twilio/quick-reply Content template), no REST read receipts.

agent.py, reeval.py and the tests only ever import these functions, so changing
channel is an env change, not a code change.

Inbound normalization: Meta's message dicts are the internal shape; for Twilio
the /webhook/twilio converter in main.py builds the same structure. One abuse
of the shape: for Twilio, `msg["audio|image"]["id"]` carries the media *URL*
(download_media detects and auths it), because Twilio gives URLs not media ids.
"""
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import uuid

import httpx

from app.config import settings


# ---------------------------------------------------------------- helpers ----

def _is_twilio() -> bool:
    return settings.channel == "twilio"


def _graph() -> str:
    return f"https://graph.facebook.com/{settings.wa_graph_version}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.wa_token}"}


def _waddr(to: str) -> str:
    """Either phone number or already-prefixed 'whatsapp:+' address."""
    return to if to.startswith("whatsapp:") else f"whatsapp:{to}"


def _from() -> str:
    return _waddr(settings.twilio_whatsapp_from)


def _creds_meta() -> bool:
    return bool(settings.wa_token and settings.wa_phone_number_id)


def _creds_twilio() -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token)


def configured() -> bool:
    return _creds_meta() if not _is_twilio() else _creds_twilio()


def _client(timeout: float = 30) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, auth=(settings.twilio_account_sid, settings.twilio_auth_token))


async def _tw_send(form: dict) -> dict:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    async with _client() as c:
        r = await c.post(url, data=form)
        r.raise_for_status()
        return r.json()


def _ext(mime: str) -> str:
    known = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
             "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/aac": "aac", "audio/flac": "flac",
             "image/jpeg": "jpg", "application/pdf": "pdf"}
    return known.get(mime.split(";")[0].strip()) or mimetypes.guess_extension(mime.split(";")[0].strip()) or "bin"


async def twilio_public_media(data: bytes, mime: str) -> str:
    """Twilio has no upload API: park media somewhere this server serves over HTTPS."""
    if not settings.public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is required for the Twilio channel (media must be fetchable)")
    folder = settings.media_dir / "serve"
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + _ext(mime)
    (folder / name).write_bytes(data)
    return f"{settings.public_base_url}/mediafile/{name}"


# ----------------------------------------------------------- signatures ------

def signature_ok(body: bytes, header: str) -> bool:
    """Meta webhook: HMAC-SHA256(X-Hub-Signature-256)."""
    expected = "sha256=" + hmac.new(settings.wa_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(settings.wa_app_secret) and hmac.compare_digest(header or "", expected)


def twilio_signature_ok(url: str, params: dict[str, str], header: str) -> bool:
    """Twilio webhook: base64(HMAC-SHA1(auth_token, full URL + sorted params)).
    Set TWILIO_VALIDATE=false to opt out e.g. behind redirects-weird tunnels.
    """
    if not settings.twilio_validate or not settings.twilio_auth_token:
        return True
    data = url + "".join(k + v for k, v in sorted(params.items()))
    expected = base64.b64encode(
        hmac.new(settings.twilio_auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(header or "", expected)


# ---------------------------------------------------------------- sending ----

async def send(payload: dict) -> dict:
    return await _meta_send(payload)  # _meta_send injects messaging_product/recipient_type


async def _meta_send(payload: dict) -> dict:
    payload = {"messaging_product": "whatsapp", "recipient_type": "individual", **payload}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{_graph()}/{settings.wa_phone_number_id}/messages", headers=_headers(), json=payload)
        if r.status_code >= 400:
            detail = r.json().get("error", {})
            raise httpx.HTTPStatusError(
                f"{r.status_code}: {detail.get('message')} (code={detail.get('code')}, "
                f"subcode={detail.get('error_subcode')}, type={detail.get('type')})", request=r.request, response=r)
        return r.json()


async def send_text(to: str, text: str) -> dict:
    if not _is_twilio():
        return await _meta_send({"to": to, "type": "text", "text": {"body": text[:4096]}})
    return await _tw_send({"To": _waddr(to), "From": _from(), "Body": text[:1600]})


async def send_buttons(to: str, text: str, buttons: list[tuple[str, str]]) -> dict:
    if not _is_twilio():
        return await _meta_send({"to": to, "type": "interactive", "interactive": {
            "type": "button", "body": {"text": text[:1024]},
            "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t[:20]}} for i, t in buttons[:3]]}}})
    # Twilio in-session quick replies must come from a Content template (no
    # WhatsApp approval needed to reply to an inbound message). The template
    # (TWILIO_QR_SID) carries titles {{1}}..{{3}} so we localize per send; ids
    # are baked in at template creation, matching _on_button: confirm/change/human.
    params = {"To": _waddr(to), "From": _from()}
    await _tw_send({**params, "Body": text[:1600]})
    if settings.twilio_qr_sid and len(buttons) == 3:
        content_vars = json.dumps({str(i + 1): n[:20] for i, (_, n) in enumerate(buttons[:3])})
        try:
            return await _tw_send({**params, "ContentSid": settings.twilio_qr_sid, "ContentVariables": content_vars})
        except httpx.HTTPStatusError as e:
            logging.info("quick-reply template rejected (%s); buttons degrade to text", e)
    return await send_text(to, "↓ " + " / ".join(n for _, n in buttons))  # best-effort fallback


async def send_document(to: str, link: str, filename: str, caption: str = "") -> dict:
    if not _is_twilio():
        return await _meta_send({"to": to, "type": "document",
                                 "document": {"link": link, "filename": filename, "caption": caption[:1024]}})
    return await _tw_send({"To": _waddr(to), "From": _from(), "MediaUrl": link, "Body": caption[:1024]})


async def send_audio(to: str, data: bytes, mime: str = "audio/wav") -> dict:
    if not _is_twilio():
        async with httpx.AsyncClient(timeout=60) as c:
            up = (await c.post(f"{_graph()}/{settings.wa_phone_number_id}/media", headers=_headers(),
                               files={"file": ("playback" + _ext(mime), data, mime)},
                               data={"messaging_product": "whatsapp", "type": "audio"})).raise_for_status().json()
        return await _meta_send({"to": to, "type": "audio", "audio": {"id": up["id"]}})
    link = await twilio_public_media(data, mime)
    return await _tw_send({"To": _waddr(to), "From": _from(), "MediaUrl": link})


async def send_flow(to: str, text: str, claim_id: int) -> dict:
    """Native multi-screen review is Cloud-API-only; on Twilio we always
    degrade to the buttons flow your no-Flow setup already used (F11)."""
    if not _is_twilio() and settings.wa_flow_id:
        return await _meta_send({"to": to, "type": "interactive", "interactive": {
            "type": "flow", "body": {"text": text[:1024]},
            "action": {"parameters": {
                "flow_message_version": "3", "flow_id": settings.wa_flow_id,
                "flow_cta": "Review claim", "flow_token": str(claim_id),
                "flow_action": "navigate",
                "flow_action_payload": {"screen": "REVIEW"}}}}})
    return await send_buttons(to, text, [
        ("confirm", "Confirm"), ("change", "Change"), ("human", "Talk to official")])


async def mark_read(message_id: str) -> None:
    try:
        if not _is_twilio():
            await _meta_send({"status": "read", "message_id": message_id})
        # Twilio: no REST read receipt for WhatsApp; 'read' arrives on webhook
        # status callbacks instead. Cosmetic either way.
    except httpx.HTTPError:
        pass


# ---------------------------------------------------------------- receiving --

async def download_media(media_id: str) -> tuple[bytes, str]:
    """Meta media URLs expire within minutes: call this as soon as the webhook
    arrives. On Twilio the 'id' is the MediaUrl (needs basic auth)."""
    if not _is_twilio():
        async with httpx.AsyncClient(timeout=60) as c:
            meta = (await c.get(f"{_graph()}/{media_id}", headers=_headers())).raise_for_status().json()
            data = (await c.get(meta["url"], headers=_headers())).raise_for_status().content
            return data, meta.get("mime_type", "")
    async with _client(60) as c:
        r = (await c.get(media_id)).raise_for_status()
        return r.content, r.headers.get("content-type", "")
