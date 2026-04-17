# ══════════════════════════════════════════════════════
# DEPRECATED — Do not extend this module.
# Replaced by: core.actions.action_model.CanonicalAction.request_approval()
# Kept for backward compatibility only.
# ══════════════════════════════════════════════════════
"""
Approval Queue — file d'approbation humaine centralisée.
Toute action à risque élevé doit être soumise ici avant exécution.
"""
import json
import os
import threading
import uuid
import pathlib
import datetime
import logging
from enum import Enum

logger = logging.getLogger(__name__)

QUEUE_PATH = pathlib.Path("workspace/approval_queue/pending.json")


def _fire_approval_webhook(item: dict) -> None:
    """
    POST the approval item to an outbound webhook URL (fire-and-forget).

    Env vars (first defined wins):
        APPROVAL_WEBHOOK_URL   — dedicated approval webhook
        N8N_WEBHOOK_URL        — n8n automation fallback

    Fires in a daemon thread so it never blocks the main flow.
    Completely fail-open: any error is logged at DEBUG level only.
    """
    webhook_url = (
        os.environ.get("APPROVAL_WEBHOOK_URL", "").strip()
        or os.environ.get("N8N_WEBHOOK_URL", "").strip()
    )
    if not webhook_url:
        return

    payload = {
        "event":      "approval_requested",
        "item_id":    item.get("id"),
        "action":     item.get("action"),
        "risk_level": item.get("risk_level"),
        "reason":     item.get("reason"),
        "source":     item.get("source"),
        "submitted_at": item.get("submitted_at"),
        "approve_url": f"/approval/approve/{item.get('id')}",
        "reject_url":  f"/approval/reject/{item.get('id')}",
    }

    def _send():
        try:
            import urllib.request
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                logger.info(
                    f"[ApprovalQueue] webhook fired → {webhook_url[:40]}… "
                    f"status={resp.status}"
                )
        except Exception as exc:
            logger.debug(f"[ApprovalQueue] webhook failed (non-fatal): {exc}")

    threading.Thread(target=_send, daemon=True, name="approval-webhook").start()


class RiskLevel(str, Enum):
    READ = "read"              # lecture simple — auto-approuvé
    WRITE_LOW = "write_low"    # écriture faible risque — auto-approuvé
    WRITE_HIGH = "write_high"  # écriture sensible — approbation requise
    INFRA = "infra"            # infra/docker — approbation requise
    DELETE = "delete"          # suppression — approbation requise
    DEPLOY = "deploy"          # déploiement — approbation requise


# Niveaux auto-approuvés (pas de blocage humain)
AUTO_APPROVE_LEVELS = {RiskLevel.READ, RiskLevel.WRITE_LOW}


def _load() -> list:
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if QUEUE_PATH.exists():
            return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        return []
    except Exception as e:
        logger.warning(f"[ApprovalQueue] load error: {e}")
        return []


def _save(items: list) -> None:
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = QUEUE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(QUEUE_PATH)
    except Exception as e:
        logger.warning(f"[ApprovalQueue] save error: {e}")


def submit_for_approval(
    action: str,
    risk_level: RiskLevel,
    reason: str,
    expected_impact: str,
    rollback_plan: str,
    source: str = "agent",
    payload: dict = None,
) -> dict:
    """
    Soumet une action pour approbation humaine.

    Returns:
        dict with keys: approved (bool), item_id (str|None), pending (bool), auto (bool)
    """
    try:
        if risk_level in AUTO_APPROVE_LEVELS:
            return {"approved": True, "item_id": None, "pending": False, "auto": True}

        # Deduplication: skip if same action+risk already pending
        existing = _load()
        action_key = action[:120]
        for e in existing:
            if e.get("action", "")[:120] == action_key and e.get("risk_level") == str(risk_level) and e.get("status") == "pending":
                logger.debug(f"[ApprovalQueue] duplicate skipped: {action_key[:60]}")
                return {"approved": False, "item_id": e["id"], "pending": True, "auto": False}

        item = {
            "id": str(uuid.uuid4()),
            "action": action,
            "risk_level": str(risk_level),
            "reason": reason,
            "expected_impact": expected_impact,
            "rollback_plan": rollback_plan,
            "source": source,
            "payload": payload or {},
            "status": "pending",
            "submitted_at": datetime.datetime.utcnow().isoformat(),
            "approved_at": None,
            "approved_by": None,
        }
        items = _load()
        items.append(item)
        _save(items)
        logger.info(f"[ApprovalQueue] submitted {item['id'][:8]}… — {action} ({risk_level})")

        # ── Outbound webhook notification (fail-open) ──────────────────────
        # Set APPROVAL_WEBHOOK_URL (or N8N_WEBHOOK_URL) in environment to receive
        # a POST with the full item payload whenever a new approval is queued.
        # Compatible with n8n, Zapier, Slack webhooks, etc.
        _fire_approval_webhook(item)

        return {"approved": False, "item_id": item["id"], "pending": True, "auto": False}

    except Exception as e:
        logger.warning(f"[ApprovalQueue] submit fail-open: {e}")
        return {"approved": False, "item_id": None, "pending": False, "auto": False, "error": str(e)}


def approve(item_id: str, approved_by: str = "human") -> bool:
    """Approuve un item en attente."""
    try:
        items = _load()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "approved"
                item["approved_at"] = datetime.datetime.utcnow().isoformat()
                item["approved_by"] = approved_by
                _save(items)
                logger.info(f"[ApprovalQueue] approved {item_id[:8]}… by {approved_by}")
                return True
        return False
    except Exception as e:
        logger.warning(f"[ApprovalQueue] approve error: {e}")
        return False


def reject(item_id: str, rejected_by: str = "human") -> bool:
    """Rejette un item en attente."""
    try:
        items = _load()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "rejected"
                item["rejected_at"] = datetime.datetime.utcnow().isoformat()
                item["rejected_by"] = rejected_by
                _save(items)
                return True
        return False
    except Exception as e:
        logger.warning(f"[ApprovalQueue] reject error: {e}")
        return False


def get_pending() -> list:
    """Retourne tous les items en attente."""
    try:
        return [i for i in _load() if i.get("status") == "pending"]
    except Exception:
        return []


def is_approved(item_id: str) -> bool:
    """Vérifie si un item est approuvé."""
    try:
        return any(
            i["id"] == item_id and i.get("status") == "approved"
            for i in _load()
        )
    except Exception:
        return False
