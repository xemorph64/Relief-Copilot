from app.rules import evaluate, is_published

V = [{"by": "a"}, {"by": "b"}]


def rule(rid, cls, amount, layer="base", geo="*", frm="2023-04-01", to=None, **kw):
    return {"rule_id": rid, "status": "published", "verifications": V, "asset_class": cls,
            "hazards": ["flood", "heavy_rain"], "applies_from": frm, "applies_to": to,
            "geo": geo, "layer": layer, "amount": amount,
            "source": {"gr_number": f"TEST-{rid}", "date": frm, "page": 1, "item": "1"}, **kw}


BASE = rule("BASE.MILCH", "milch_large", {"type": "per_unit", "value": 37500}, cap_count=3)
PALGHAR = rule("PAL.MILCH", "milch_large", {"type": "per_unit", "value": 40000}, layer="package",
               geo=["Palghar"], frm="2026-07-04", to="2026-07-08", cap_count=3, supersedes=["BASE.MILCH"])
SHOP = rule("PAL.SHOP", "shop", {"type": "percent_of_assessed", "pct": 75, "max": 50000}, layer="package",
            geo=["Palghar"], frm="2026-07-04", to="2026-07-08", gates=["electoral_roll"])
RULES = [BASE, PALGHAR, SHOP]


def fact(**kw):
    return {"hazard": "flood", "incident_date": "2026-07-05", "district": "Palghar",
            "asset_class": "milch_large", "quantity": 2, **kw}


def test_package_supersedes_base_with_comparison():
    r = evaluate(RULES, fact())
    assert (r["verdict"], r["amount"], r["comparison_amount"]) == ("ELIGIBLE", 80000, 75000)
    assert r["governing"]["rule_id"] == "PAL.MILCH"


def test_base_applies_outside_package_window():
    r = evaluate(RULES, fact(incident_date="2026-06-01"))
    assert (r["amount"], r["governing"]["rule_id"]) == (75000, "BASE.MILCH")


def test_cap():
    assert evaluate(RULES, fact(quantity=5))["amount"] == 120000


def test_percent_capped_and_gate():
    r = evaluate(RULES, fact(asset_class="shop", quantity=1, assessed_loss=80000, gates={"electoral_roll": True}))
    assert (r["verdict"], r["amount"]) == ("ELIGIBLE", 50000)
    r = evaluate(RULES, fact(asset_class="shop", quantity=1, assessed_loss=80000, gates={"electoral_roll": False}))
    assert (r["verdict"], r["reason"]) == ("NEEDS_REVIEW", "gate_failed")
    r = evaluate(RULES, fact(asset_class="shop", quantity=1))
    assert (r["verdict"], r["amount"]) == ("NEEDS_REVIEW", None)


def test_no_rule():
    assert evaluate(RULES, fact(asset_class="boat_full"))["verdict"] == "RULE_NOT_VERIFIED"


def test_tie_goes_to_human():
    twin = {**PALGHAR, "rule_id": "PAL.MILCH.2", "supersedes": []}
    assert evaluate(RULES + [twin], fact())["verdict"] == "NEEDS_REVIEW"


def test_unverified_rules_never_used():
    one_signer = {**PALGHAR, "verifications": [{"by": "a"}, {"by": "a"}]}
    assert not is_published(one_signer)
    assert evaluate([BASE, one_signer], fact())["governing"]["rule_id"] == "BASE.MILCH"
    assert evaluate([{**BASE, "status": "drafted"}], fact())["verdict"] == "RULE_NOT_VERIFIED"
