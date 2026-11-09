"""Per-claim state machine. Code owns the flow; Claude only fills form fields (extract.py);
amounts come only from rules.py.

NEW -> INTAKE -> (CLARIFY <-> INTAKE) -> REVIEW -> DELIVERED -> WATCHING
                                      +-> NEEDS_HUMAN
"""
import asyncio
import datetime as dt
import logging

from app import asr, geo, rainfall, rules, store, wa
from app.config import settings
from app.extract import extract

log = logging.getLogger("agent")
DEBOUNCE_S = 20  # wait for the rest of a burst (voice note + photos + pin) before thinking
CONF = 0.75
_locks: dict[int, asyncio.Lock] = {}
_timers: dict[int, asyncio.Task] = {}

T = {  # user-facing text; keep each language in step
    "welcome": {
        "mr": "नमस्कार! मी रिलीफ कोपायलट. आपत्तीत झालेल्या नुकसानीचा सरकारी मदतीचा अर्ज मी तुमच्यासाठी भरतो.\n"
              "1) काय नुकसान झाले ते व्हॉइस नोटमध्ये सांगा\n2) 2-3 फोटो पाठवा\n3) लोकेशन पाठवा",
        "hi": "नमस्ते! मैं रिलीफ कोपायलट हूँ। आपदा में हुए नुकसान का सरकारी सहायता आवेदन मैं आपके लिए भरता हूँ।\n"
              "1) क्या नुकसान हुआ, वॉइस नोट में बताइए\n2) 2-3 फोटो भेजिए\n3) लोकेशन भेजिए",
        "en": "Hello! I'm Relief Copilot. I fill the government disaster-relief claim form for you.\n"
              "1) Describe your loss in a voice note\n2) Send 2-3 photos\n3) Share your location"},
    "ask_intro": {"mr": "अर्ज जवळजवळ तयार आहे. फक्त हे सांगा:", "hi": "आवेदन लगभग तैयार है। बस यह बताइए:",
                  "en": "Almost done. Just tell me:"},
    "q_hazard": {"mr": "कोणत्या आपत्तीमुळे नुकसान झाले? (पूर, अतिवृष्टी, वादळ, दरड...)",
                 "hi": "किस आपदा से नुकसान हुआ? (बाढ़, भारी बारिश, तूफ़ान, भूस्खलन...)",
                 "en": "What disaster caused the loss? (flood, heavy rain, cyclone, landslide...)"},
    "q_incident_date": {"mr": "नुकसान कोणत्या तारखेला झाले?", "hi": "नुकसान किस तारीख को हुआ?",
                        "en": "On what date did it happen?"},
    "q_location": {"mr": "तुमचे गाव कोणते? (किंवा 📍 लोकेशन पाठवा)", "hi": "आपका गाँव कौन सा है? (या 📍 लोकेशन भेजिए)",
                   "en": "Which village? (or share your 📍 location)"},
    "q_assets": {"mr": "नक्की काय नुकसान झाले? (घर पक्के/कच्चे, पूर्ण/अंशतः पडले, किती जनावरे...)",
                 "hi": "ठीक-ठीक क्या नुकसान हुआ? (घर पक्का/कच्चा, पूरा/आंशिक गिरा, कितने पशु...)",
                 "en": "What exactly was lost? (house pucca/kutcha, fully/partly damaged, how many animals...)"},
    "q_applicant_name": {"mr": "अर्जदाराचे पूर्ण नाव?", "hi": "आवेदक का पूरा नाम?", "en": "Applicant's full name?"},
    "review_head": {"mr": "तुमचा अर्ज:", "hi": "आपका आवेदन:", "en": "Your claim:"},
    "not_verified": {"mr": "नियम अद्याप पडताळलेला नाही - रक्कम सांगता येत नाही",
                     "hi": "नियम अभी सत्यापित नहीं - राशि नहीं बता सकते",
                     "en": "rule not verified yet - no amount shown"},
    "needs_review": {"mr": "अधिकारी तपासतील", "hi": "अधिकारी जाँच करेंगे", "en": "an official will check"},
    "total": {"mr": "एकूण", "hi": "कुल", "en": "Total"},
    "confirm_q": {"mr": "हे बरोबर आहे का?", "hi": "क्या यह सही है?", "en": "Is this correct?"},
    "btn_yes": {"mr": "बरोबर आहे", "hi": "सही है", "en": "Correct"},
    "btn_change": {"mr": "बदल करायचा", "hi": "बदलाव करना है", "en": "Change"},
    "btn_human": {"mr": "अधिकाऱ्याशी बोला", "hi": "अधिकारी से बात", "en": "Talk to official"},
    "change_ask": {"mr": "काय बदलायचे ते सांगा (व्हॉइस नोट चालेल).", "hi": "क्या बदलना है बताइए (वॉइस नोट चलेगा)।",
                   "en": "Tell me what to change (a voice note is fine)."},
    "confirmed": {"mr": "धन्यवाद! तुमचा अर्ज तयार आहे.", "hi": "धन्यवाद! आपका आवेदन तैयार है।",
                  "en": "Thank you! Your claim form is ready."},
    "human": {"mr": "ठीक आहे, एक अधिकारी तुमचा अर्ज पाहतील.", "hi": "ठीक है, एक अधिकारी आपका आवेदन देखेंगे।",
              "en": "OK, an official will look at your claim."},
    "asr_fail": {"mr": "व्हॉइस नोट समजली नाही. कृपया पुन्हा पाठवा किंवा लिहून सांगा.",
                 "hi": "वॉइस नोट समझ नहीं आई। कृपया दोबारा भेजें या लिखकर बताएं।",
                 "en": "I couldn't understand the voice note. Please resend or type it."},
    "reeval": {"mr": "नवीन शासन निर्णय लागू झाला आहे. तुमची मदत आता {amount} होऊ शकते. जुने अर्ज बदलण्यासाठी 'बदल' दाबा.",
               "hi": "एक नया शासकीय निर्णय लागू हुआ है। आपकी सहायता अब {amount} हो सकती है। बदलने के लिए 'बदलाव' दबाएं।",
               "en": "A new government resolution applies to your claim. Your assistance may now be {amount}. Press 'Change' to update."},
}


def t(key: str, lang: str | None) -> str:
    return T[key].get(lang or "mr", T[key]["en"])


# Typed versions of the review buttons (lowercase). Needed because Twilio trials
# lack the Content API, so interactive quick-replies can degrade to "reply with
# one of these words".
_TYPED_BUTTONS = {
    "confirm": "confirm", "yes": "confirm", "ok": "confirm", "होय": "confirm",
    "बरोबर": "confirm", "बरोबर आहे": "confirm", "सही": "confirm", "सही है": "confirm", "ठीक": "confirm",
    "change": "change", "बदल": "change", "बदल करायचा": "change", "बदलाव": "change",
    "human": "human", "official": "human", "अधिकारी": "human", "अधिकाऱ्याशी बोला": "human", "अधिकारी से बात": "human",
}


async def handle(msg: dict, profile_name: str = "") -> None:
    """Entry point for one inbound WhatsApp message (already signature-checked and deduped)."""
    phone = msg["from"]
    claim = store.open_claim(phone)
    async with _locks.setdefault(claim["id"], asyncio.Lock()):
        claim = store.get_claim(claim["id"])
        d = claim["data"]
        kind = msg["type"]
        store.save_message(msg["id"], claim["id"], "in", kind, msg)
        store.event(claim["id"], "message_in", {"type": kind})
        if profile_name:
            d.setdefault("wa_profile_name", profile_name)

        if kind == "audio":
            audio, _ = await wa.download_media(msg["audio"]["id"])
            path = _save_media(claim["id"], msg["id"], audio, "ogg")
            try:
                text = await asr.transcribe(audio, claim.get("lang") or "mr")
                d.setdefault("utterances", []).append({"kind": "voice", "text": text, "media": path})
                store.event(claim["id"], "transcribed", {"text": text})
            except Exception as e:  # noqa: BLE001 - any ASR failure means: ask to resend
                log.warning("asr failed: %s", e)
                store.event(claim["id"], "error", {"stage": "asr", "error": str(e)})
                await wa.send_text(phone, t("asr_fail", claim.get("lang")))
        elif kind == "image":
            img, _ = await wa.download_media(msg["image"]["id"])
            d.setdefault("photos", []).append(_save_media(claim["id"], msg["id"], img, "jpg"))
            if msg["image"].get("caption"):
                d.setdefault("utterances", []).append({"kind": "text", "text": msg["image"]["caption"]})
        elif kind == "location":
            lat, lon = msg["location"]["latitude"], msg["location"]["longitude"]
            d["location"] = {"lat": lat, "lon": lon, "district": geo.district_at(lat, lon)}
            store.event(claim["id"], "located", d["location"])
        elif kind == "interactive":
            reply = msg["interactive"].get("button_reply") or msg["interactive"].get("list_reply") or {}
            claim["data"] = d
            return await _on_button(claim, reply.get("id", ""))
        elif kind == "text":
            body = msg["text"]["body"].strip()
            if body.upper() in ("HUMAN", "STOP"):
                claim["data"] = d
                return await _on_button(claim, "human")
            if claim["state"] == "REVIEW" and body.lower() in _TYPED_BUTTONS:
                # interactive buttons unavailable / templateless: typed reply works the same
                store.event(claim["id"], "button", {"id": _TYPED_BUTTONS[body.lower()], "typed": True})
                claim["data"] = d
                return await _on_button(claim, _TYPED_BUTTONS[body.lower()])
            d.setdefault("utterances", []).append({"kind": "text", "text": body})
        else:
            store.event(claim["id"], "ignored", {"type": kind})

        if claim["state"] == "NEW":
            claim["state"] = "INTAKE"
            if not d.get("utterances"):
                await wa.send_text(phone, t("welcome", _guess_lang(msg)))
        claim["data"] = d
        store.save_claim(claim)
    _schedule(claim["id"])


def _guess_lang(msg: dict) -> str:
    body = (msg.get("text") or {}).get("body", "")
    if any("ऀ" <= ch <= "ॿ" for ch in body):
        return "hi" if any(w in body for w in ("है", "हुआ", "मेरा", "मेरी")) else "mr"
    return "en" if body else "mr"


def _save_media(cid: int, mid: str, data: bytes, ext: str) -> str:
    folder = settings.media_dir / str(cid)
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{mid}.{ext}"
    p.write_bytes(data)
    return str(p)


def _schedule(cid: int) -> None:
    if (old := _timers.get(cid)) and not old.done():
        old.cancel()
    _timers[cid] = asyncio.create_task(_debounced(cid))


async def _debounced(cid: int) -> None:
    await asyncio.sleep(DEBOUNCE_S)
    async with _locks.setdefault(cid, asyncio.Lock()):
        claim = store.get_claim(cid)
        if claim["state"] in ("INTAKE", "CLARIFY") and claim["data"].get("utterances"):
            try:
                await step(claim)
            except Exception as e:  # noqa: BLE001 - keep the claim, surface on dashboard
                log.exception("step failed")
                store.event(cid, "error", {"stage": claim["state"], "error": str(e)})


async def step(claim: dict) -> None:
    d, phone = claim["data"], claim["phone"]
    said = "\n".join(f"- ({u['kind']}) {u['text']}" for u in d.get("utterances", []))
    known = {"district_from_gps": (d.get("location") or {}).get("district"),
             "whatsapp_profile_name": d.get("wa_profile_name")}
    facts = await extract(said, known, dt.date.today().isoformat())
    f = facts.model_dump()
    f["district"] = f["district"] or known["district_from_gps"]
    claim["lang"] = facts.language
    d["facts"] = f
    store.event(claim["id"], "extracted", f)

    missing = []
    if not f["hazard"] or f["hazard_confidence"] < CONF:
        missing.append("q_hazard")
    if not f["incident_date"] or f["incident_date_confidence"] < CONF:
        missing.append("q_incident_date")
    if not f["district"] or (not f["village"] and not d.get("location")):
        missing.append("q_location")
    if not f["assets"] or any(a["confidence"] < CONF or a["asset_class"] == "other" for a in f["assets"]):
        missing.append("q_assets")
    if not f["applicant_name"] or f["applicant_name_confidence"] < CONF:
        missing.append("q_applicant_name")

    asked = d.setdefault("asked_rounds", 0)
    if missing and asked < 2:
        d["asked_rounds"] = asked + 1
        claim["state"] = "CLARIFY"
        store.save_claim(claim)
        store.event(claim["id"], "asked", {"fields": missing})
        q = "\n".join(f"{i}. {t(k, claim['lang'])}" for i, k in enumerate(missing, 1))
        await wa.send_text(phone, f"{t('ask_intro', claim['lang'])}\n{q}")
        return
    if missing:
        claim["state"] = "NEEDS_HUMAN"
        store.save_claim(claim)
        store.event(claim["id"], "escalated", {"reason": "fields_missing_after_2_asks", "fields": missing})
        await wa.send_text(phone, t("human", claim["lang"]))
        return

    if (loc := d.get("location")) and not d.get("rainfall"):
        try:
            d["rainfall"] = await rainfall.around(loc["lat"], loc["lon"], f["incident_date"])
            store.event(claim["id"], "evidence", {"rainfall_max_3day_mm": d["rainfall"]["max_3day_mm"],
                                                  "source": d["rainfall"]["source"]})
        except Exception as e:  # noqa: BLE001 - evidence is supporting context, never blocking
            store.event(claim["id"], "error", {"stage": "rainfall", "error": str(e)})

    all_rules = rules.load_rules()
    results = []
    for a in f["assets"]:
        r = rules.evaluate(all_rules, {"hazard": f["hazard"], "incident_date": f["incident_date"],
                                       "district": f["district"], "asset_class": a["asset_class"],
                                       "quantity": a["quantity"]})
        results.append({"asset": a, "verdict": r["verdict"], "amount": r.get("amount"),
                        "rule_id": r["governing"]["rule_id"] if r.get("governing") else None,
                        "citation": rules.citation(r["governing"]) if r.get("governing") else None,
                        "comparison_amount": r.get("comparison_amount"), "trace": r.get("trace", []),
                        "missing_docs": r.get("missing_docs", [])})
        store.event(claim["id"], "rule_resolved", results[-1])
    d["results"] = results
    claim["state"] = "REVIEW"
    store.save_claim(claim)
    summary = _summary(claim)
    if settings.wa_flow_id:  # native multi-screen review (F11); falls back to buttons otherwise
        await wa.send_flow(phone, summary, claim["id"])
    else:
        await wa.send_buttons(phone, summary, [
            ("confirm", t("btn_yes", claim["lang"])), ("change", t("btn_change", claim["lang"])),
            ("human", t("btn_human", claim["lang"]))])
    try:  # same summary played back as speech for citizens who can't read it
        from app import tts
        voice = await tts.synthesize(summary, claim["lang"])
        await wa.send_audio(phone, voice)
        store.event(claim["id"], "tts_sent", {"lang": claim["lang"]})
    except Exception as e:  # noqa: BLE001 - TTS is additive; buttons already delivered
        store.event(claim["id"], "error", {"stage": "tts", "error": str(e)})


def _summary(claim: dict) -> str:
    lang, f, res = claim["lang"], claim["data"]["facts"], claim["data"]["results"]
    lines = [t("review_head", lang), f"{f['applicant_name']} · {f.get('village') or ''} {f['district']}",
             f"{f['hazard']} · {f['incident_date']}", ""]
    total = 0
    for r in res:
        a = r["asset"]
        head = f"• {a['description']} ×{a['quantity']}"
        if r["verdict"] == "ELIGIBLE" and r["amount"] is not None:
            total += r["amount"]
            lines.append(f"{head}: ₹{r['amount']:,}\n   ({r['citation']})")
        elif r["verdict"] == "RULE_NOT_VERIFIED":
            lines.append(f"{head}: {t('not_verified', lang)}")
        else:
            lines.append(f"{head}: {t('needs_review', lang)}")
    if total:
        lines += ["", f"{t('total', lang)}: ₹{total:,}"]
    lines += ["", t("confirm_q", lang)]
    return "\n".join(lines)


async def _on_button(claim: dict, button: str) -> None:
    phone, lang = claim["phone"], claim.get("lang")
    store.event(claim["id"], "button", {"id": button})
    if button == "confirm" and claim["state"] == "REVIEW":
        claim["state"] = "DELIVERED"
        store.save_claim(claim)
        store.event(claim["id"], "confirmed", {})
        await wa.send_text(phone, t("confirmed", lang))
        from app import pdf  # local import: reportlab is only needed here
        path = pdf.render(claim)
        store.event(claim["id"], "pdf_ready", {"path": str(path)})
        if settings.public_base_url:
            await wa.send_document(phone, f"{settings.public_base_url}/files/{path.name}", path.name)
            store.event(claim["id"], "pdf_sent", {"file": path.name})
        claim["state"] = "WATCHING"
    elif button == "change":
        claim["state"] = "CLARIFY"
        claim["data"]["asked_rounds"] = 0
        await wa.send_text(phone, t("change_ask", lang))
    elif button == "human":
        claim["state"] = "NEEDS_HUMAN"
        store.event(claim["id"], "escalated", {"reason": "citizen_asked"})
        await wa.send_text(phone, t("human", lang))
    store.save_claim(claim)
