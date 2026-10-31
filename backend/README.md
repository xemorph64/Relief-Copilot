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
