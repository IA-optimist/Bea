"""
JARVIS MAX — Multimodal Voice Module
STT:  OpenAI Whisper API (primary) → HuggingFace Whisper (secondary) → local whisper library (fallback)
TTS:  OpenAI TTS (primary) → HuggingFace MMS-TTS (secondary) → Coqui TTS stub (fallback)
VoiceSession: full STT → LLM → TTS pipeline.

All imports are lazy; works with zero API keys.
"""
from __future__ import annotations

import io
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import structlog

log = structlog.get_logger(__name__)


# ── Result types ──────────────────────────────────────────────

@dataclass
class TranscriptResult:
    text:     str
    language: str    = "fr"
    provider: str    = "stub"
    error:    Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text)


@dataclass
class AudioResult:
    audio_bytes: Optional[bytes] = None
    provider:    str             = "stub"
    format:      str             = "mp3"
    cost_usd:    float           = 0.0
    error:       Optional[str]   = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.audio_bytes)


# ── TTS cost table (USD per 1k chars) ────────────────────────
_TTS_COST_PER_1K = {
    "tts-1":    0.015,
    "tts-1-hd": 0.030,
}

_OPENAI_TTS_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


# ── STT: OpenAI Whisper API ───────────────────────────────────

async def _whisper_api(
    audio: Union[str, bytes, Path],
    language: str,
) -> TranscriptResult:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    import openai as _openai
    client = _openai.AsyncOpenAI(api_key=api_key)

    if isinstance(audio, (str, Path)):
        with open(audio, "rb") as f:
            audio_bytes = f.read()
        filename = Path(audio).name
    else:
        audio_bytes = audio
        filename = "audio.wav"

    try:
        resp = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes),
            language=language,
        )
        log.info("whisper_api_transcribed", chars=len(resp.text))
        return TranscriptResult(text=resp.text, language=language, provider="openai_whisper")
    except Exception as e:
        raise RuntimeError(f"Whisper API failed: {e}") from e


# ── STT: local whisper library ────────────────────────────────

def _whisper_local(
    audio: Union[str, bytes, Path],
    language: str,
) -> TranscriptResult:
    try:
        import whisper  # openai-whisper package
    except ImportError:
        raise RuntimeError("local whisper not installed (pip install openai-whisper)")

    if isinstance(audio, bytes):
        import tempfile, wave
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(audio)
        tmp.flush()
        audio_path = tmp.name
    else:
        audio_path = str(audio)

    try:
        model = whisper.load_model("base")
        result = model.transcribe(audio_path, language=language)
        text = result.get("text", "")
        log.info("whisper_local_transcribed", chars=len(text))
        return TranscriptResult(text=text, language=language, provider="whisper_local")
    except Exception as e:
        raise RuntimeError(f"local whisper failed: {e}") from e


# ── STT: HuggingFace Whisper API ─────────────────────────────

async def _hf_whisper(
    audio: Union[str, bytes, Path],
) -> TranscriptResult:
    """Transcribe audio using HuggingFace Inference API (openai/whisper-large-v3)."""
    try:
        from config.settings import get_settings
        hf_key = getattr(get_settings(), "huggingface_api_key", "") or os.getenv("HUGGINGFACE_API_KEY", "")
    except Exception:
        hf_key = os.getenv("HUGGINGFACE_API_KEY", "")

    if not hf_key:
        raise RuntimeError("HUGGINGFACE_API_KEY not set")

    if isinstance(audio, (str, Path)):
        with open(audio, "rb") as f:
            audio_bytes = f.read()
    else:
        audio_bytes = audio

    hf_url = "https://api-inference.huggingface.co/models/openai/whisper-large-v3"
    log.info("hf_whisper_stt_called", bytes=len(audio_bytes))

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                hf_url,
                headers={"Authorization": f"Bearer {hf_key}"},
                content=audio_bytes,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text", "") if isinstance(data, dict) else str(data)
            log.info("hf_whisper_stt_done", chars=len(text))
            return TranscriptResult(text=text, language="auto", provider="hf_whisper")
    except Exception as e:
        raise RuntimeError(f"HuggingFace Whisper failed: {e}") from e


# ── TTS: HuggingFace MMS-TTS ──────────────────────────────────

async def _hf_tts(text: str) -> str:
    """
    Text-to-speech using HuggingFace Inference API (facebook/mms-tts-fra).
    Saves audio bytes to workspace/audio/{uuid}.flac and returns the path.
    """
    try:
        from config.settings import get_settings
        settings = get_settings()
        hf_key = getattr(settings, "huggingface_api_key", "") or os.getenv("HUGGINGFACE_API_KEY", "")
        workspace = Path(settings.workspace_dir)
    except Exception:
        hf_key = os.getenv("HUGGINGFACE_API_KEY", "")
        workspace = Path("workspace")

    if not hf_key:
        raise RuntimeError("HUGGINGFACE_API_KEY not set")

    hf_url = "https://api-inference.huggingface.co/models/facebook/mms-tts-fra"
    log.info("hf_tts_called", chars=len(text))

    import httpx
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            hf_url,
            headers={"Authorization": f"Bearer {hf_key}"},
            json={"inputs": text},
        )
        resp.raise_for_status()
        audio_bytes = resp.content

    audio_dir = workspace / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"{uuid.uuid4()}.flac"
    audio_path.write_bytes(audio_bytes)

    log.info("hf_tts_saved", path=str(audio_path))
    return str(audio_path)


# ── Public: speech_to_text ────────────────────────────────────

async def speech_to_text(
    audio_path_or_bytes: Union[str, bytes, Path],
    language: str = "fr",
) -> TranscriptResult:
    """
    Transcribe audio to text.
    Tries OpenAI Whisper API first, then local whisper library.
    Never raises — returns error string in result on full failure.
    """
    try:
        return await _whisper_api(audio_path_or_bytes, language)
    except Exception as e:
        log.debug("whisper_api_unavailable", err=str(e)[:80])

    # HuggingFace Whisper as secondary fallback
    try:
        return await _hf_whisper(audio_path_or_bytes)
    except Exception as e:
        log.debug("hf_whisper_unavailable", err=str(e)[:80])

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _whisper_local, audio_path_or_bytes, language
        )
    except Exception as e:
        log.debug("whisper_local_unavailable", err=str(e)[:80])

    return TranscriptResult(
        text="",
        language=language,
        provider="stub",
        error="No STT provider available (set OPENAI_API_KEY, HUGGINGFACE_API_KEY, or install openai-whisper)",
    )


# ── TTS: OpenAI ───────────────────────────────────────────────

async def _openai_tts(text: str, voice: str, model: str) -> AudioResult:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    voice = voice if voice in _OPENAI_TTS_VOICES else "alloy"

    try:
        import openai as _openai
        client = _openai.AsyncOpenAI(api_key=api_key)
        resp = await client.audio.speech.create(
            model=model,
            voice=voice,   # type: ignore[arg-type]
            input=text,
            response_format="mp3",
        )
        audio_bytes = resp.read()
        cost = _TTS_COST_PER_1K.get(model, 0.015) * len(text) / 1000
        log.info("openai_tts_generated", chars=len(text), voice=voice, cost=cost)
        return AudioResult(audio_bytes=audio_bytes, provider="openai_tts", cost_usd=cost)
    except Exception as e:
        raise RuntimeError(f"OpenAI TTS failed: {e}") from e


# ── TTS: Coqui stub ───────────────────────────────────────────

async def _coqui_tts_stub(text: str) -> AudioResult:
    """
    Placeholder for Coqui TTS integration.
    Coqui TTS (tts library) requires heavy model downloads — not auto-installed.
    Returns an error stub. Real impl: `from TTS.api import TTS; tts = TTS(...)`
    """
    log.warning("coqui_tts_stub_used", chars=len(text))
    return AudioResult(
        audio_bytes=None,
        provider="coqui_stub",
        error="Coqui TTS not configured (install: pip install TTS)",
    )


# ── Public: text_to_speech ────────────────────────────────────

async def text_to_speech(
    text:     str,
    voice:    str = "alloy",
    provider: str = "auto",
    model:    str = "tts-1",
) -> AudioResult:
    """
    Convert text to speech audio bytes (MP3).
    provider: "auto" | "openai" | "coqui" | "stub"
    Never raises.
    """
    if provider in ("openai", "auto"):
        try:
            return await _openai_tts(text, voice, model)
        except Exception as e:
            log.debug("openai_tts_unavailable", err=str(e)[:80])
            if provider == "openai":
                return AudioResult(error=str(e), provider="openai_tts")

    # HuggingFace MMS-TTS as secondary fallback
    if provider in ("huggingface", "auto"):
        try:
            audio_path = await _hf_tts(text)
            audio_bytes = Path(audio_path).read_bytes()
            return AudioResult(
                audio_bytes=audio_bytes,
                provider="hf_mms_tts",
                format="flac",
                cost_usd=0.0,
            )
        except Exception as e:
            log.debug("hf_tts_unavailable", err=str(e)[:80])
            if provider == "huggingface":
                return AudioResult(error=str(e), provider="hf_mms_tts")

    if provider in ("coqui", "auto"):
        try:
            return await _coqui_tts_stub(text)
        except Exception as e:
            log.debug("coqui_tts_failed", err=str(e)[:80])

    return AudioResult(
        provider="stub",
        error="No TTS provider available (set OPENAI_API_KEY, HUGGINGFACE_API_KEY, or install TTS)",
    )


# ── VoiceSession ──────────────────────────────────────────────

class VoiceSession:
    """
    Manages a full STT → LLM → TTS pipeline for voice interactions.

    Usage:
        session = VoiceSession(system_prompt="Tu es Jarvis...")
        audio_out = await session.process(audio_bytes)
    """

    def __init__(
        self,
        system_prompt: str = "Tu es Jarvis, un assistant IA. Réponds de façon concise.",
        language:      str = "fr",
        tts_voice:     str = "alloy",
        model:         str = "gpt-4o-mini",
    ) -> None:
        self.system_prompt = system_prompt
        self.language      = language
        self.tts_voice     = tts_voice
        self.model         = model
        self._history:     list[dict] = []

    async def process(
        self,
        audio_input: Union[str, bytes, Path],
    ) -> tuple[str, AudioResult]:
        """
        Full pipeline: audio → transcript → LLM → audio response.
        Returns (transcript_text, AudioResult).
        """
        # 1. STT
        transcript = await speech_to_text(audio_input, language=self.language)
        if not transcript.ok:
            log.warning("voice_session_stt_failed", err=transcript.error)
            tts = await text_to_speech(
                "Désolé, je n'ai pas compris l'audio.", voice=self.tts_voice
            )
            return ("", tts)

        user_text = transcript.text
        log.info("voice_session_stt", text=user_text[:80])

        # 2. LLM
        llm_response = await self._llm(user_text)

        # 3. TTS
        audio_out = await text_to_speech(llm_response, voice=self.tts_voice)
        return (user_text, audio_out)

    async def _llm(self, user_text: str) -> str:
        """Call LLM with conversation history."""
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return "[LLM unavailable: OPENAI_API_KEY not set]"

        self._history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": self.system_prompt}] + self._history

        try:
            import openai as _openai
            client = _openai.AsyncOpenAI(api_key=api_key)
            resp = await client.chat.completions.create(
                model=self.model,
                messages=messages,   # type: ignore[arg-type]
                max_tokens=512,
            )
            reply = resp.choices[0].message.content or ""
            self._history.append({"role": "assistant", "content": reply})
            # Keep history bounded
            if len(self._history) > 20:
                self._history = self._history[-20:]
            return reply
        except Exception as e:
            log.error("voice_session_llm_failed", err=str(e)[:120])
            return f"[Erreur LLM: {e}]"

    def reset(self) -> None:
        """Clear conversation history."""
        self._history.clear()


# ── Capability probe ──────────────────────────────────────────

def voice_capabilities() -> dict:
    _key = os.getenv("OPENAI_API_KEY", "")
    has_openai = bool(_key) and not _key.startswith("sk-or-")  # OpenRouter can't do Whisper/TTS
    has_whisper_local = False
    try:
        import whisper  # noqa: F401
        has_whisper_local = True
    except ImportError:
        _silent_log.debug("suppressed_exception", src='voice.py')
    has_coqui = False
    try:
        import TTS  # noqa: F401
        has_coqui = True
    except ImportError:
        _silent_log.debug("suppressed_exception", src='voice.py')

    return {
        "stt_whisper_api":   has_openai,
        "stt_whisper_local": has_whisper_local,
        "tts_openai":        has_openai,
        "tts_coqui":         has_coqui,
        "voice_session":     has_openai or has_whisper_local,
    }
