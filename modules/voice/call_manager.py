"""
BEA MAX — CallManager (Phase 10)
Twilio outbound calls, SMS, webhook handler, call status.

Config via env vars:
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_PHONE_NUMBER

If twilio is not installed or credentials are missing, every method
returns a graceful stub dict instead of raising.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_STUB = {"status": "stub", "message": "Twilio not configured"}


def _twilio_client():
    """Return a Twilio REST client or raise ImportError / RuntimeError."""
    try:
        from twilio.rest import Client  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("twilio not installed (pip install twilio)") from exc

    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN",  "")
    if not sid or not token:
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")

    return Client(sid, token)


class CallManager:
    """
    Manages Twilio outbound calls, SMS, webhook parsing and call status queries.
    All public methods are sync (Twilio SDK is sync) and never raise —
    they log a warning and return a stub dict if Twilio is unavailable.
    """

    def __init__(self) -> None:
        self._from = os.getenv("TWILIO_PHONE_NUMBER", "")

    # ── Outbound call ─────────────────────────────────────────

    def initiate_call(
        self,
        to:      str,
        from_:   str = "",
        message: str = "Hello from BeaMax.",
    ) -> dict[str, Any]:
        """
        Make an outbound call using Twilio TTS (<Say> verb).

        Returns:
            {"status": "queued", "call_sid": "CA...", "to": ..., "from": ...}
            or stub dict on failure.
        """
        caller = from_ or self._from
        if not caller:
            log.warning("call_manager_no_from_number")
            return {**_STUB, "message": "TWILIO_PHONE_NUMBER not set"}

        try:
            client = _twilio_client()
            # Build TwiML inline so no public URL is required
            twiml = f"<Response><Say>{_escape_xml(message)}</Say></Response>"
            call = client.calls.create(
                to=to,
                from_=caller,
                twiml=twiml,
            )
            log.info("call_initiated", sid=call.sid, to=to)
            return {
                "status":   call.status,
                "call_sid": call.sid,
                "to":       to,
                "from":     caller,
            }
        except ImportError as exc:
            log.warning("call_manager_twilio_not_installed", err=str(exc))
            return _STUB
        except Exception as exc:
            log.warning("call_manager_initiate_failed", err=str(exc)[:120])
            return {"status": "error", "message": str(exc)}

    # ── SMS ───────────────────────────────────────────────────

    def send_sms(
        self,
        to:    str,
        from_: str = "",
        body:  str = "",
    ) -> dict[str, Any]:
        """
        Send an SMS via Twilio.

        Returns:
            {"status": "sent", "message_sid": "SM...", "to": ..., "from": ...}
        """
        sender = from_ or self._from
        if not sender:
            log.warning("call_manager_no_from_number_sms")
            return {**_STUB, "message": "TWILIO_PHONE_NUMBER not set"}

        try:
            client = _twilio_client()
            msg = client.messages.create(to=to, from_=sender, body=body)
            log.info("sms_sent", sid=msg.sid, to=to)
            return {
                "status":      "sent",
                "message_sid": msg.sid,
                "to":          to,
                "from":        sender,
            }
        except ImportError as exc:
            log.warning("call_manager_twilio_not_installed", err=str(exc))
            return _STUB
        except Exception as exc:
            log.warning("call_manager_sms_failed", err=str(exc)[:120])
            return {"status": "error", "message": str(exc)}

    # ── Webhook handler ───────────────────────────────────────

    def handle_incoming_webhook(self, data: dict) -> str:
        """
        Parse a Twilio webhook payload (POST form data) and return a TwiML response.

        Typical Twilio fields in `data`:
            CallSid, From, To, CallStatus, SpeechResult (if gather)

        Returns a TwiML XML string.
        """
        call_sid     = data.get("CallSid", "unknown")
        caller       = data.get("From", "unknown")
        speech       = data.get("SpeechResult", "")
        call_status  = data.get("CallStatus", "")

        log.info("incoming_webhook",
                 call_sid=call_sid, caller=caller,
                 status=call_status, speech_chars=len(speech))

        if speech:
            reply_text = f"Vous avez dit : {speech}. Merci d'avoir contacté BeaMax."
        else:
            reply_text = "Bonjour, vous avez joint BeaMax. Comment puis-je vous aider ?"

        twiml = (
            "<Response>"
            f"<Say language=\"fr-FR\">{_escape_xml(reply_text)}</Say>"
            "</Response>"
        )
        return twiml

    # ── Call status ───────────────────────────────────────────

    def get_call_status(self, call_sid: str) -> dict[str, Any]:
        """
        Poll the current status of a Twilio call.

        Returns:
            {"call_sid": ..., "status": ..., "duration": ..., "direction": ...}
        """
        try:
            client = _twilio_client()
            call   = client.calls(call_sid).fetch()
            log.info("call_status_fetched", sid=call_sid, status=call.status)
            return {
                "call_sid":  call.sid,
                "status":    call.status,
                "duration":  call.duration,
                "direction": call.direction,
                "to":        call.to,
                "from":      call.from_formatted,
            }
        except ImportError as exc:
            log.warning("call_manager_twilio_not_installed", err=str(exc))
            return _STUB
        except Exception as exc:
            log.warning("call_status_failed", sid=call_sid, err=str(exc)[:120])
            return {"status": "error", "call_sid": call_sid, "message": str(exc)}


# ── helpers ───────────────────────────────────────────────────

def _escape_xml(text: str) -> str:
    """Escape special XML characters for safe embedding in TwiML."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


# ── singleton ─────────────────────────────────────────────────

_instance: CallManager | None = None


def get_call_manager() -> CallManager:
    global _instance
    if _instance is None:
        _instance = CallManager()
    return _instance
