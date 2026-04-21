"""
JARVIS MAX — Voice & Call API Routes (Phase 10)

POST /api/v2/voice/process          — upload audio → pipeline → response audio
POST /api/v2/voice/call             — initiate outbound call via Twilio
POST /api/v2/voice/sms              — send SMS via Twilio
POST /api/v2/voice/webhook          — Twilio webhook handler (no auth, returns TwiML)
GET  /api/v2/voice/call/{call_sid}  — get call status

Auth: X-Jarvis-Token header (same pattern as other routes).
      /webhook is intentionally unauthenticated (Twilio signs requests separately).
"""
from __future__ import annotations

import os
from typing import Optional

import structlog
from fastapi import Depends, APIRouter, File, Header, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from api._deps import _check_auth

log = structlog.get_logger(__name__)


def _auth(x_jarvis_token: str | None = Header(None),
          authorization: str | None = Header(None)):
    _check_auth(x_jarvis_token, authorization)



router = APIRouter(prefix="/api/v2/voice", tags=["voice"], dependencies=[Depends(_auth)])

_API_TOKEN = os.getenv("JARVIS_API_TOKEN", "")


# ── Request models ─────────────────────────────────────────────

class CallRequest(BaseModel):
    to:      str = Field(..., min_length=7,  description="E.164 phone number")
    message: str = Field(..., min_length=1,  max_length=1000)
    from_:   str = Field("",                 alias="from",
                         description="Override caller ID (uses TWILIO_PHONE_NUMBER if empty)")

    model_config = {"populate_by_name": True}


class SMSRequest(BaseModel):
    to:      str = Field(..., min_length=7,  description="E.164 phone number")
    message: str = Field(..., min_length=1,  max_length=1600)
    from_:   str = Field("",                 alias="from",
                         description="Override sender (uses TWILIO_PHONE_NUMBER if empty)")

    model_config = {"populate_by_name": True}


# ── Process audio (full pipeline) ────────────────────────────

@router.post("/process")
async def process_audio(
    file:           UploadFile       = File(...),
    session_id:     str              = Query("", description="Conversation session ID"),
    language:       str              = Query("fr"),
    x_jarvis_token: Optional[str]    = Header(None),
):
    """
    Upload an audio file and run it through the full STT → LLM → TTS pipeline.

    Returns JSON with:
        transcript, response_text, audio_base64 (MP3, base64),
        provider_stt, provider_tts, error.
    """
    from modules.voice.voice_pipeline import VoicePipeline

    audio_bytes = await file.read()
    pipeline    = VoicePipeline(language=language)

    result = await pipeline.process_audio(
        audio_bytes=audio_bytes,
        session_id=session_id,
    )
    return {"ok": True, "data": result}


# ── Outbound call ─────────────────────────────────────────────

@router.post("/call")
async def initiate_call(
    req:            CallRequest,
    x_jarvis_token: Optional[str] = Header(None),
):
    """
    Initiate an outbound call using Twilio TTS.
    Returns call_sid on success, or stub dict if Twilio is not configured.
    """
    from modules.voice.call_manager import get_call_manager

    cm     = get_call_manager()
    result = cm.initiate_call(to=req.to, from_=req.from_, message=req.message)
    return {"ok": True, "data": result}


# ── SMS ───────────────────────────────────────────────────────

@router.post("/sms")
async def send_sms(
    req:            SMSRequest,
    x_jarvis_token: Optional[str] = Header(None),
):
    """Send an SMS message via Twilio."""
    from modules.voice.call_manager import get_call_manager

    cm     = get_call_manager()
    result = cm.send_sms(to=req.to, from_=req.from_, body=req.message)
    return {"ok": True, "data": result}


# ── Twilio webhook (no auth) ──────────────────────────────────

@router.post("/webhook", response_class=PlainTextResponse)
async def twilio_webhook(request: Request):
    """
    Twilio webhook handler — receives incoming calls / SMS events.
    Returns TwiML (XML).  No JWT auth — Twilio request signing should be
    verified in production via X-Twilio-Signature (add middleware as needed).
    """
    try:
        form_data = await request.form()
        data      = dict(form_data)
    except Exception:
        data = {}

    from modules.voice.call_manager import get_call_manager
    cm     = get_call_manager()
    twiml  = cm.handle_incoming_webhook(data)

    return PlainTextResponse(content=twiml, media_type="application/xml")


# ── Call status ───────────────────────────────────────────────

@router.get("/call/{call_sid}")
async def get_call_status(
    call_sid:       str,
    x_jarvis_token: Optional[str] = Header(None),
):
    """Poll the status of an outbound call by call_sid."""
    from modules.voice.call_manager import get_call_manager

    cm     = get_call_manager()
    result = cm.get_call_status(call_sid)
    return {"ok": True, "data": result}
