"""Local demo driver (no WhatsApp account needed): feeds the agent the exact
Meta-shaped message dicts the webhook would, and prints every outbound
send_* to the console instead of hitting Meta.

Everything below runs the production agent.py path — same extraction, rules,
review flow and PDF you get over WhatsApp — so this doubles as (a) a failsafe
demo during Meta verification outages and (b) a fast local dev loop.

Usage:
  python -m app.simulate chat                 # interactive REPL: you play the citizen
  python -m app.simulate script <file>        # hands-free: replay a scenario line by line
  python -m app.simulate script <file> +919xxxxxxx --keep  # reuse an existing claim's phone

REPL commands (also allowed inside script files, one per line):
  /loc                 attach the Pune GPS pin (exercises district matching)
  /btn confirm         tap a review button: confirm | change | human
  /img path [caption]  attach a photo (exercises the media path)
  /voice path          attach a voice note (transcribed offline, see below)
  /state /facts /reset /quit

A /voice line uses the sibling .txt of the audio file if present
(demo_script voice notes ship without Bhashini keys; set BHASHINI_* and drop
the .txt to use real ASR instead).

By default the simulator runs against a throwaway DB (so demos don't pollute
real intake data). Export SIMULATE_REAL_DB=1 to write to the production store.
"""
import asyncio
import os
import sys
import tempfile
import uuid

# isolated demo store unless explicitly asked for the real one
if not os.environ.get("SIMULATE_REAL_DB"):
    _tmp = tempfile.mkdtemp(prefix="relief_sim_")
    os.environ["DB_PATH"] = os.path.join(_tmp, "demo.db")
    os.environ["MEDIA_DIR"] = _tmp

from app import agent, asr, store, wa  # noqa: E402
from app.config import settings  # noqa: E402

REAL_DB = bool(os.environ.get("SIMULATE_REAL_DB"))
PHONE_DEFAULT = "+919999900001"


# ---- fake channel: print instead of send, synthesize instead of download -----

def _civ(s: str) -> str:  # citizen on the demo stage
    return f"\033[1;32m  you>\033[0m {s}"


def _bot(s: str) -> str:
    return f"\033[1;34m  bot>\033[0m {s}"


def _install_fake_channel() -> None:
    async def _text(to, text):
        print(_bot(text))
        return {}

    async def _buttons(to, text, buttons):
        print(_bot(text))
        print(_bot("   [ " + " | ".join(f"{n} ({i})" for i, n in buttons) + " ]"))
        return {}

    async def _document(to, link, filename, caption=""):
        print(_bot(f"📄 document delivered: {filename}"))
        if link:
            print(_bot(f"    {link}"))
        return {}

    async def _audio(to, data, mime="audio/wav"):
        path = settings.media_dir / "sim_audio.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(_bot(f"🔊 voice note ({len(data) // 1024} kB): {path}"))
        return {}

    async def _flow(to, text, claim_id):
        print(_bot(text))
        print(_bot("   [ review flow / buttons: confirm | change | human ]"))
        return {}

    async def _download(media_id):
        # demo media travels as local file paths
        try:
            return open(media_id, "rb").read(), ""
        except OSError:
            return f"simulated {media_id}".encode(), ""

    async def _fake_tts(text, lang="mr"):
        raise RuntimeError("simulator mode: TTS additive only")

    wa.send_text, wa.send_buttons, wa.send_document = _text, _buttons, _document
    wa.send_audio, wa.send_flow, wa.download_media = _audio, _flow, _download
    agent.DEBOUNCE_S = 0  # reply immediately, this is a solo conversation
    try:  # offline ASR: prefer a sibling .txt (scripted demo), else echo a canned line
        orig = asr.transcribe

        async def _asr(data, lang="mr"):
            try:
                return orig(data, lang)
            except Exception:  # noqa: BLE001 - demo fallback
                return "माझं नाव ओजस आहे. २० जुलै २०२६ ला मुंबईत भीषण पावसात घराचा ताफा नुकसान झाला."
        asr.transcribe = _asr
    except Exception:  # noqa: BLE001
        pass


def _msg(kind: str, body: dict, mid: str | None = None) -> dict:
    return {"id": mid or f"sim-{uuid.uuid4().hex[:10]}", "from": PHONE.get(), "type": kind, **body}


# ---- current phone (the "citizen" you are playing) ----------------------------

class _Phone:
    value = PHONE_DEFAULT

    def get(self):
        return self.value


PHONE = _Phone()


# ---- scripted REPL ------------------------------------------------------------

HELP = """commands: /loc /btn <confirm|change|human> /img <path> [caption] /voice <path>
/state /facts /reset /phone <number> /quit"""


async def _cmd(line: str) -> bool:
    if not line.startswith("/"):
        msg = {"type": "text", "text": {"body": line}}
        await agent.handle(_msg("text", msg), "Demo Citizen")
        return True
    cmd, _, rest = line.partition(" ")
    if cmd == "/loc":
        await agent.handle(_msg("location", {"location": {"latitude": 18.5204, "longitude": 73.8567}}), "")
        print(_civ("📍 GPS pin: Pune"))
    elif cmd == "/btn":
        bid = rest.strip() or "confirm"
        await agent.handle(_msg("interactive", {"interactive": {"button_reply": {"id": bid, "title": bid}}}), "")
        print(_civ(f"🔘 button: {bid}"))
    elif cmd == "/img":
        path, _, caption = rest.partition(" ")
        p = path.strip() or "sim"
        if not os.path.exists(p):  # no file? synthesize a placeholder image
            p = os.path.join(tempfile.gettempdir(), f"sim-img-{uuid.uuid4().hex[:6]}.jpg")
            open(p, "wb").write(b"\xff\xd8\xff\xe0simulated jpg\x00")
        await agent.handle(_msg("image", {"image": {"id": p, "caption": caption.strip()}}), "")
        print(_civ(f"🖼  photo attached: {p}"))
    elif cmd == "/voice":
        p = rest.strip()
        await agent.handle(_msg("audio", {"audio": {"id": p or "sim", }}), "")
        print(_civ("🎙  voice note sent"))
    elif cmd == "/state":
        c = store.get_claim(store.open_claim(PHONE.get())["id"])
        print(_bot(f"claim #{c['id']} · {c['state']} · lang {c.get('lang')}"))
    elif cmd == "/facts":
        c = store.get_claim(store.open_claim(PHONE.get())["id"])
        print(_bot(f"facts: {c['data'].get('facts')}"))
        print(_bot(f"results: {c['data'].get('results')}"))
    elif cmd == "/reset":
        c = store.get_claim(store.open_claim(PHONE.get())["id"])
        c["state"], c["data"] = "INTAKE", {"asked_rounds": 0, "utterances": []}
        store.save_claim(c)
        print(_bot(f"claim #{c['id']} reset"))
    elif cmd == "/phone":
        PHONE.value = rest.strip() or PHONE_DEFAULT
        print(_bot(f"citizen phone -> {PHONE.value}"))
    elif cmd == "/quit":
        return False
    elif cmd == "/help":
        print(_bot(HELP))
    else:
        print(_bot(f"unknown: {cmd} (try /help)"))
    return True


def _msg(kind: str, body: dict, mid: str | None = None) -> dict:
    return {"id": mid or f"sim-{uuid.uuid4().hex[:10]}", "from": PHONE.get(), "type": kind, **body}

async def chat() -> None:
    _install_fake_channel()
    print(_bot("Relief Copilot local demo — you are the citizen. " + HELP))
    while await _cmd(await asyncio.to_thread(input, "\033[1;32m  you>\033[0m ")):
        pass
    print(_bot("bye"))


async def script(path: str) -> None:
    _install_fake_channel()
    lines = [l.strip() for l in open(path, encoding="utf-8").read().splitlines() if l.strip() and not l.strip().startswith("#")]
    for i, line in enumerate(lines):
        if line.startswith("PAUSE"):
            await asyncio.sleep(float(line.split()[1] or 0.5))
            continue
        print(_civ(line))
        if not await _cmd(line):
            break
        await asyncio.sleep(0.8)
    print(_bot("script finished — open the /admin dashboard to review the claim"))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="local Relief Copilot demo (no WhatsApp)")
    ap.add_argument("mode", choices=["chat", "script"])
    ap.add_argument("script", nargs="?", help="scenario file for script mode")
    ap.add_argument("--phone", default=PHONE_DEFAULT, help="citizen phone (E.164)")
    args = ap.parse_args()
    PHONE.value = args.phone
    try:
        asyncio.run(chat() if args.mode == "chat" else script(args.script or "data/demo_script.txt"))
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
