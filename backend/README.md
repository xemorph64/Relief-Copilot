# Relief Copilot backend

WhatsApp agent + rule engine + dashboard API. See the PRD for the design.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in keys
python -m pytest -q         # rule engine + agent flow tests
python -m uvicorn app.main:app --port 8000
cloudflared tunnel --url http://localhost:8000   # public HTTPS URL for Meta's webhook
```

In Meta's app dashboard set the webhook to `https://<tunnel>/webhook`, verify token = `WA_VERIFY_TOKEN`,
subscribe to `messages`. Put the tunnel URL in `PUBLIC_BASE_URL` so PDFs can be delivered.

## Admin dashboard

Open `https://<tunnel>/admin/` (or http://localhost:8000/admin/ locally): confidence-sorted review
queue, per-claim detail with event log, district filing-density chart, live updates over SSE
(`GET /api/claims`, `GET /api/claims/{id}`, `GET /api/events/stream`).

## Review over WhatsApp Flow + TTS (optional)

The review step ships as native reply buttons by default. For the multi-screen Flow (F11):

1. Dashboard > WhatsApp > Flows: upload `app/static/review_flow.json`, publish it, put its id in `WA_FLOW_ID`.
2. Set the Flow's data endpoint to `https://<tunnel>/api/flows/{claim_id}` and its integrity
   passphrase to `FLOW_ENDPOINT_PASSPHRASE`.
3. Every review message then also gets a voice playback of the summary via Bhashini TTS (additive;
   buttons/Flow always arrive first).

## Retroactive re-evaluation (F15)

After ingesting a new GR and adding rules to `data/rules/`:

```bash
curl -X POST "http://localhost:8000/api/reeval"          # dry: list changed claims
curl -X POST "http://localhost:8000/api/reeval?notify=1" # also message citizens in REVIEW state
```

## Layout

| File | Job |
| --- | --- |
| `app/main.py` | Webhook (signature check, dedupe, fast ack), dashboard API, SSE event stream, PDF files |
| `app/agent.py` | Per-claim state machine: intake, one batched question, review, confirm, PDF |
| `app/extract.py` | Claude fills form fields from what the citizen said (never money) |
| `app/rules.py` | Deterministic resolver + engine; the only code that produces amounts |
| `app/asr.py` | Bhashini speech-to-text |
| `app/geo.py` | GPS pin to district |
| `app/rainfall.py` | Rainfall around the incident date (evidence) |
| `app/grwatcher.py` | Crawl gr.maharashtra.gov.in, download relief GRs, fingerprint |
| `app/verify_rule.py` | Two-person sign-off that publishes a rule |
| `app/tts.py` | Bhashini text-to-speech: the review summary played back as a voice note |
| `app/flows.py` | WhatsApp Flow data-exchange handler for the review screen |
| `app/reeval.py` | Retroactive re-evaluation of open claims after new rules are ingested |
| `app/static/` | Admin dashboard (single-file HTML/JS) and the review Flow JSON |

## Data

- `data/gr/` official GR PDFs (SHA-256 in `index.json`), fetched only from gr.maharashtra.gov.in
- `data/rules/` rule JSON; each rule cites GR ref, page, item and quote. Status `drafted` until two
  people run `python -m app.verify_rule sign <rule_id> <name>` against the PDF page.
- `data/geo/` Maharashtra district boundaries (36 districts, MIT-licensed community dataset)

Until rules are signed, the agent answers every asset with "rule not verified" - by design.

## GR Watcher

```bash
python -m app.grwatcher scan                 # last ~week of GRs, keeps relief-related ones
python -m app.grwatcher fetch <18-digit-ref> # older GRs; find the ref via the portal's search (captcha, by hand)
```
