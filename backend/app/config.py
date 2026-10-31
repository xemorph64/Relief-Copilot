from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # WhatsApp Cloud API
    wa_token: str = ""
    wa_phone_number_id: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = ""
    wa_graph_version: str = "v23.0"

    # Claude (anthropic SDK also reads ANTHROPIC_API_KEY itself)
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"

    # Bhashini (ASR / TTS)
    bhashini_user_id: str = ""
    bhashini_api_key: str = ""

    # data.gov.in (LGD masters, IMD district rainfall)
    data_gov_in_api_key: str = ""

    db_path: Path = ROOT / "data" / "relief.db"
    media_dir: Path = ROOT / "data" / "media"
    public_base_url: str = ""  # e.g. the tunnel URL; used to hand PDFs to WhatsApp


settings = Settings()
