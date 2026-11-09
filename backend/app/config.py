from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # Which WhatsApp backend to use: "meta" (WhatsApp Cloud API) or "twilio"
    # (Programmable Messaging). agent.py only talks to app.wa, so switching is
    # an env change, not a code change.
    channel: str = Field("meta", validation_alias=AliasChoices("channel", "message_channel"))

    # WhatsApp Cloud API (meta)
    wa_token: str = ""
    wa_phone_number_id: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = ""
    wa_graph_version: str = "v23.0"
    wa_flow_id: str = ""  # registered Flow for the review screen (F11); empty = plain buttons
    flow_endpoint_passphrase: str = ""  # integrity header check for the Flow data endpoint

    # Twilio WhatsApp
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""  # e.g. "whatsapp:+14155238886" (sandbox number)
    twilio_qr_sid: str = ""        # HX.. quick-reply Content template (ids confirm/change/human)
    twilio_validate: bool = True   # reject /webhook/twilio posts whose X-Twilio-Signature doesn't match

    # Claude (anthropic SDK also reads ANTHROPIC_API_KEY itself)
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"

    # Groq (OpenAI-compatible; alternative extraction LLM)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_provider: str = "claude"  # "claude" | "groq"

    # Bhashini (ASR / TTS)
    bhashini_user_id: str = ""
    bhashini_api_key: str = ""

    # data.gov.in (LGD masters, IMD district rainfall)
    data_gov_in_api_key: str = ""

    db_path: Path = ROOT / "data" / "relief.db"
    media_dir: Path = ROOT / "data" / "media"
    public_base_url: str = ""  # e.g. the tunnel URL; used to hand PDFs to WhatsApp


settings = Settings()
