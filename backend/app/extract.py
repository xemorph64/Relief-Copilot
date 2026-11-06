"""Claude/Groq fill the claim form fields from what the citizen said. It never computes money."""
import json
from typing import Literal, Optional

import anthropic
import httpx
from pydantic import BaseModel

from app.config import settings

AssetClass = Literal[
    "house_full_plain", "house_full_hilly", "house_partial_pucca", "house_partial_kutcha", "hut",
    "cattle_shed", "milch_large", "draught_large", "draught_small", "sheep_goat", "poultry",
    "shop", "stall", "boat_partial", "boat_full", "net_partial", "net_full", "other"]
Hazard = Literal["flood", "heavy_rain", "cloudburst", "cyclone", "landslide", "hailstorm", "lightning",
                 "fire", "earthquake", "cold_wave", "drought", "other"]


class Asset(BaseModel):
    asset_class: AssetClass
    quantity: int
    description: str
    confidence: float
    quote: str  # citizen's own words this came from


class Facts(BaseModel):
    language: Literal["mr", "hi", "en"]
    applicant_name: Optional[str]
    applicant_name_confidence: float
    hazard: Optional[Hazard]
    hazard_confidence: float
    incident_date: Optional[str]  # YYYY-MM-DD
    incident_date_confidence: float
    district: Optional[str]
    taluka: Optional[str]
    village: Optional[str]
    village_confidence: float
    assets: list[Asset]
    amount_citizen_expects: Optional[int]  # logged only, never used
    notes: str


SYSTEM = """You fill the Maharashtra disaster-relief claim form from a citizen's WhatsApp messages \
(voice-note transcripts in Marathi/Hindi/Hinglish, typed text, answers to earlier questions).

Rules:
- Only record what the citizen said or what the context states. Never invent a value: use null and a low confidence.
- Confidence is 0-1: how sure you are this is what the citizen meant.
- Dates: resolve relative dates ("parva", "3 tarkhela") against TODAY; output YYYY-MM-DD.
- Houses: house_full_* when fully destroyed or severely damaged; house_partial_pucca/kutcha when partly damaged \
(at least 15%). Use _hilly only if the citizen says the area is hilly.
- Livestock: milch_large = buffalo/cow giving milk; draught_large = bullock/ox; draught_small = calf, donkey, pony, \
heifer; sheep_goat = sheep, goat, pig; poultry = birds (quantity = number of birds).
- One Asset per kind of loss, with quantity.
- Never compute or state compensation amounts. If the citizen names an amount they expect, put it in \
amount_citizen_expects and nothing else.
- language = the language the citizen writes/speaks in."""


async def extract(messages_text: str, known: dict, today: str) -> Facts:
    if settings.llm_provider == "groq":
        return await groq_extract(messages_text, known, today)
    if settings.anthropic_api_key:
        return await claude_extract(messages_text, known, today)
    raise RuntimeError("no LLM configured: set llm_provider + GROQ_API_KEY or ANTHROPIC_API_KEY")


async def claude_extract(messages_text: str, known: dict, today: str) -> Facts:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
    r = await client.beta.messages.parse(
        model=settings.claude_model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"TODAY: {today}\nAlready known (from GPS / earlier answers): {known}\n\n"
                   f"Citizen messages, oldest first:\n{messages_text}"}],
        output_format=Facts,
    )
    if r.stop_reason == "refusal" or r.parsed_output is None:
        raise RuntimeError(f"extraction failed: stop_reason={r.stop_reason}")
    return r.parsed_output


# --- Groq (OpenAI-compatible chat completions with strict JSON schema) ---

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _strict_schema(schema: dict) -> dict:
    """Groq strict mode: every object needs additionalProperties=false and all keys required."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
            schema["required"] = sorted(schema.get("properties", {}))
        for v in schema.values():
            _strict_schema(v)
    elif isinstance(schema, list):
        for item in schema:
            _strict_schema(item)
    return schema


async def groq_extract(messages_text: str, known: dict, today: str) -> Facts:
    schema = _strict_schema(Facts.model_json_schema())
    payload = {
        "model": settings.groq_model,
        "max_tokens": 4096,
        "response_format": {"type": "json_schema", "json_schema": {"name": "facts", "schema": schema, "strict": True}},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                f"TODAY: {today}\nAlready known (from GPS / earlier answers): {known}\n\n"
                f"Citizen messages, oldest first:\n{messages_text}"},
        ],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(GROQ_URL, json=payload,
                              headers={"Authorization": f"Bearer {settings.groq_api_key}"})
        r.raise_for_status()
        return Facts.model_validate(json.loads(r.json()["choices"][0]["message"]["content"]))
