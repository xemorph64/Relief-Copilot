"""End-to-end agent flow with WhatsApp, Claude and Bhashini stubbed out."""
import asyncio
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()

from app import agent, store  # noqa: E402
from app.extract import Facts  # noqa: E402
from tests.test_rules import PALGHAR, BASE  # noqa: E402

sent = []


async def fake_send(*args, **kw):
    sent.append(args)
    return {}


def facts(**kw):
    base = dict(language="mr", applicant_name="Sunita Patil", applicant_name_confidence=0.9, hazard="flood",
                hazard_confidence=0.95, incident_date="2026-07-05", incident_date_confidence=0.9,
                district="Palghar", taluka="Vasai", village="Agashi", village_confidence=0.9,
                assets=[dict(asset_class="milch_large", quantity=2, description="म्हशी", confidence=0.9,
                             quote="don mhashi")], amount_citizen_expects=200000, notes="")
    return Facts(**{**base, **kw})


def test_voice_to_review_to_confirm(monkeypatch):
    for name in ("send_text", "send_buttons", "send_document", "mark_read"):
        monkeypatch.setattr(agent.wa, name, fake_send)
    monkeypatch.setattr(agent.rules, "load_rules", lambda: [BASE, PALGHAR])
    monkeypatch.setattr(agent, "DEBOUNCE_S", 0)
    replies = iter([facts(incident_date=None, incident_date_confidence=0.1), facts()])

    async def fake_extract(*a):
        return next(replies)
    monkeypatch.setattr(agent, "extract", fake_extract)

    async def run():
        await agent.handle({"id": "m1", "from": "919800000001", "type": "text",
                            "text": {"body": "puraat don mhashi vahun gelya, mi Sunita Patil"}})
        await asyncio.sleep(0.05)
        c = store.open_claim("919800000001")
        assert c["state"] == "CLARIFY" and "तारखेला" in sent[-1][1]   # one batched question
        await agent.handle({"id": "m2", "from": "919800000001", "type": "text", "text": {"body": "5 July"}})
        await asyncio.sleep(0.05)
        c = store.get_claim(c["id"])
        assert c["state"] == "REVIEW"
        assert c["data"]["results"][0]["amount"] == 80000                # engine, not the LLM's 2 lakh
        assert "₹80,000" in sent[-1][1] and "200,000" not in sent[-1][1]
        await agent.handle({"id": "m3", "from": "919800000001", "type": "interactive",
                            "interactive": {"button_reply": {"id": "confirm"}}})
        assert store.get_claim(c["id"])["state"] == "WATCHING"
        kinds = [e["kind"] for e in store.claim_events(c["id"])]
        assert {"extracted", "asked", "rule_resolved", "confirmed", "pdf_ready"} <= set(kinds)

    asyncio.run(run())
