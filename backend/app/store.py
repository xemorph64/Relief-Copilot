"""SQLite persistence for claims, messages and the agent event log the dashboard streams.

ponytail: single-file SQLite + one process; move to Postgres when running more than one worker.
"""
import asyncio
import json
import sqlite3
import time

from app.config import settings

settings.db_path.parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(settings.db_path, check_same_thread=False, isolation_level=None)
db.row_factory = sqlite3.Row
db.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS claims(
  id INTEGER PRIMARY KEY, phone TEXT NOT NULL, state TEXT NOT NULL, lang TEXT,
  channel TEXT NOT NULL DEFAULT 'whatsapp', data TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  wa_id TEXT PRIMARY KEY, claim_id INTEGER, direction TEXT, type TEXT, body TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, claim_id INTEGER, kind TEXT, payload TEXT, actor TEXT, ts REAL);
""")

OPEN = ("NEW", "INTAKE", "CLARIFY", "REVIEW", "NEEDS_HUMAN")
_subscribers: set[asyncio.Queue] = set()


def seen(wa_id: str) -> bool:
    """Atomically record an inbound message id; True if Meta already delivered it."""
    try:
        db.execute("INSERT INTO messages(wa_id, ts) VALUES(?, ?)", (wa_id, time.time()))
        return False
    except sqlite3.IntegrityError:
        return True


def save_message(wa_id: str, claim_id: int, direction: str, type_: str, body: dict) -> None:
    db.execute("INSERT OR REPLACE INTO messages VALUES(?,?,?,?,?,?)",
               (wa_id, claim_id, direction, type_, json.dumps(body, ensure_ascii=False), time.time()))


def open_claim(phone: str, channel: str = "whatsapp") -> dict:
    row = db.execute(f"SELECT * FROM claims WHERE phone=? AND state IN ({','.join('?' * len(OPEN))}) "
                     "ORDER BY id DESC LIMIT 1", (phone, *OPEN)).fetchone()
    if row:
        return _claim(row)
    now = time.time()
    cid = db.execute("INSERT INTO claims(phone, state, channel, created, updated) VALUES(?,?,?,?,?)",
                     (phone, "NEW", channel, now, now)).lastrowid
    event(cid, "claim_created", {"phone_tail": phone[-2:], "channel": channel})
    return get_claim(cid)


def get_claim(cid: int) -> dict:
    return _claim(db.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone())


def _claim(row) -> dict:
    c = dict(row)
    c["data"] = json.loads(c["data"])
    return c


def save_claim(c: dict) -> None:
    db.execute("UPDATE claims SET state=?, lang=?, data=?, updated=? WHERE id=?",
               (c["state"], c.get("lang"), json.dumps(c["data"], ensure_ascii=False), time.time(), c["id"]))


def event(claim_id: int | None, kind: str, payload: dict, actor: str = "agent") -> None:
    ts = time.time()
    eid = db.execute("INSERT INTO events(claim_id, kind, payload, actor, ts) VALUES(?,?,?,?,?)",
                     (claim_id, kind, json.dumps(payload, ensure_ascii=False, default=str), actor, ts)).lastrowid
    ev = {"id": eid, "claim_id": claim_id, "kind": kind, "payload": payload, "actor": actor, "ts": ts}
    for q in list(_subscribers):
        q.put_nowait(ev)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def list_claims(limit: int = 200) -> list[dict]:
    return [_claim(r) for r in db.execute("SELECT * FROM claims ORDER BY updated DESC LIMIT ?", (limit,))]


def claim_events(cid: int) -> list[dict]:
    return [{**dict(r), "payload": json.loads(r["payload"])}
            for r in db.execute("SELECT * FROM events WHERE claim_id=? ORDER BY id", (cid,))]


def claim_messages(cid: int) -> list[dict]:
    return [{**dict(r), "body": json.loads(r["body"] or "{}")}
            for r in db.execute("SELECT * FROM messages WHERE claim_id=? ORDER BY ts", (cid,))]
