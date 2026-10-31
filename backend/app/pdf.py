"""Claim PDF. ponytail: English/Latin layout only - ReportLab cannot shape Devanagari conjuncts;
switch to an HTML template + a shaping renderer (e.g. WeasyPrint) for the bilingual government format."""
import datetime as dt
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.config import settings


def render(claim: dict) -> Path:
    out = settings.media_dir / "pdf"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"RC-{claim['id']:06d}.pdf"
    f, res = claim["data"]["facts"], claim["data"].get("results", [])
    c = canvas.Canvas(str(path), pagesize=A4)
    y = A4[1] - 20 * mm

    def line(text, size=10, gap=6):
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(18 * mm, y, text[:110])
        y -= gap * mm

    line("Disaster Relief Assistance - Application (prepared by Relief Copilot)", 13, 9)
    line(f"Claim id: RC-{claim['id']:06d}    Generated: {dt.datetime.now():%d-%m-%Y %H:%M}")
    line(f"Applicant: {f.get('applicant_name') or ''}    Mobile: {claim['phone']}")
    line(f"Village: {f.get('village') or ''}  Taluka: {f.get('taluka') or ''}  District: {f.get('district') or ''}")
    line(f"Disaster: {f.get('hazard')}    Date of incident: {f.get('incident_date')}", gap=9)
    line("Damage details and relief as per Government Resolution", 11, 7)
    total = 0
    for i, r in enumerate(res, 1):
        a = r["asset"]
        amt = f"Rs {r['amount']:,}" if r["amount"] is not None else r["verdict"].replace("_", " ").title()
        total += r["amount"] or 0
        line(f"{i}. {a['asset_class']} x{a['quantity']}  -  {amt}")
        if r.get("rule_id"):
            line(f"    Rule {r['rule_id']} (GR ref and page in annexure)", 8, 5)
    line(f"Total relief computed: Rs {total:,}", 11, 9)
    line(f"Photos attached: {len(claim['data'].get('photos', []))}    Location: {claim['data'].get('location')}", 9)
    line("Applicant confirmed this statement on WhatsApp. Final sanction rests with the competent authority.", 8)
    line("Talathi / Panchanama ref: ____________________   Signature / thumb: ____________________", 9, 12)
    c.showPage()
    c.save()
    return path
