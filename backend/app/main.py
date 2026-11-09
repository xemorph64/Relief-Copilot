import asyncio
import json
import logging
import mimetypes

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import agent, store, wa
from app.config import settings

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Relief Copilot backend")
app.mount("/admin", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="admin")


@app.get("/health")
def health():
    return {"ok": True, "channel": settings.channel, "whatsapp_configured": wa.configured(),
            "claude_configured": bool(settings.anthropic_api_key),
            "groq_configured": bool(settings.groq_api_key),
            "llm_provider": settings.llm_provider,
            "asr_configured": bool(settings.bhashini_api_key)}


@app.get("/webhook")
def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.wa_verify_token:
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403)


@app.post("/webhook")
async def inbound(request: Request, tasks: BackgroundTasks):
    body = await request.body()
    logging.info("WH raw POST: %s", body[:2000])
    ok = wa.signature_ok(body, request.headers.get("X-Hub-Signature-256", ""))
    logging.info("WH signature ok=%s", ok)
    if not ok:
        raise HTTPException(401)
    for entry in json.loads(body).get("entry", []):
        for change in entry.get("changes", []):
            v = change.get("value", {})
            names = {c["wa_id"]: c.get("profile", {}).get("name", "") for c in v.get("contacts", [])}
            for msg in v.get("messages", []):
                if not store.seen(msg["id"]):  # Meta retries deliveries
                    tasks.add_task(_process, msg, names.get(msg["from"], ""))
            for st in v.get("statuses", []):
                store.event(None, "delivery_status", {"id": st.get("id"), "status": st.get("status")}, "whatsapp")
    return {"ok": True}  # ack fast; work happens after the response


async def _process(msg: dict, name: str):
    await wa.mark_read(msg["id"])
    try:
        await agent.handle(msg, name)
    except Exception:  # noqa: BLE001
        logging.exception("handling %s failed", msg.get("id"))


# ---- Twilio channel ------------------------------------------------------------------------
# Point Twilio's "When a message comes in" (sandbox or sender) at
#   https://<host>/webhook/twilio
# Inbound posts are form-encoded and signed with X-Twilio-Signature; they are
# converted into the Meta-shaped message dicts agent.py already handles.

@app.post("/webhook/twilio")
async def twilio_inbound(request: Request, tasks: BackgroundTasks):
    from urllib.parse import parse_qsl
    raw = (await request.body()).decode("utf-8", "replace")
    form = dict(parse_qsl(raw, keep_blank_values=True))  # urlencoded, no python-multipart needed
    ok = wa.twilio_signature_ok(str(request.url), form, request.headers.get("X-Twilio-Signature", ""))
    if not ok:
        logging.info("TW signature rejected")
        raise HTTPException(401)
    sid = form.get("MessageSid", "")
    if not sid:
        return {"ok": True}
    if not _twilio_is_message(form):  # it's a send/status callback
        st = form.get("MessageStatus") or form.get("SmsStatus") or ""
        if st and st != "received":
            store.event(None, "delivery_status", {"id": sid, "status": st}, "whatsapp")
        return {"ok": True}
    if not store.seen(sid):  # Twilio retries deliveries like Meta does
        tasks.add_task(_process, _twilio_msg(form), form.get("ProfileName", ""))
    return {"ok": True}  # ack fast; work happens after the response


def _twilio_is_message(f: dict) -> bool:
    """Inbound message vs outbound status callback. Messages have content."""
    return bool(f.get("Body") or f.get("ButtonPayload")
                or (f.get("NumMedia") or "0") not in ("0", "", None)
                or (f.get("Latitude") and f.get("Longitude")))


def _twilio_msg(f: dict) -> dict:
    """Twilio webhook form -> the Meta-shaped msg dict agent.handle() expects."""
    msg = {"id": f["MessageSid"], "from": f.get("From", "").replace("whatsapp:", "")}
    if f.get("ButtonPayload"):  # quick-reply tap: id round-trips verbatim
        msg["type"] = "interactive"
        msg["interactive"] = {"button_reply": {"id": f["ButtonPayload"],
                                               "title": f.get("ButtonText") or f.get("Body") or ""}}
        return msg
    if f.get("Latitude") and f.get("Longitude"):
        msg["type"] = "location"
        try:
            msg["location"] = {"latitude": float(f["Latitude"]), "longitude": float(f["Longitude"])}
        except ValueError:
            msg["location"] = {"latitude": f["Latitude"], "longitude": f["Longitude"]}
        return msg
    try:
        n_media = int(f.get("NumMedia") or 0)
    except ValueError:
        n_media = 0
    if n_media:
        mime = (f.get("MediaContentType0", "") or "").split(";")[0].strip()
        kind = "audio" if mime.startswith("audio") else "image"
        # 'id' carries the fetch URL; download_media() auths it (Twilio = URL-land).
        sub = {"id": f.get("MediaUrl0", ""), "mime_type": mime}
        if kind == "image" and f.get("Body"):
            sub["caption"] = f["Body"]
        msg["type"] = kind
        msg[kind] = sub
        return msg
    msg["type"] = "text"
    msg["text"] = {"body": f.get("Body", "")}
    return msg


# ---- dashboard API -------------------------------------------------------------------------

@app.get("/api/claims")
def claims():
    return [{k: c[k] for k in ("id", "state", "lang", "channel", "created", "updated")}
            | {"phone_tail": c["phone"][-2:], "facts": c["data"].get("facts"), "results": c["data"].get("results")}
            for c in store.list_claims()]


@app.get("/api/claims/{cid}")
def claim(cid: int):
    c = store.get_claim(cid)
    c["phone"] = "xxxxxxxx" + c["phone"][-2:]
    return {"claim": c, "messages": store.claim_messages(cid), "events": store.claim_events(cid)}


@app.get("/api/events/stream")
async def events_stream():
    q = store.subscribe()

    async def gen():
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            store.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/flows/{cid}")
async def flows_endpoint(cid: int, request: Request):
    """WhatsApp Flows data-exchange endpoint for the review Flow (F11)."""
    from app import flows
    body = await request.body()
    if not flows.signature_ok(body, request.headers.get("x-flow-request-integrity", "")):
        raise HTTPException(401)
    return flows.handle(cid, json.loads(body or b"{}"))


@app.post("/api/reeval")
async def reeval(notify: bool = False):
    """Retroactive re-evaluation after new rules were ingested (F15). notify=1 also messages
    citizens whose REVIEW-state claim amounts changed."""
    from app import reeval as rv
    return {"changed": rv.reevaluate(notify=notify)}


@app.get("/files/{name}")
def files(name: str):
    p = (settings.media_dir / "pdf" / name).resolve()
    if p.parent != (settings.media_dir / "pdf").resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf", filename=name)


@app.get("/mediafile/{name}")
def mediafile(name: str):
    """Publicly fetchable media for the Twilio channel (Twilio pulls MediaUrl
    itself; it has no upload API). Files are what send_audio/... parked there."""
    p = (settings.media_dir / "serve" / name).resolve()
    if p.parent != (settings.media_dir / "serve").resolve() or not p.exists():
        raise HTTPException(404)
    mime, _ = mimetypes.guess_type(name)
    return FileResponse(p, media_type=mime or "application/octet-stream")
