# Relief Copilot — Product Documentation

**A WhatsApp-native AI caseworker that turns a spoken description of disaster damage into a rule-matched, evidence-backed, submission-ready government compensation claim.**

Version 1.0 · Maharashtra · 09 September 2026

---

## Contents

1. What the product is
2. Why it exists
3. Who it's for
4. What it does and does not do
5. The user journey, end to end
6. Feature specification
7. The rule system — the core of the product
8. Architecture
9. Data model
10. Evidence layer
11. WhatsApp as the channel
12. Trust, safety and data handling
13. Failure modes and how the product behaves
14. Metrics
15. Operating model and deployment
16. Roadmap
17. Known limitations
18. Glossary

---

## 1. What the product is

Relief Copilot is a conversational case-processing system that sits between a disaster-affected citizen and the government relief bureaucracy.

A citizen sends a WhatsApp voice note in Marathi or Hindi describing what they lost, adds two or three photos and shares their location. The system transcribes it, extracts structured facts, determines which government relief rule applies to that specific loss on that specific date in that specific district, assembles supporting evidence, and returns a completed, government-format claim form as a PDF along with a plain-language summary the citizen confirms before anything is generated.

It is a **case-processing pipeline**, not a chatbot. The conversation is the input method. The product is what happens after: structured extraction → versioned rule resolution → deterministic validation → evidence assembly → form generation → human confirmation → filing handoff.

**The single sentence version:** relief portals already exist and already cover houses, shops and livestock; what no system tells a citizen is *which rule applies to their loss* — because that rule changes with every disaster.

---

## 2. Why it exists

### 2.1 Government relief is the recovery channel, not insurance

Around 90% of Indian catastrophe losses are uninsured. Residential insurance penetration is below 3% of households and roughly 62% of small and micro enterprises carry no cover. When a flood destroys a house, a shop or a buffalo, the money that arrives — if any arrives — is government relief under SDRF/NDRF norms and state top-up packages.

### 2.2 The money is not the bottleneck

Maharashtra's October 2025 relief package was ₹31,628 crore across 29 of 36 districts. By December 2025, roughly 92% of the ~90 lakh affected farmers had been paid. The remainder were held up on **KYC** — bank seeding, document mismatch, identity verification — not on funding.

The failure mode is administrative, at the last mile, on paperwork.

### 2.3 Digitisation already happened and did not close the gap

This is the point most people get wrong. Self-file relief portals exist. Haryana's e-Kshatipurti covers house, livestock, crop and commercial property damage; in October 2025 it disbursed ₹4.72 crore to 2,386 people for damaged houses and perished livestock. Maharashtra runs a relief DBT system. These are real, working, citizen-facing portals.

And during the same flood that filled e-Kshatipurti, reporting described villagers struggling with the online application process. A portal gives you a form. It does not tell you which category your loss falls into, which scheme governs it, what evidence that scheme requires, or what you are entitled to.

### 2.4 The rule itself moves

This is the problem Relief Copilot actually solves. Relief norms in Maharashtra operate as a stack:

| Layer | Instrument | Dead milch animal | Cap |
|---|---|---|---|
| Base norm | SDRF/NDRF 2022-23 to 2025-26, adopted by GR 27-03-2023 | ₹37,500 | max 3 per household |
| State event package | GR 07-10-2025, ₹31,628 cr, statewide, flood | ₹32,000 | **cap revoked** |
| Regional package | Palghar / Vasai-Virar, July–August 2026 | ₹40,000 | max 3, **electoral-roll gated** |

Same state, same hazard, same animal, three different correct answers within twelve months — differing not only in amount but in cap structure and in eligibility test. The same pattern holds for shop damage: absent from the base norm, then ₹47,000–₹50,000 flat under the October 2025 package, then 75% of assessed loss capped at ₹50,000 under the Palghar package.

No citizen can track this. No static form can encode it. Determining which version of which rule applies to a given loss — by hazard, date, district and asset — is the hard problem, and it is a retrieval and reasoning problem.

---

## 3. Who it's for

### Primary user — the claimant
A rural or peri-urban household in a flood-affected district. Owns a smartphone with WhatsApp (the near-universal messaging app), limited data, variable literacy, speaks Marathi or Hindi or a code-switched mix. Has lost a house wall, a shop's stock, a buffalo, a cattle shed. Has never filed a relief claim, or filed one and had it rejected without knowing why.

They do not want a portal. They want to be told what to do and to end up with the right paper.

### Secondary user — the assisted-filing operator
A Common Service Centre operator, NGO field worker, gram sevak or panchayat volunteer filing on behalf of several households. Their bottleneck is not typing — it is knowing which category and which scheme applies to each different loss they encounter in a day.

### Tertiary user — the revenue official
A talathi or tehsildar receiving applications. Their pain is incomplete and wrongly-categorised submissions that generate rework. The admin view surfaces pre-validated claims sorted by confidence, and a district dashboard plotting hazard exposure against filing density — revealing revenue circles that were hit but produced almost no claims.

---

## 4. What it does and does not do

### In scope
- Voice-first intake in Marathi, Hindi and Hinglish over WhatsApp
- Structured extraction of loss facts with per-field confidence
- Versioned rule resolution across base norms and event packages
- Deterministic eligibility, amount, cap and required-document computation
- Evidence assembly from citizen photos, GPS, and public rainfall/flood-context data
- Document and KYC pre-flight checking before submission
- Government-format PDF generation with a plain-language summary
- Citizen confirmation before any output is finalised
- Re-evaluation of open claims when a superseding GR is published
- Claim status updates over WhatsApp
- District-level exposure-vs-filing dashboard

### Categories covered at v1
House (fully destroyed, partially damaged), hut, cattle shed, livestock (milch large, draught large, calf/donkey/pony/mule, sheep/goat/pig, poultry), and shop or stall where an applicable event package covers it.

### Explicitly out of scope
- **Crop loss.** PMFBY, DigiClaim and state crop systems already handle it with satellite-based verification. Duplicating it adds nothing.
- **Disaster prediction, forecasting or early warning.** Relief Copilot operates strictly after the event.
- **Live government portal submission.** No public API exists. The output is a ready-to-file PDF and a filing handoff.
- **Determining whether a loss actually occurred.** That is the sanctioning authority's job.
- **Legal proof.** Satellite and rainfall data are supporting context, never proof that a specific asset was damaged.

### Non-negotiable product rules
1. No compensation figure is ever shown without the Government Resolution number, date and page it came from.
2. If no authoritative rule can be retrieved, the system says **"rule not verified"** rather than guessing.
3. Nothing is submitted or finalised without explicit citizen confirmation.
4. The LLM never computes an amount.

---

## 5. The user journey, end to end

### 5.1 Intake

The citizen messages the Relief Copilot number — typically a contact card forwarded in a village WhatsApp group. There is no app to install, no account to create, no password. The phone number is the identity, and it is usually the same number seeded to their bank account for DBT.

The bot replies in the language of the incoming message and asks for three things in one message: a voice note describing what was lost, two or three photos, and a location pin.

**Example voice note:** *"Puraat majha ghar padla, ani don mhashi vaahun gelya."* (In the flood my house collapsed, and two buffaloes were washed away.)

### 5.2 Extraction and clarification

Speech is transcribed. An LLM extracts structured facts against a fixed schema with a confidence score per field:

```
hazard            flood            0.96
incident_date     ?                0.20
asset[0]          house            0.94
construction      ?                0.30
damage_level      total            0.88
asset[1]          livestock/milch  0.91
quantity          2                0.93
district          Palghar (GPS)    0.99
```

Any field below threshold becomes a question — batched into a single message, never a chain of five:

> *"Two more things and I'm done: was the house pucca or kutcha, and roughly what date did this happen?"*

This is what makes it feel like a caseworker rather than a form. The system asks only what it is missing.

### 5.3 Rule resolution

The resolver filters candidate clauses by district, incident date window and hazard, retrieves the applicable relief items, walks the supersession chain, and returns the narrowest applicable rule for each loss.

For the two buffaloes it will find both the base norm and the regional package, determine which governs, and — critically — show the citizen the comparison rather than a bare number.

### 5.4 Evidence

Photos, EXIF timestamps and GPS are packed alongside IMD district rainfall and any district warning issued around the incident date, each stored with the endpoint, query parameters and fetch time. If a flood-context layer covering the district is available, it is attached with its vintage stated.

The verdict is one of three states: **Eligible**, **Needs Review**, or **Rule Not Verified**.

### 5.5 Pre-flight

Before generating anything, the system checks the required documents and eligibility gates for the resolved rule, and reports what is missing:

> *"Your claim is ready except for one thing — this package requires your name on the electoral roll of the affected village. Here is how to check."*

This targets the actual observed failure mode. Claims fail on KYC and documents, not on merit.

### 5.6 Stacking

The same loss frequently qualifies under more than one instrument — SDRF relief plus a housing scheme plus a loan-recovery suspension plus a fee waiver. The system lists what else this loss may qualify for so the citizen does not file for one of four things they are entitled to.

### 5.7 Review and confirmation

The citizen receives a plain-language summary as a WhatsApp Flow — a native multi-screen form inside the chat, no browser, no link:

> **Your claim**
> House, fully destroyed — ₹1,20,000 *(GR 27-03-2023, item 3, p.5)*
> 2 milch animals — ₹80,000 *(Palghar package Jul 2026, item 4(b), p.3)*
> **Total: ₹2,00,000**
> Evidence attached: 3 photos, location, IMD rainfall for 19 July.
> Missing: electoral roll entry.
>
> *Is this correct?*

If they cannot read it, the same summary is played back as speech in their language and confirmed by voice.

### 5.8 Delivery

On confirmation, the filled PDF arrives as a WhatsApp document. The citizen forwards it to a talathi, prints it at a CSC, or carries the phone to the tehsil office. Everything — the conversation, the photos, the citations, the final PDF — remains in their own chat history on their own device.

### 5.9 Re-evaluation

Weeks later, a new Government Resolution is published covering that district and date window. It is ingested as a versioned override. Every open claim in scope is recomputed, and affected citizens receive a message:

> *"A new government order (GR 07-10-2025) applies to your claim. Your assistance may increase from ₹37,500 to ₹1,60,000. Reply YES to regenerate your form."*

This is the feature that cannot exist without versioned rules, and it is the reason the product is a system rather than a form-filler.

---

## 6. Feature specification

| # | Feature | Description | Priority |
|---|---|---|---|
| F1 | WhatsApp intake | Voice note, photos, location, text — all native | P0 |
| F2 | Multilingual ASR | Marathi, Hindi, Hinglish transcription | P0 |
| F3 | Structured extraction | Schema-constrained facts with per-field confidence | P0 |
| F4 | Clarification loop | Batched questions for low-confidence fields only | P0 |
| F5 | GR corpus + retrieval | Item-level chunks, metadata-filtered hybrid search | P0 |
| F6 | **Versioned rule resolver** | Supersession walk by hazard/date/district/asset | P0 |
| F7 | Deterministic rule engine | Amount, cap, thresholds, required documents | P0 |
| F8 | Evidence assembly | Photos, EXIF, GPS, IMD rainfall, flood context | P0 |
| F9 | Three-state verdict | Eligible / Needs Review / Rule Not Verified | P0 |
| F10 | Citation display | GR number, date, page beside every amount | P0 |
| F11 | Plain-language review | WhatsApp Flow + TTS playback | P0 |
| F12 | PDF generation | Government-format template, delivered as document | P0 |
| F13 | Audit trail | Retrieved pages, rule version, model version, hashes | P0 |
| F14 | Document pre-flight | Missing document and KYC gate detection | P1 |
| F15 | **Retroactive re-evaluation** | Recompute open claims on new GR ingestion | P1 |
| F16 | Scheme stacking | Surface other applicable schemes | P1 |
| F17 | Status updates | Utility-template notifications | P1 |
| F18 | Admin review queue | Confidence-sorted claims for officials | P1 |
| F19 | District dashboard | Exposure vs filing density by revenue circle | P1 |
| F20 | Returning-claimant memory | Reuse asset registry and documents next disaster | P2 |
| F21 | IVR / SMS fallback | Feature-phone channel | P2 |
| F22 | Additional states | Corpus expansion beyond Maharashtra | P2 |

---

## 7. The rule system — the core of the product

Everything else is plumbing. This is the product.

### 7.1 Rules are data, never prompt text

Every relief norm is a JSON object, version-controlled in git, diffable, and independently testable:

```json
{
  "rule_id": "MH.LIVESTOCK.MILCH_LARGE.PALGHAR_2026",
  "when": { "asset": "livestock", "class": "milch_large", "hazard": "flood" },
  "amount": 40000,
  "unit": "per_animal",
  "cap": { "type": "count_per_household", "value": 3 },
  "eligibility_gates": ["electoral_roll_entry", "ration_card"],
  "requires": ["ownership_proof", "death_certification", "photo", "location"],
  "geo_scope": { "level": "district", "ids": ["Palghar", "Vasai-Virar"] },
  "applies_from": "2026-07-01",
  "applies_to": null,
  "supersedes": "MH.LIVESTOCK.MILCH_LARGE.STATE_2025_10",
  "source_ref": {
    "gr": "…", "date": "2026-07-xx", "page": 3, "item": "4(b)",
    "checksum": "sha256:…"
  }
}
```

### 7.2 Resolution algorithm

```
resolve(hazard, incident_date, district, asset_class):
    candidates = rules where
        asset_class matches when.asset/class
        and hazard ∈ when.hazard
        and incident_date ∈ [applies_from, applies_to]
        and district ∈ geo_scope
    order candidates by specificity:
        district-scoped  >  state-scoped  >  national base norm
    walk supersedes chain, drop any rule superseded within scope
    return narrowest surviving rule, plus base_rule for comparison
```

Two rules surviving at equal specificity is not resolved by guessing — it routes to **human review**.

### 7.3 Retrieval feeds the engine; it never replaces it

The retriever's only job is to propose which clauses might apply. The engine decides.

- **Chunking:** by relief item row, never fixed-token. One chunk per (item, sub-item), semantically complete and independently citable.
- **Metadata prefilter first:** district, date window, hazard. This is what makes temporal resolution work — most of the corpus is eliminated before any semantic search runs.
- **Hybrid search:** BM25 plus dense embeddings, then a cross-encoder rerank.
- **Chunk metadata:** `gr_number, gr_date, page, item_no, category, language, applies_from, applies_to, hazard_scope, geo_scope, supersedes, superseded_by, source_url, checksum`.

### 7.4 Why the LLM is barred from computing amounts

This is an evidence-based design decision, not caution for its own sake.

Stanford RegLab and Yale published the first preregistered evaluation of commercial legal RAG tools (*Hallucination-Free?*, Journal of Empirical Legal Studies, 2025). Purpose-built, retrieval-grounded, professionally sold legal research systems hallucinated **17–33%** of the time. Lexis+ AI was accurate on 65% of queries; Westlaw's AI-Assisted Research on roughly 42%.

Their error taxonomy maps directly onto this domain: jurisdiction confusion, authority-hierarchy violation, **temporal misapplication**, entity substitution, and **sycophancy** — the model agreeing with a user's incorrect premise and constructing support for it. A distressed claimant asking *"I should get 1.2 lakh, right?"* is exactly that trap.

Follow-on statutory benchmarking found a structured tool reaching 83% accuracy where commercial AI statutory tools scored 58% and 64% — worse than plain RAG. **Structure beats model size on statutory work.**

Hence the division: the LLM extracts facts and explains rules in plain language; a deterministic engine computes money.

### 7.5 Corpus maintenance

New GRs are ingested through the same pipeline: OCR, table reconstruction, item-level chunking, metadata attachment, checksum, index. Adding the next event package is a data operation, not a code change — which is precisely what makes F15 (retroactive re-evaluation) cheap to run.

The corpus, not the code, is the defensible asset. A versioned, geo- and date-scoped rule store spanning base norms and every state and regional package represents weeks of OCR and Marathi table cleanup.

---

## 8. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ CHANNEL — WhatsApp Business Platform (Cloud API)             │
│ voice note · photos · location pin · Flows · document out    │
└───────────────────────────┬──────────────────────────────────┘
                            │ signed webhook
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ GATEWAY — FastAPI                                            │
│ signature verification · idempotency by message_id           │
│ media fetch → own object storage → delete from Meta          │
└──────────────────────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ CONVERSATION STATE MACHINE — Redis                           │
│ INTAKE → CLARIFY → RESOLVE → EVIDENCE → PREFLIGHT →          │
│ REVIEW → DELIVERED → WATCHING                                │
│ tracks the 24-hour window; minimises outbound turns          │
└───────────────┬──────────────────────────┬───────────────────┘
                ▼                          ▼
┌───────────────────────────┐  ┌───────────────────────────────┐
│ ASR — Bhashini / ULCA     │  │ VISION — asset type, damage   │
│ mr · hi · hinglish        │  │ hint, EXIF, geotag            │
└───────────────┬───────────┘  └───────────────┬───────────────┘
                └──────────────┬───────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ EXTRACTOR — LLM, JSON-schema constrained                     │
│ facts + per-field confidence → clarification loop            │
└──────────────────────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ RULE RESOLVER                                                │
│ metadata prefilter → hybrid retrieval → rerank →             │
│ supersession walk → narrowest applicable rule                │
└──────────────────────────────────────────────────────────────┘
```

## 9. Data model

Single-process SQLite (`data/relief.db`), one file; promoted to Postgres only when more than one worker is needed.

**claims** — `id, phone, state, lang, channel, data(JSON), created, updated`
- `state` ∈ {NEW, INTAKE, CLARIFY, REVIEW, DELIVERED, WATCHING, NEEDS_HUMAN}; OPEN = {NEW, INTAKE, CLARIFY, REVIEW} — everything before citizen confirmation.
- `data` carries the claim JSON: `facts` (extraction output), `results` (rule evaluation per asset), `photos`, `location`, `rainfall`, `asked_rounds`, `utterances`, `wa_profile_name`, `reevaluated_at`.

**messages** — `wa_id PK, claim_id, direction, type, body, ts` (idempotency key = Meta message id).

**events** — `id, claim_id, kind, payload(JSON), actor, ts` — the full audit trail (F13); streamed to the admin dashboard over SSE (`GET /api/events/stream`).

**Rules as data** — `data/rules/*.json`, version-controlled in git, diffable, independently testable. Each rule carries `status` and `verifications[]`; a rule is usable only when `status == "published"` with sign-offs from two different verifiers (maker-checker).

**GR index** — `data/gr/index.json`: ref → {department, title, date, url, sha256, bytes, status}. Fingerprinted so re-ingestion is idempotent.

## 10. Evidence layer

Per claim, the evidence pack stores:
- Citizen photos (2–3) with the local media path; image captions are treated as text utterances.
- GPS pin → district via `data/geo/maharashtra_districts.topo.json` (36 districts; community MIT dataset; suggestion only, citizen confirms).
- Rainfall around the incident date (±3 days) from Open-Meteo archive reanalysis — clearly labelled **"not IMD"**; a `data.gov.in` IMD key can swap this in. Stored with endpoint, query parameters and fetch time.
- Flood-context layer attached with its vintage stated when available.

Each evidence item is stored with its source, query params and fetch time so it is re-auditable later.

**Verdict** — one of **Eligible**, **Needs Review**, **Rule Not Verified**. Satellite and rainfall data are supporting context, never proof that a specific asset was damaged (out of scope: determining whether a loss actually occurred — that is the sanctioning authority's job).

## 11. WhatsApp as the channel

- **Channel:** WhatsApp Business Platform (Cloud API) — webhook with signature verification; idempotency by `message_id` (Meta retries deliveries).
- **Identity:** phone number only — no app to install, no account, no password. Usually the same number seeded to the citizen's bank account for DBT.
- **Inputs:** voice note, photos, location pin, text; native reply buttons by default, WhatsApp Flow multi-screen review when `WA_FLOW_ID` is registered (F11).
- **Outputs:** review summary (buttons or Flow), TTS voice playback of the same summary (additive), filled government-format PDF as a document, status updates over WhatsApp (utility templates, F17).
- **Media:** fetched on webhook arrival into own object storage, then deleted from Meta. 24-hour session window tracked by the conversation state machine; outbound turns minimised.
- **Review over Flow:** `GET /api/flows/{cid}` answers `ping` / `get_data` / `data_exchange` with HMAC integrity (`FLOW_ENDPOINT_PASSPHRASE`); `confirm` drives the same state machine as the three buttons.

## 12. Trust, safety and data handling

Non-negotiable product rules (from §4):
1. No compensation figure is ever shown without the Government Resolution number, date and page it came from.
2. If no authoritative rule can be retrieved, the system says **"rule not verified"** rather than guessing.
3. Nothing is submitted or finalised without explicit citizen confirmation.
4. The LLM never computes an amount.

Why (4) exists: Stanford RegLab / Yale 2025 found commercial legal RAG tools hallucinate 17–33% of the time, with error types that map directly onto this domain — jurisdiction confusion, temporal misapplication, sycophancy. Structure beats model size on statutory work, so the LLM extracts facts and explains rules in plain language; a deterministic engine computes money.

Additional safeguards:
- Equal-specificity rule ties route to **human review**, never guessing.
- Rules are git-versioned data, not prompt text; retriever proposes clauses, the engine decides.
- Two-person maker-checker sign-off before a rule is published.
- Everything — conversation, photos, citations, final PDF — remains in the citizen's own WhatsApp chat history on their own device.
- No compensation figure without GR citation; no amount computed by the LLM.

## 13. Failure modes and how the product behaves

| Failure | Behaviour |
|---|---|
| ASR cannot transcribe | Ask the citizen to resend or type (`asr_fail`); never invent text. |
| Low-confidence fields | One batched clarification message (max 2 rounds); never a chain of five questions. |
| Still missing after 2 rounds | Escalate to `NEEDS_HUMAN`; an official picks it up. |
| No applicable rule | `RULE_NOT_VERIFIED` — no amount shown, citizen told plainly. |
| Rule tie at equal specificity | `NEEDS_REVIEW`, reason `rule_tie`, routed to a human. |
| Eligibility gate failed | `NEEDS_REVIEW`, reason `gate_failed`, lists the missing gate and how to check it. |
| Percent-of-assessed rule without assessed loss | `NEEDS_REVIEW`; asks for assessed loss. |
| TTS/rainfall down | Additive only — buttons/Flow already delivered; rainfall is supporting context, never blocking. |
| Meta webhook retry | Dedupe by `message_id`; read-receipt failures are cosmetic and ignored. |
| New GR supersedes old rules | Re-evaluate open claims (F15); confirmed claims are **never silently changed** — affected citizens are offered a regenerate, and finalised claims wait for an official to re-file (non-negotiable 3). |
| Devanagari in PDF | ReportLab cannot shape Devanagari conjuncts; PDF is English/Latin only with a bilingual note (known limitation — switch to HTML + shaping renderer for the final government format). |

## 14. Metrics

- Claims created per week; state distribution (INTAKE / CLARIFY / REVIEW / DELIVERED / WATCHING / NEEDS_HUMAN).
- Completion rate: intake → review → confirmed → PDF delivered.
- Clarification rounds used; escalation rate to `NEEDS_HUMAN`.
- Verdict distribution per asset: Eligible / Needs Review / Rule Not Verified.
- Rupee amount computed per claim and in total; most common governing rules.
- PDF delivery rate; TTS playback rate.
- Re-evaluation triggers and amount changes (F15 usage).
- District filing density vs hazard exposure (admin dashboard) — reveals revenue circles hit but producing almost no claims.
- Per-claim event log retained for audit (F13).

## 15. Operating model and deployment

Run locally:
```
pip install -r requirements.txt
cp .env.example .env        # fill in keys
python -m pytest -q
python -m uvicorn app.main:app --port 8000
cloudflared tunnel --url http://localhost:8000   # public HTTPS URL for Meta's webhook
```
Meta dashboard: webhook = `https://<tunnel>/webhook`, verify token = `WA_VERIFY_TOKEN`, subscribe to `messages`. Set `PUBLIC_BASE_URL` to the tunnel URL so PDFs can be handed to WhatsApp.

WhatsApp Flow (F11): upload `app/static/review_flow.json` in the Meta dashboard > WhatsApp > Flows, publish it, set `WA_FLOW_ID`; point the Flow's data endpoint at `https://<tunnel>/api/flows/{claim_id}` with integrity passphrase `FLOW_ENDPOINT_PASSPHRASE`.

GR ingestion: `python -m app.grwatcher scan` (last ~week) or `fetch <18-digit-ref>` (older GRs, found via portal search by hand — captcha is not automated). Then `python -m app.verify_rule sign <rule_id> <name>` twice (two different people), then `POST /api/reeval` to refresh open claims.

Environment variables: `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_APP_SECRET`, `WA_VERIFY_TOKEN`, `WA_GRAPH_VERSION`, `WA_FLOW_ID`, `FLOW_ENDPOINT_PASSPHRASE`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `BHASHINI_USER_ID`, `BHASHINI_API_KEY`, `DATA_GOV_IN_API_KEY`, `PUBLIC_BASE_URL`.

## 16. Roadmap

**v1.0 (locked — Maharashtra):** Oct 2025 state relief package rules for house (full/partial, pucca/kutcha), hut, cattle shed, livestock (milch/draught/sheep-goat/poultry), boat and net; Marathi + Hindi; WhatsApp buttons review; admin queue + district dashboard. Rule corpus currently covers this package (2025-06-01 to 2025-09-30, all-India).

**v1.1:** Base norm GR 27-03-2023 rules; Palghar / Vasai-Virar regional package (July–August 2026) with electoral-roll gate; shop/stall rules under event packages; WhatsApp Flow review screen (F11).

**v1.2:** IMD rainfall via data.gov.in (F8); TTS playback of review summary (F11); SMS / IVR fallback for feature phones (F21); returning-claimant memory / asset registry (F20).

**v2:** Additional states beyond Maharashtra (F22). Crop loss stays out of scope (PMFBY / DigiClaim already cover it).

## 17. Known limitations

- This document (v1.1) completes sections 9–18 which were pending in v1.0.
- PDF layout is English/Latin only; ReportLab cannot shape Devanagari conjuncts.
- No `.env` is committed; a live WhatsApp channel requires `WA_TOKEN`, `WA_PHONE_NUMBER_ID`, `WA_APP_SECRET`, plus Claude and Bhashini keys.
- Rule corpus is partial: only the Oct 2025 package is encoded; the base norm and regional packages named in §2.4 are not yet in `data/rules/`; shop rules are missing.
- ASR sends OGG as-is; an ffmpeg → 16 kHz WAV step may be needed if Bhashini rejects it.
- Single SQLite file, single worker; the GR watcher's listing crawl needs no captcha, but the portal search for older GRs is manual by reference number.
- Bhashini pipeline ID must be confirmed in the MeitY ULCA dashboard before ASR/TTS work live.

## 18. Glossary

- **GR** — Government Resolution, the instrument that sets relief norms and amounts.
- **SDRF / NDRF** — State / National Disaster Response Fund norms (base relief entitlement).
- **Event package** — a state or regional top-up GR for a specific disaster, overriding the base norm for a date window and geography.
- **Supersession** — a newer GR invalidating an older rule within scope; the resolver walks the chain and keeps the narrowest surviving rule.
- **DBT** — Direct Benefit Transfer (relief paid straight to the bank account).
- **Talathi / Tehsildar** — village and taluka revenue officials who receive and sanction claims.
- **CSC** — Common Service Centre (assisted-filing operator).
- **Panchanama** — official on-the-spot damage inspection record required as evidence.
- **ASR / TTS** — automatic speech recognition / text-to-speech.
- **Bhashini / ULCA** — MeitY's Indian-language AI platform powering ASR and TTS.
- **Maker-checker** — two-person sign-off required before a rule is published.
- **LGD** — Local Government Directory (data.gov.in masters for districts/talukas/villages).

---

**STATUS: LOCKED v1.1 · Maharashtra · 05 November 2026**

All eighteen sections are complete. Sections 1–8 were authored 09 September 2026; sections 9–18 are added here to close the document. No further changes to the spec without a new version and a changelog entry. The implementation target for this hackathon is v1.0 plus v1.1 rule-corpus work (base norm + Palghar package + shop rules).
