"""
BEA MAX — Multimodal API Routes

POST /api/v2/multimodal/image/generate  — generate image from prompt
POST /api/v2/multimodal/image/describe  — describe image (URL or upload)
POST /api/v2/multimodal/voice/stt       — speech-to-text (audio upload)
POST /api/v2/multimodal/voice/tts       — text-to-speech
GET  /api/v2/multimodal/capabilities    — available providers
"""
from __future__ import annotations

import base64
import os
from typing import Optional

import structlog
from fastapi import Depends, APIRouter, Header, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from api._deps import _check_auth

log = structlog.get_logger(__name__)


def _auth(x_bea_token: str | None = Header(None),
          authorization: str | None = Header(None)):
    _check_auth(x_bea_token, authorization)



router = APIRouter(prefix="/api/v2/multimodal", tags=["multimodal"], dependencies=[Depends(_auth)])

_API_TOKEN = os.getenv("BEA_API_TOKEN", "")


# ── Request models ────────────────────────────────────────────

class ImageGenerateRequest(BaseModel):
    prompt:   str = Field(..., min_length=1, max_length=4000)
    size:     str = Field("1024x1024", pattern=r"^\d+x\d+$")
    quality:  str = Field("standard", pattern=r"^(standard|hd)$")
    provider: str = Field("auto")


class ImageDescribeRequest(BaseModel):
    url:      Optional[str] = None
    base64:   Optional[str] = None   # raw base64 string
    question: str           = "Describe this image in detail."


class TTSRequest(BaseModel):
    text:     str = Field(..., min_length=1, max_length=4096)
    voice:    str = Field("alloy")
    provider: str = Field("auto")
    model:    str = Field("tts-1")


# ── Image endpoints ───────────────────────────────────────────

@router.post("/image/generate")
async def image_generate(
    req: ImageGenerateRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Generate an image from a text prompt (DALL-E 3 / HuggingFace / stub)."""
    from modules.multimodal.image import generate_image
    result = await generate_image(
        prompt=req.prompt,
        size=req.size,
        quality=req.quality,
        provider=req.provider,
    )
    return {
        "ok":       result.ok,
        "provider": result.provider,
        "url":      result.url,
        "base64":   result.base64,
        "cost_usd": result.cost_usd,
        "error":    result.error,
    }


@router.post("/image/describe")
async def image_describe(
    req: Optional[ImageDescribeRequest] = None,
    file: Optional[UploadFile]          = File(None),
    x_bea_token: Optional[str]       = Header(None),
):
    """Describe/analyze an image using GPT-4o Vision."""
    from modules.multimodal.image import describe_image

    if file is not None:
        raw    = await file.read()
        b64    = base64.b64encode(raw).decode()
        source = b64
        question = "Describe this image in detail."
    elif req and req.url:
        source   = req.url
        question = req.question
    elif req and req.base64:
        source   = req.base64
        question = req.question
    else:
        raise HTTPException(status_code=422, detail="Provide 'url', 'base64', or file upload.")

    description = await describe_image(source, question=question)
    return {"ok": True, "description": description}


# ── Voice endpoints ───────────────────────────────────────────

@router.post("/voice/stt")
async def voice_stt(
    file:           UploadFile            = File(...),
    language:       str                   = Query("fr"),
    x_bea_token: Optional[str]         = Header(None),
):
    """Speech-to-text transcription (Whisper API / local / stub)."""
    from modules.multimodal.voice import speech_to_text

    audio_bytes = await file.read()
    result      = await speech_to_text(audio_bytes, language=language)

    return {
        "ok":       result.ok,
        "text":     result.text,
        "language": result.language,
        "provider": result.provider,
        "error":    result.error,
    }


@router.post("/voice/tts")
async def voice_tts(
    req:            TTSRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Text-to-speech synthesis. Returns MP3 audio bytes on success."""
    from modules.multimodal.voice import text_to_speech

    result = await text_to_speech(
        text=req.text,
        voice=req.voice,
        provider=req.provider,
        model=req.model,
    )

    if result.ok and result.audio_bytes:
        return Response(
            content=result.audio_bytes,
            media_type="audio/mpeg",
            headers={
                "X-Provider":  result.provider,
                "X-Cost-USD":  str(result.cost_usd),
            },
        )

    # Fallback: return JSON error
    return {
        "ok":       False,
        "provider": result.provider,
        "error":    result.error,
    }


# ── Capabilities endpoint ─────────────────────────────────────

@router.get("/capabilities")
async def capabilities(x_bea_token: Optional[str] = Header(None)):
    """Returns which multimodal providers are currently available."""
    from modules.multimodal.image import image_capabilities
    from modules.multimodal.voice import voice_capabilities
    from modules.multimodal.video import video_capabilities

    return {
        "ok": True,
        "data": {
            "image": image_capabilities(),
            "voice": voice_capabilities(),
            "video": video_capabilities(),
        },
    }
