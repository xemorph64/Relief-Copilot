import asyncio
import json
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse

from app import agent, store, wa
from app.config import settings

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Relief Copilot backend")


@app.get("/health")
def health():
    return {"ok": True, "whatsapp_configured": bool(settings.wa_token and settings.wa_phone_number_id),
            "claude_configured": bool(settings.anthropic_api_key), "asr_configured": bool(settings.bhashini_api_key)}


@app.get("/webhook")
def verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.wa_verify_token:
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(403)


@app.post("/webhook")
async def inbound(request: Request, tasks: BackgroundTasks):
    body = await request.body()
    if not wa.signature_ok(body, request.headers.get("X-Hub-Signature-256", "")):
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


@app.get("/files/{name}")
def files(name: str):
    p = (settings.media_dir / "pdf" / name).resolve()
    if p.parent != (settings.media_dir / "pdf").resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf", filename=name)
