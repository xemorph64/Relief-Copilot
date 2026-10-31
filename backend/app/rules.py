"""Deterministic rule resolver and engine. The only code that produces rupee amounts.

Rules live in data/rules/*.json. A rule is used only when status == "published" and it carries
sign-offs from two different verifiers (see PRD: Official GR retrieval and verification).
"""
import json
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent.parent / "data" / "rules"


def load_rules(d: Path = RULES_DIR) -> list[dict]:
    return [r for f in sorted(d.glob("*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]


def is_published(r: dict) -> bool:
    return r["status"] == "published" and len({v["by"] for v in r.get("verifications", [])}) >= 2


def specificity(r: dict) -> int:
    # district-scoped package > statewide package > statewide base norm
    return (2 if r["geo"] != "*" else 1) + (1 if r["layer"] == "package" else 0)


def _matches(r: dict, f: dict) -> bool:
    return (
        is_published(r)
        and r["asset_class"] == f["asset_class"]
        and f["hazard"] in r["hazards"]
        and r["applies_from"] <= f["incident_date"] <= (r["applies_to"] or "9999-12-31")
        and (r["geo"] == "*" or f["district"] in r["geo"])
    )


def resolve(rules: list[dict], fact: dict) -> dict:
    cands = [r for r in rules if _matches(r, fact)]
    superseded = {s for r in cands for s in r.get("supersedes", [])}
    live = sorted((r for r in cands if r["rule_id"] not in superseded), key=specificity, reverse=True)
    if not live:
        return {"verdict": "RULE_NOT_VERIFIED", "governing": None, "comparison": None}
    if len(live) > 1 and specificity(live[0]) == specificity(live[1]):
        return {"verdict": "NEEDS_REVIEW", "reason": "rule_tie", "governing": None,
                "comparison": None, "candidates": [r["rule_id"] for r in live]}
    gov = live[0]
    comp = next((r for r in cands if r["rule_id"] in gov.get("supersedes", [])), None)
    return {"verdict": "ELIGIBLE", "governing": gov, "comparison": comp}


def compute(rule: dict, fact: dict) -> dict:
    a, q, trace = rule["amount"], fact.get("quantity", 1), []
    cap = rule.get("cap_count")
    if cap and q > cap:
        trace.append(f"quantity {q} capped to {cap} (cap_count)")
        q = cap
    if a["type"] == "per_unit":
        amt = a["value"] * q
        trace.append(f"{q} x {a['value']} = {amt}")
    elif a["type"] == "flat":
        amt = a["value"]
        trace.append(f"flat {amt}")
    elif a["type"] == "percent_of_assessed":
        loss = fact.get("assessed_loss")
        if loss is None:
            return {"amount": None, "quantity": q, "trace": ["assessed loss not yet known"], "needs": "assessed_loss"}
        amt = loss * a["pct"] // 100
        trace.append(f"{a['pct']}% of {loss} = {amt}")
    else:
        raise ValueError(f"unknown amount type {a['type']}")
    mx = a.get("max") or rule.get("max_amount")
    if mx and amt > mx:
        trace.append(f"{amt} capped to {mx}")
        amt = mx
    return {"amount": amt, "quantity": q, "trace": trace}


def evaluate(rules: list[dict], fact: dict) -> dict:
    """fact: hazard, incident_date (YYYY-MM-DD), district, asset_class, quantity, [assessed_loss], [gates]."""
    res = resolve(rules, fact)
    gov = res["governing"]
    if not gov:
        return {**res, "amount": None, "trace": []}
    out = {**res, **compute(gov, fact)}
    if res["comparison"]:
        out["comparison_amount"] = compute(res["comparison"], fact)["amount"]
    gates = fact.get("gates", {})
    failed = [g for g in gov.get("gates", []) if gates.get(g) is False]
    out["pending_gates"] = [g for g in gov.get("gates", []) if gates.get(g) is None]
    out["missing_docs"] = [d for d in gov.get("requires", []) if d not in fact.get("docs", [])]
    if failed:
        out.update(verdict="NEEDS_REVIEW", reason="gate_failed", failed_gates=failed)
    elif out["amount"] is None:
        out.update(verdict="NEEDS_REVIEW", reason=out.get("needs"))
    return out


def citation(rule: dict) -> str:
    s = rule["source"]
    return f"GR {s['gr_number']} dt {s['date']}, p.{s['page']}, item {s['item']}"
