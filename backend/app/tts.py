"""Text-to-speech via Bhashini (same ULCA pipeline as asr.py): for citizens who can't read
the review summary, the same text is played back as a voice note in their language.
"""
import base64

import httpx

from app.config import settings

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
PIPELINE_ID = "64392f96daac500b55c543cd"  # keep in step with asr.py


class TTSError(RuntimeError):
    pass


async def synthesize(text: str, lang: str = "mr") -> bytes:
    """Return audio bytes (wav) speaking `text`. lang: 'mr' | 'hi' | 'en'."""
    if not (settings.bhashini_user_id and settings.bhashini_api_key):
        raise TTSError("BHASHINI_USER_ID / BHASHINI_API_KEY not set")
    async with httpx.AsyncClient(timeout=60) as c:
        cfg = (await c.post(CONFIG_URL,
                            headers={"userID": settings.bhashini_user_id, "ulcaApiKey": settings.bhashini_api_key},
                            json={"pipelineTasks": [{"taskType": "tts", "config": {"language": {"sourceLanguage": lang}}}],
                                  "pipelineRequestConfig": {"pipelineId": PIPELINE_ID}})).raise_for_status().json()
        ep = cfg["pipelineInferenceAPIEndPoint"]
        service_id = cfg["pipelineResponseConfig"][0]["config"][0]["serviceId"]
        key = ep["inferenceApiKey"]
        out = (await c.post(ep["callbackUrl"], headers={key["name"]: key["value"]}, json={
            "pipelineTasks": [{"taskType": "tts", "config": {
                "language": {"sourceLanguage": lang}, "serviceId": service_id}}],
            "inputData": {"input": [{"source": text}]},
        })).raise_for_status().json()
    try:
        return base64.b64decode(out["pipelineResponse"][0]["audio"][0]["audioContent"])
    except (KeyError, IndexError) as e:
        raise TTSError(f"unexpected Bhashini TTS response: {str(out)[:300]}") from e
