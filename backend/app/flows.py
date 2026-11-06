"""WhatsApp Flow for the review-and-confirm step (PRD 5.7 / F11): a native multi-screen form
inside the chat instead of plain buttons. The Flow definition in static/review_flow.json is
imported into the Meta dashboard (or via API), then configured with this server as its data
endpoint:  POST /api/flows/{claim_id}

Data-exchange protocol (Meta docs): requests carry an encrypted token and an integrity header;
we verify the HMAC of the body with the endpoint passphrase, resolve the claim, and answer
ping / get_data / data_exchange. On data_exchange with action=confirm we drive the same state
machine the three buttons use.
"""
import hashlib
import hmac
import json
import logging

from app import agent, store
from app.config import settings

log = logging.getLogger("flows")
PROTOCOL_VERSION = "3.0"


def _summary_lines(c: dict) -> list[dict]:
    lang, res = c["lang"], c["data"].get("results", [])
    lines = []
    for r in res:
        a = r["asset"]
        if r["verdict"] == "ELIGIBLE" and r["amount"] is not None:
            lines.append({"text": f"{a['description']} ×{a['quantity']} — ₹{r['amount']:,}",
                          "citation": r.get("citation") or "", "state": "ok"})
        elif r["verdict"] == "RULE_NOT_VERIFIED":
            lines.append({"text": f"{a['description']} ×{a['quantity']}", "citation": "",
                          "state": "not_verified"})
        else:
            lines.append({"text": f"{a['description']} ×{a['quantity']}", "citation": "",
                          "state": "needs_review"})
    return lines


def review_data(c: dict) -> dict:
    f, lang = c["data"]["facts"], c.get("lang") or "en"
    total = sum(r["amount"] or 0 for r in c["data"].get("results", []))
    return {
        "applicant": f.get("applicant_name", ""),
        "place": f"{f.get('village') or ''} {f.get('district') or ''}".strip(),
        "hazard_date": f"{f.get('hazard') or ''} · {f.get('incident_date') or ''}",
        "lines": _summary_lines(c),
        "total": f"₹{total:,}" if total else "",
        "lang": lang,
        "labels": {k: agent.t(k, lang) for k in
                   ("review_head", "confirm_q", "btn_yes", "btn_change", "btn_human",
                    "not_verified", "needs_review")},
    }


def signature_ok(body: bytes, header: str) -> bool:
    if not settings.flow_endpoint_passphrase:
        log.warning("flow endpoint passphrase not set; skipping integrity check")
        return True
    expected = hmac.new(settings.flow_endpoint_passphrase.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header or "", expected)


def handle(cid: int, request: dict) -> dict:
    """Answer one Flow data-exchange request for claim `cid`."""
    action = request.get("action")
    if action == "ping":
        return {"data": {"status": "ok"}}
    if action == "get_data":
        return {"screen": "REVIEW", "data": review_data(store.get_claim(cid))}
    if action == "data_exchange":
        payload = (request.get("data") or {}).get("action", "")
        if payload == "confirm":
            c = store.get_claim(cid)
            if c["state"] == "REVIEW":
                import asyncio
                asyncio.ensure_future(agent._on_button(c, "confirm"))
                return {"data": {"status": "accepted"}}
            return {"data": {"status": "not_in_review"}}
        c = store.get_claim(cid)
        return {"screen": "REVIEW", "data": review_data(c)}
    return {"data": {"status": "unknown_action"}}


def flow_json() -> dict:
    from pathlib import Path
    return json.loads((Path(__file__).parent / "static" / "review_flow.json").read_text(encoding="utf-8"))
