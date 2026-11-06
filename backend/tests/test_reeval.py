"""Re-evaluation and Flow data-exchange handler tests."""
import asyncio
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()

from app import flows, reeval, store  # noqa: E402
from tests.test_rules import PALGHAR, BASE  # noqa: E402


def make_claim(amount):
    c = store.open_claim("9100000000")
    c["state"] = "REVIEW"
    c["lang"] = "en"
    c["data"] = {"facts": {"applicant_name": "T", "hazard": "flood", "incident_date": "2025-07-15",
                           "district": "Palghar", "village": "x", "taluka": "",
                           "hazard_confidence": 0.9, "incident_date_confidence": 0.9,
                           "applicant_name_confidence": 0.9, "village_confidence": 0.9,
                           "assets": [{"asset_class": "house_full_plain", "quantity": 1,
                                       "description": "ghar", "confidence": 0.9}]},
                 "results": [{"asset": {"asset_class": "house_full_plain", "quantity": 1,
                                        "description": "ghar"}, "verdict": "ELIGIBLE",
                              "amount": amount, "rule_id": "OLD", "citation": None,
                              "comparison_amount": None, "trace": [], "missing_docs": []}]}
    store.save_claim(c)
    return c


def test_reeval_detects_change():
    c = make_claim(70000)
    changed = reeval.reevaluate(notify=False)
    ids = [x["claim_id"] for x in changed]
    assert c["id"] in ids
    entry = next(x for x in changed if x["claim_id"] == c["id"])
    assert entry["changes"][0]["to"] == 120000  # Oct-2025 package, house fully destroyed


def test_reeval_no_change():
    c = make_claim(120000)
    assert all(x["claim_id"] != c["id"] for x in reeval.reevaluate(notify=False))


def test_flow_ping_and_get_data():
    c = make_claim(120000)
    assert flows.handle(c["id"], {"action": "ping"})["data"]["status"] == "ok"
    out = flows.handle(c["id"], {"action": "get_data"})
    assert out["screen"] == "REVIEW"
    assert out["data"]["lines"][0]["text"].startswith("ghar ×1")
    assert "120,000" in out["data"]["total"]  # plain Python number format (not en-IN grouping)


def test_flow_confirm_drives_state_machine(monkeypatch):
    c = make_claim(120000)
    sent = []
    monkeypatch.setattr("app.wa.send_text", lambda *a, **kw: _res(sent, "text"))
    monkeypatch.setattr("app.wa.send_audio", lambda *a, **kw: _res(sent, "audio"))

    def _res(box, kind):
        box.append(kind)
        return {}

    async def run():
        out = flows.handle(c["id"], {"action": "data_exchange", "data": {"action": "confirm"}})
        await asyncio.sleep(0.05)  # let _on_button task complete
        return out

    out = asyncio.run(run())
    assert out["data"]["status"] == "accepted"
    assert store.get_claim(c["id"])["state"] in ("DELIVERED", "WATCHING")
