"""
BEA MAX — VoicePipeline (Phase 10)
Full STT → LLM → TTS pipeline with per-session history.

Uses:
    modules/multimodal/voice.py  — speech_to_text(), text_to_speech()
    core/agent_comm.py           — AgentComm bus for transcript routing
"""
from __future__ import annotations

import base64
import os
import uuid
from collections import deque
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Per-session history: deque of {"role": "user"|"assistant", "content": str}
_HISTORY_MAXLEN = 50
_sessions: dict[str, deque] = {}


class VoicePipeline:
    """
    High-level voice pipeline: audio bytes → transcript → LLM → audio response.

    Each call to process_audio() runs the full pipeline and returns:
        {
            "transcript":    str,
            "response_text": str,
            "audio_base64":  str | None,   # MP3, base64-encoded
            "provider_stt":  str,
            "provider_tts":  str,
            "error":         str | None,
        }
    """

    def __init__(
        self,
        language:  str = "fr",
        tts_voice: str = "alloy",
        model:     str = "gpt-4o-mini",
    ) -> None:
        self.language  = language
        self.tts_voice = tts_voice
        self.model     = model

    # ── Full pipeline ─────────────────────────────────────────

    async def process_audio(
        self,
        audio_bytes: bytes,
        session_id:  str = "",
    ) -> dict[str, Any]:
        """
        Process raw audio bytes through STT → LLM → TTS.

        Args:
            audio_bytes: Raw audio (WAV, MP3, OGG, …).
            session_id:  Conversation session identifier.
                         Auto-generated if empty.

        Returns:
            dict with keys: transcript, response_text, audio_base64,
                            provider_stt, provider_tts, error.
        """
        sid = session_id or str(uuid.uuid4())

        # 1. STT ─────────────────────────────────────────────
        from modules.multimodal.voice import speech_to_text, text_to_speech

        stt_result = await speech_to_text(audio_bytes, language=self.language)
        if not stt_result.ok:
            log.warning("voice_pipeline_stt_failed", session=sid, err=stt_result.error)
            fallback_text = "Désolé, la transcription a échoué."
            tts_result    = await text_to_speech(fallback_text, voice=self.tts_voice)
            return {
                "transcript":    "",
                "response_text": fallback_text,
                "audio_base64":  _to_b64(tts_result.audio_bytes),
                "provider_stt":  stt_result.provider,
                "provider_tts":  tts_result.provider,
                "error":         stt_result.error,
            }

        transcript = stt_result.text
        log.info("voice_pipeline_stt_ok", session=sid, chars=len(transcript))

        # 2. Publish to AgentComm bus ─────────────────────────
        try:
            from core.agent_comm import get_agent_comm
            bus = get_agent_comm()
            await bus.publish(
                session_id  = sid,
                agent_name  = "voice-pipeline",
                output_type = "transcript",
                payload     = {"text": transcript, "language": self.language},
            )
        except Exception as exc:
            log.debug("voice_pipeline_bus_error", err=str(exc)[:80])

        # 3. LLM ─────────────────────────────────────────────
        history   = _get_history(sid)
        llm_reply = await _call_llm(transcript, history, self.model)
        _update_history(sid, transcript, llm_reply)

        log.info("voice_pipeline_llm_ok", session=sid, reply_chars=len(llm_reply))

        # 4. TTS ─────────────────────────────────────────────
        tts_result = await text_to_speech(llm_reply, voice=self.tts_voice)

        return {
            "transcript":    transcript,
            "response_text": llm_reply,
            "audio_base64":  _to_b64(tts_result.audio_bytes),
            "provider_stt":  stt_result.provider,
            "provider_tts":  tts_result.provider,
            "error":         tts_result.error if not tts_result.ok else None,
        }

    # ── Real-time session stub ────────────────────────────────

    def start_realtime_session(self, session_id: str = "") -> str:
        """
        Return a WebSocket URL for streaming voice interaction.

        NOTE: Full duplex WebSocket streaming requires an additional
        WS endpoint (api/ws.py).  This method returns the expected URL
        pattern; wire up the WS handler separately when needed.
        """
        sid = session_id or str(uuid.uuid4())
        _get_history(sid)   # initialise session bucket
        ws_base = os.getenv("BEA_WS_BASE_URL", "ws://localhost:8000")
        url     = f"{ws_base}/api/v2/voice/ws/{sid}"
        log.info("voice_pipeline_realtime_session_url", session=sid, url=url)
        return url


# ── Internal helpers ──────────────────────────────────────────

def _get_history(session_id: str) -> deque:
    if session_id not in _sessions:
        _sessions[session_id] = deque(maxlen=_HISTORY_MAXLEN)
    return _sessions[session_id]


def _update_history(session_id: str, user_text: str, assistant_text: str) -> None:
    h = _get_history(session_id)
    h.append({"role": "user",      "content": user_text})
    h.append({"role": "assistant", "content": assistant_text})


async def _call_llm(user_text: str, history: deque, model: str) -> str:
    """Call OpenAI chat completion with conversation history."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return "[LLM unavailable: OPENAI_API_KEY not set]"

    system_prompt = (
        "Tu es BeaMax, un assistant IA avancé. "
        "Réponds de façon concise et utile."
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages += list(history)
    messages.append({"role": "user", "content": user_text})

    try:
        import openai as _openai
        client = _openai.AsyncOpenAI(api_key=api_key)
        resp   = await client.chat.completions.create(
            model      = model,
            messages   = messages,   # type: ignore[arg-type]
            max_tokens = 512,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        log.error("voice_pipeline_llm_error", err=str(exc)[:120])
        return f"[Erreur LLM: {exc}]"


def _to_b64(audio_bytes: bytes | None) -> str | None:
    if not audio_bytes:
        return None
    return base64.b64encode(audio_bytes).decode()
