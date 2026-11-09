# Handoff notes — WhatsApp demo state (Nov 2026)

Read this before touching the channel configs. Everything below was verified by
running the real pipeline (logs show Graph 200-OK / Twilio done-400 tests).

## What works

| Layer | State |
| --- | --- |
| Agent / extraction / rules / PDF | ✅ unchanged, all tests pass |
| Meta Cloud API channel (`MESSAGE_CHANNEL=meta`) | ✅ sends verified working (Graph 200 OK) with the permanent System User token in `backend/.env` |
| Twilio channel (`MESSAGE_CHANNEL=twilio`) | ✅ code + smoke tests pass (signature, converters, quick-reply payloads) |
| Local demo simulator | ✅ full intake → clarify → review → PDF inside the terminal, no WhatsApp needed |

## What is blocked, and by what

1. **Meta delivery to Indian numbers fails with 131031 "Business Account locked"**.
   Root cause found via the health API: the business portfolio has **not passed
   business verification** (error 141010, WABA itself shows APPROVED). Unblock =
   Business Settings → Business info → Start verification. Verification needs a
   tax ID (GST/UDYAM/PAN) or document route.
2. **Twilio trial cannot send anything programmatically** (freeform rejected 21654
   "ContentSid Required"; Content API 20003 trial-gated). Upgrade the account
   (~$20) and Twilio works with zero Meta paperwork: Content API unlocks, the
   sandbox/number accepts freeform in-session replies, register the quick-reply
   template with the curl in `backend/README.md`, set `TWILIO_QR_SID`, flip
   `MESSAGE_CHANNEL=twilio`.

## How to switch channels

Both backends live behind one module (`app/wa.py`); `agent.py` never knows which.
Set in `backend/.env`: `MESSAGE_CHANNEL=meta` or `=twilio`, plus that channel's
credentials (see `backend/.env.example` and the channel sections in
`backend/README.md`). Cloudflared needs重启ing for a fresh public URL; update the
webhook URL in whichever dashboard (Meta app / Twilio "When a message comes in").

## Demo without WhatsApp (works today)

```bash
cd backend
python -m app.simulate chat                       # you type as the citizen
python -m app.simulate script data/demo_script.txt  # hands-free
# SIMULATE_REAL_DB=1 to mirror the claim into the /admin dashboard (run uvicorn alongside)
```

Includes a typed fallback for review buttons (Marathi/Hindi/English words map to
`confirm/change/human`) because Twilio-trial has no interactive templates.

## Secrets

`backend/.env` holds all live keys (WA permanent token, Twilio SID/token, Groq).
It is gitignored — get it from the previous owner, never commit it. Rotate the
Twilio Auth Token and Groq key periodically; they were pasted into a chat.

## Known code notes

- `send_buttons` on Twilio needs the `twilio_qr_sid` Content template inactive
  (trial) and degrades to a text prompt until it exists.
- Outbound read receipts: no-op on Twilio (webhook status events only).
- Twilio inbound media arrives as URLs (`/mediafile/` route serves what we send).
