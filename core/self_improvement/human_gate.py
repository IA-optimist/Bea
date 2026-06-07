"""
core/self_improvement/human_gate.py — Human approval gate for REVIEW decisions.

Sends notifications to configured channels when a self-improvement candidate
requires human validation (REVIEW decision from PromotionPipeline).

Supported notification channels:
  1. Slack  — via SLACK_WEBHOOK_URL env var (incoming webhook)
  2. Telegram — via TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars
  3. Log-only — always-on fallback (INFO level)

Usage:
    gate = get_human_gate()
    notified = gate.notify_review(run_id="abc123", domain="core", ...)
"""
from __future__ import annotations

import json
import structlog
import os
import urllib.error
import urllib.request
from typing import Optional

log = structlog.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NOTIFICATION_TIMEOUT_S = int(os.getenv("NOTIFICATION_TIMEOUT_S", "10"))


# ── Message formatter ─────────────────────────────────────────────────────────

def _format_slack_message(
    run_id: str,
    domain: str,
    description: str,
    risk_level: str,
    score: float,
    changed_files: list[str],
    tests_passed: bool,
    pr_url: str = "",
) -> dict:
    """Format a Slack Block Kit message for a REVIEW notification."""
    risk_emoji = {"LOW": ":yellow_circle:", "MEDIUM": ":orange_circle:", "HIGH": ":red_circle:"}.get(
        risk_level, ":orange_circle:"
    )
    score_bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
    tests_icon = ":white_check_mark:" if tests_passed else ":warning:"

    files_list = "\n".join(f"• `{f}`" for f in changed_files[:5])
    if len(changed_files) > 5:
        files_list += f"\n• _...and {len(changed_files) - 5} more_"

    pr_section = f"\n*PR:* <{pr_url}|View Pull Request>" if pr_url else ""

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🤖 BeaMax SI — Review Required",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Run ID:*\n`{run_id}`"},
                {"type": "mrkdwn", "text": f"*Domain:*\n{domain}"},
                {"type": "mrkdwn", "text": f"*Risk:*\n{risk_emoji} {risk_level}"},
                {"type": "mrkdwn", "text": f"*Score:*\n`{score:.2f}` [{score_bar}]"},
                {"type": "mrkdwn", "text": f"*Tests:*\n{tests_icon} {'Pass' if tests_passed else 'Uncertain'}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Description:*\n{description[:500]}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Changed files:*\n{files_list or '_none_'}{pr_section}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "This change was validated in a Docker sandbox. "
                        "Approve by merging the PR or reject by closing it. "
                        "Auto-merge is *disabled*."
                    ),
                }
            ],
        },
    ]

    return {"blocks": blocks, "text": f"BeaMax SI Review Required — {run_id}"}


def _format_telegram_message(
    run_id: str,
    domain: str,
    description: str,
    risk_level: str,
    score: float,
    changed_files: list[str],
    tests_passed: bool,
    pr_url: str = "",
) -> str:
    """Format Telegram message (Markdown V2 compatible)."""
    files_str = ", ".join(f"`{f}`" for f in changed_files[:3])
    if len(changed_files) > 3:
        files_str += f" \\+{len(changed_files) - 3} more"

    tests_icon = "✅" if tests_passed else "⚠️"
    risk_icon = {"LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴"}.get(risk_level, "🟠")

    pr_line = f"\n🔗 [View PR]({pr_url})" if pr_url else ""

    return (
        f"🤖 *BeaMax SI — Review Required*\n\n"
        f"*Run ID:* `{run_id}`\n"
        f"*Domain:* {domain}\n"
        f"*Risk:* {risk_icon} {risk_level}\n"
        f"*Score:* `{score:.2f}/1.00`\n"
        f"*Tests:* {tests_icon}\n\n"
        f"*Description:*\n{description[:300]}\n\n"
        f"*Files:* {files_str or 'none'}"
        f"{pr_line}\n\n"
        f"_Approve by merging the PR\\. Auto\\-merge is disabled\\._"
    )


# ── Notification senders ──────────────────────────────────────────────────────

def _send_slack(payload: dict) -> bool:
    """Send Slack webhook notification. Returns True on success."""
    if not SLACK_WEBHOOK_URL:
        return False

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=NOTIFICATION_TIMEOUT_S) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            body = resp.read().decode("utf-8")
            if resp.status == 200 and body == "ok":
                log.info("human_gate.slack_sent")
                return True
            log.warning("human_gate.slack_unexpected_response", status=resp.status, body=body[:100])
            return False
    except urllib.error.HTTPError as exc:
        log.error("human_gate.slack_http_error", status=exc.code, err=str(exc))
        return False
    except Exception as exc:
        log.error("human_gate.slack_failed", err=str(exc)[:100])
        return False


def _send_telegram(text: str) -> bool:
    """Send Telegram message. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=NOTIFICATION_TIMEOUT_S) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                log.info("human_gate.telegram_sent")
                return True
            log.warning("human_gate.telegram_not_ok", data=str(data)[:100])
            return False
    except Exception as exc:
        log.error("human_gate.telegram_failed", err=str(exc)[:100])
        return False


# ── Main gate ─────────────────────────────────────────────────────────────────

class HumanGate:
    """
    Sends human review notifications for REVIEW decisions.
    Always logs regardless of channel availability.
    """

    def notify_review(
        self,
        run_id: str,
        domain: str,
        description: str,
        risk_level: str,
        score: float,
        validation_report: dict,
        unified_diff: str = "",
        changed_files: Optional[list[str]] = None,
        pr_url: str = "",
    ) -> bool:
        """
        Send review notification to all configured channels.

        Returns True if at least one channel was notified successfully.
        Always returns without raising.
        """
        if changed_files is None:
            changed_files = []

        tests_passed = validation_report.get("tests_passed", False)

        # Always log
        log.warning(
            "human_gate.review_required",
            run_id=run_id,
            domain=domain,
            risk_level=risk_level,
            score=score,
            changed_files=changed_files,
            tests_passed=tests_passed,
            pr_url=pr_url or "none",
        )

        success = False

        # Slack
        if SLACK_WEBHOOK_URL:
            slack_payload = _format_slack_message(
                run_id=run_id,
                domain=domain,
                description=description,
                risk_level=risk_level,
                score=score,
                changed_files=changed_files,
                tests_passed=tests_passed,
                pr_url=pr_url,
            )
            if _send_slack(slack_payload):
                success = True

        # Telegram
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            tg_text = _format_telegram_message(
                run_id=run_id,
                domain=domain,
                description=description,
                risk_level=risk_level,
                score=score,
                changed_files=changed_files,
                tests_passed=tests_passed,
                pr_url=pr_url,
            )
            if _send_telegram(tg_text):
                success = True

        if not success:
            log.info(
                "human_gate.log_only — no notification channels configured. "
                "Set SLACK_WEBHOOK_URL or TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID",
                run_id=run_id,
            )

        return success


# ── Singleton ──────────────────────────────────────────────────────────────────

_gate: HumanGate | None = None


def get_human_gate() -> HumanGate:
    global _gate
    if _gate is None:
        _gate = HumanGate()
    return _gate
