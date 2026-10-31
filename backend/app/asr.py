"""Speech-to-text via Bhashini (MeitY ULCA pipeline API): config call, then compute call."""
import base64

import httpx

from app.config import settings

CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
# MeitY pipeline id commonly used for ASR/NMT/TTS; confirm it in your Bhashini dashboard.
PIPELINE_ID = "64392f96daac500b55c543cd"


class ASRError(RuntimeError):
    pass


async def transcribe(audio: bytes, lang: str = "mr", audio_format: str = "ogg") -> str:
    """lang: ISO-639 code ('mr', 'hi'). WhatsApp voice notes are OGG/Opus.

    ponytail: sends OGG as-is; if a Bhashini service rejects it, add an ffmpeg -> 16 kHz wav step here.
    """
    if not (settings.bhashini_user_id and settings.bhashini_api_key):
        raise ASRError("BHASHINI_USER_ID / BHASHINI_API_KEY not set")
    async with httpx.AsyncClient(timeout=60) as c:
        cfg = (await c.post(CONFIG_URL,
                            headers={"userID": settings.bhashini_user_id, "ulcaApiKey": settings.bhashini_api_key},
                            json={"pipelineTasks": [{"taskType": "asr", "config": {"language": {"sourceLanguage": lang}}}],
                                  "pipelineRequestConfig": {"pipelineId": PIPELINE_ID}})).raise_for_status().json()
        ep = cfg["pipelineInferenceAPIEndPoint"]
        service_id = cfg["pipelineResponseConfig"][0]["config"][0]["serviceId"]
        key = ep["inferenceApiKey"]
        out = (await c.post(ep["callbackUrl"], headers={key["name"]: key["value"]}, json={
            "pipelineTasks": [{"taskType": "asr", "config": {
                "language": {"sourceLanguage": lang}, "serviceId": service_id,
                "audioFormat": audio_format, "samplingRate": 16000,
                "preProcessors": ["vad"], "postProcessors": ["itn"]}}],
            "inputData": {"audio": [{"audioContent": base64.b64encode(audio).decode()}]},
        })).raise_for_status().json()
    try:
        return out["pipelineResponse"][0]["output"][0]["source"].strip()
    except (KeyError, IndexError) as e:
        raise ASRError(f"unexpected Bhashini response: {str(out)[:300]}") from e
