"""GR Watcher: pulls the latest GRs from gr.maharashtra.gov.in (official domain only), keeps the
relief-relevant ones, downloads their PDFs and fingerprints them for the verification queue.

The portal's default listing (about the last week, paged) needs no captcha; its search form does,
and we never automate that. Older GRs are added by reference number with `fetch <ref>`.

Usage:
    python -m app.grwatcher scan            # crawl listing, download relevant new GRs
    python -m app.grwatcher fetch <18-digit-ref> [<ref> ...]
"""
import hashlib
import html
import json
import re
import sys

import httpx

from app.config import ROOT

LIST_URL = "https://gr.maharashtra.gov.in/1145/Government-Resolutions"
PDF_URL = "https://gr.maharashtra.gov.in/Site/Upload/Government%20Resolutions/Marathi/{ref}.pdf"
GR_DIR = ROOT / "data" / "gr"
INDEX = GR_DIR / "index.json"
RELIEF_DEPTS = ("मदत व पुनर्वसन", "महसूल व वन", "पशुसंवर्धन", "कृषी, पशुसंवर्धन")
RELIEF_WORDS = ("आपत्ती", "अतिवृष्टी", "पूर", "नुकसान", "मदत", "चक्रीवादळ", "गारपीट", "दरड", "वीज", "भूकंप",
                "दुष्काळ", "पुनर्वसन", "SDRF", "NDRF")


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": "ReliefCopilot-GRWatcher/0.1"}, timeout=90, follow_redirects=True)


def _rows(page: str) -> list[dict]:
    flat = re.sub(r"\s+", " ", page)
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", flat):
        ref = re.search(r"(\d{18})\.pdf", tr)
        if not ref:
            continue
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr)]
        cells = [c for c in cells if c]
        date = next((c for c in cells if re.fullmatch(r"\d{2}-\d{2}-\d{4}", c)), "")
        out.append({"ref": ref.group(1), "department": cells[1] if len(cells) > 1 else "",
                    "title": cells[2] if len(cells) > 2 else "", "date": date})
    return out


def _form(page: str) -> dict:
    d = {}
    for tag in re.findall(r"<input[^>]*>", page):  # hidden + text inputs carry the pager state
        typ = re.search(r'type="([^"]*)"', tag)
        name = re.search(r'name="([^"]*)"', tag)
        if name and typ and typ.group(1) in ("hidden", "text"):
            val = re.search(r'value="([^"]*)"', tag)
            d[name.group(1)] = html.unescape(val.group(1)) if val else ""
    d["ctl00$SitePH$rblDateFilter"] = "1"
    return d


def list_recent(max_pages: int = 60) -> list[dict]:
    rows, seen = [], set()
    with _client() as c:
        page = c.get(LIST_URL).text
        for _ in range(max_pages):
            new = [r for r in _rows(page) if r["ref"] not in seen]
            if not new:
                break
            seen.update(r["ref"] for r in new)
            rows += new
            d = _form(page)
            d["__EVENTTARGET"] = "ctl00$SitePH$ucPaging$lnkNext"
            page = c.post(LIST_URL, data=d).text
    return rows


def is_relevant(row: dict) -> bool:
    return any(d in row["department"] for d in RELIEF_DEPTS) and any(w in row["title"] for w in RELIEF_WORDS)


def _load_index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def fetch(ref: str, meta: dict | None = None) -> dict:
    if not re.fullmatch(r"\d{18}", ref):
        raise ValueError("GR reference must be 18 digits")
    GR_DIR.mkdir(parents=True, exist_ok=True)
    with _client() as c:
        r = c.get(PDF_URL.format(ref=ref))
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            raise ValueError(f"{ref}: official URL did not return a PDF")
    (GR_DIR / f"{ref}.pdf").write_bytes(r.content)
    idx = _load_index()
    idx[ref] = {**idx.get(ref, {}), **(meta or {}), "ref": ref, "url": PDF_URL.format(ref=ref),
                "sha256": hashlib.sha256(r.content).hexdigest(), "bytes": len(r.content),
                "status": idx.get(ref, {}).get("status", "discovered")}
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return idx[ref]


def scan() -> list[dict]:
    idx = _load_index()
    rows = list_recent()
    got = [fetch(r["ref"], r) for r in rows if is_relevant(r) and r["ref"] not in idx]
    print(f"listed {len(rows)} GRs, {len(got)} new relief-relevant downloaded")
    return got


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd, *args = sys.argv[1:] or ["scan"]
    if cmd == "scan":
        for g in scan():
            print(g["ref"], g.get("date"), g.get("title", "")[:90])
    elif cmd == "fetch":
        for ref in args:
            print(json.dumps(fetch(ref), ensure_ascii=False))
