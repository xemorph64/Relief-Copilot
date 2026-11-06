"""Retroactive re-evaluation: when new rules are ingested (a superseding GR published), every
open claim whose facts resolve differently is recomputed. Pre-confirmation claims (NEW..REVIEW)
are refreshed in place; confirmed ones are listed for the admin to act on — nothing is changed
without the citizen's knowledge (PRD non-negotiable 3).

Run via the dashboard API:  POST /api/reeval?notify=1
"""
import asyncio
import time

from app import agent, rules, store


def _evaluate_assets(all_rules: list[dict], f: dict, district: str | None) -> list[dict]:
    out = []
    for a in f["assets"]:
        r = rules.evaluate(all_rules, {"hazard": f["hazard"], "incident_date": f["incident_date"],
                                       "district": f["district"] or district, "asset_class": a["asset_class"],
                                       "quantity": a["quantity"]})
        out.append({"asset": a, "verdict": r["verdict"], "amount": r.get("amount"),
                    "rule_id": r["governing"]["rule_id"] if r.get("governing") else None,
                    "citation": rules.citation(r["governing"]) if r.get("governing") else None,
                    "comparison_amount": r.get("comparison_amount"), "trace": r.get("trace", []),
                    "missing_docs": r.get("missing_docs", [])})
    return out


def _diff(old: list[dict] | None, new: list[dict]) -> dict | None:
    old = old or []
    old_by = {r["asset"]["asset_class"]: r for r in old}
    new_by = {r["asset"]["asset_class"]: r for r in new}
    changes = []
    for k in old_by.keys() | new_by.keys():
        o, n = old_by.get(k, {}).get("amount"), new_by.get(k, {}).get("amount")
        if o != n:
            changes.append({"asset_class": k, "from": o, "to": n,
                            "new_rule": new_by.get(k, {}).get("rule_id")})
    return {"changes": changes} if changes else None


def reevaluate(notify: bool = False) -> list[dict]:
    all_rules = rules.load_rules()
    changed = []
    for c in store.list_claims():
        if c["state"] not in store.OPEN or not (c["data"].get("facts") or {}).get("assets"):
            continue
        f = c["data"]["facts"]
        new_results = _evaluate_assets(all_rules, f, (c["data"].get("location") or {}).get("district"))
        d = _diff(c["data"].get("results"), new_results)
        if d:
            c["data"]["results"] = new_results
            c["data"]["reevaluated_at"] = time.time()
            store.save_claim(c)
            store.event(c["id"], "reevaluated", d)
            changed.append({"claim_id": c["id"], "state": c["state"], **d})
            if notify and c["state"] == "REVIEW":
                # only claims still awaiting confirmation get an automatic message; anything
                # finalised stays finalised until an official re-files (non-negotiable 3)
                text = agent.t("reeval", c["lang"]).format(**_fmt(new_results))
                store.event(c["id"], "reeval_notified", {})
                asyncio.ensure_future(_notify(c["phone"], text))
    return changed


async def _notify(phone: str, text: str) -> None:
    from app import wa
    try:
        await wa.send_text(phone, text)
    except Exception:  # noqa: BLE001
        store.event(None, "error", {"stage": "reeval_notify", "phone_tail": phone[-2:]})


def _fmt(results: list[dict]) -> dict:
    total = sum(r["amount"] or 0 for r in results)
    return {"amount": f"₹{total:,}"}
