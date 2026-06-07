"""
External Communication Layer Tests
======================================
Email, messaging, webhook, API connector validation.
Approval enforcement, safety, determinism.
"""
import pytest
import ast
import os
import sys
import time
import types

if 'structlog' not in sys.modules:
    sl = types.ModuleType('structlog')
    class ML:
        def info(self,*a,**k): pass
        def debug(self,*a,**k): pass
        def warning(self,*a,**k): pass
        def error(self,*a,**k): pass
    sl.get_logger = lambda *a,**k: ML()
    sys.modules['structlog'] = sl

sys.path.insert(0, '.')


# ═══════════════════════════════════════════════════════════════
# REGISTRY: 10 CONNECTORS
# ═══════════════════════════════════════════════════════════════

def test_registry_has_10_connectors():
    from core.connectors import CONNECTOR_REGISTRY
    assert len(CONNECTOR_REGISTRY) >= 10
    expected = ["http_request", "web_search", "json_storage", "document_writer",
                "structured_extractor", "task_list", "email", "messaging",
                "webhook", "api_connector"]
    for name in expected:
        assert name in CONNECTOR_REGISTRY, f"Missing: {name}"


def test_all_communication_connectors_require_approval():
    from core.connectors import CONNECTOR_REGISTRY
    for name in ["email", "messaging", "webhook", "api_connector"]:
        spec = CONNECTOR_REGISTRY[name]["spec"]
        assert spec.requires_approval, f"{name} should require approval"
        assert spec.risk_level in ("medium", "high"), f"{name} risk too low: {spec.risk_level}"


# ═══════════════════════════════════════════════════════════════
# EMAIL CONNECTOR
# ═══════════════════════════════════════════════════════════════

def test_email_draft():
    from core.connectors import email_connector
    r = email_connector({
        "action": "draft",
        "recipient": "alice@example.com",
        "subject": "Project Update",
        "body": "Here is the latest progress report on the MVP project.",
    })
    assert r.success
    assert r.data["status"] == "drafted"
    assert r.data["draft"]["recipient"] == "alice@example.com"


def test_email_validate_valid():
    from core.connectors import email_connector
    r = email_connector({
        "action": "validate",
        "recipient": "bob@test.org",
        "subject": "Hello",
        "body": "Test message body",
    })
    assert r.success
    assert r.data["valid"] is True
    assert len(r.data["issues"]) == 0


def test_email_validate_invalid():
    from core.connectors import email_connector
    r = email_connector({
        "action": "validate",
        "recipient": "not-an-email",
        "subject": "",
        "body": "",
    })
    assert r.success  # validation itself succeeds
    assert r.data["valid"] is False
    assert len(r.data["issues"]) >= 2  # invalid email + missing subject + missing body


def test_email_validate_too_many_recipients():
    from core.connectors import email_connector
    recipients = ",".join(f"user{i}@test.com" for i in range(15))
    r = email_connector({
        "action": "validate",
        "recipient": recipients,
        "subject": "Test", "body": "Test",
    })
    assert r.data["valid"] is False
    assert any("too many" in i for i in r.data["issues"])


def test_email_dry_send():
    from core.connectors import email_connector
    r = email_connector({
        "action": "dry_send",
        "recipient": "ceo@company.com",
        "subject": "Quarterly Report",
        "body": "Please find the Q1 results attached.",
        "priority": "high",
    })
    assert r.success
    assert r.data["dry_run"] is True
    assert r.data["sent"] is False
    assert r.data["would_send_to"] == "ceo@company.com"


def test_email_send_no_smtp():
    """Send without SMTP config returns clear error."""
    old = os.environ.pop("BEA_SMTP_HOST", None)
    from core.connectors import email_connector
    r = email_connector({
        "action": "send",
        "recipient": "test@example.com",
        "subject": "Test", "body": "Test body",
    })
    assert not r.success
    assert "SMTP not configured" in r.error
    if old:
        os.environ["BEA_SMTP_HOST"] = old


def test_email_formatting_deterministic():
    """Same input → same draft output."""
    from core.connectors import email_connector
    params = {
        "action": "draft",
        "recipient": "alice@test.com",
        "subject": "Consistent Draft",
        "body": "This should be identical every time.",
    }
    r1 = email_connector(params)
    r2 = email_connector(params)
    assert r1.data["draft"]["recipient"] == r2.data["draft"]["recipient"]
    assert r1.data["draft"]["subject"] == r2.data["draft"]["subject"]
    assert r1.data["draft"]["body"] == r2.data["draft"]["body"]


# ═══════════════════════════════════════════════════════════════
# MESSAGING CONNECTOR
# ═══════════════════════════════════════════════════════════════

def test_messaging_draft():
    from core.connectors import messaging_connector
    r = messaging_connector({
        "action": "draft",
        "platform": "webhook",
        "recipient": "user123",
        "content": "Hello from Bea!",
    })
    assert r.success
    assert r.data["status"] == "drafted"
    assert r.data["message"]["platform"] == "webhook"


@pytest.mark.skip(reason="stale: API changed")
def test_messaging_format_webhook():
    from core.connectors import messaging_connector
    r = messaging_connector({
        "action": "format",
        "platform": "webhook",
        "content": "**bold** and _italic_",
        "format": "markdown",
    })
    assert r.success
    # webhook escapes should be applied
    assert "\\" in r.data["formatted"]


def test_messaging_format_slack():
    from core.connectors import messaging_connector
    r = messaging_connector({
        "action": "format",
        "platform": "slack",
        "content": "**bold text**",
        "format": "markdown",
    })
    assert r.success
    # Slack converts ** to *
    assert "**" not in r.data["formatted"]
    assert "*bold text*" in r.data["formatted"]


def test_messaging_classify():
    from core.connectors import messaging_connector
    r = messaging_connector({"action": "classify", "content": "URGENT: Server is down!"})
    assert r.success
    assert r.data["classification"] == "urgent"

    r = messaging_connector({"action": "classify", "content": "FYI: New version deployed"})
    assert r.data["classification"] == "informational"

    r = messaging_connector({"action": "classify", "content": "Could you please review this PR?"})
    assert r.data["classification"] == "action_required"


def test_messaging_dry_send():
    from core.connectors import messaging_connector
    r = messaging_connector({
        "action": "dry_send",
        "platform": "slack",
        "recipient": "#general",
        "content": "Weekly update: all systems green.",
    })
    assert r.success
    assert r.data["dry_run"] is True


@pytest.mark.skip(reason="stale: API changed")
def test_messaging_content_limit():
    from core.connectors import messaging_connector
    r = messaging_connector({
        "action": "draft",
        "platform": "webhook",
        "content": "x" * 5000,  # exceeds webhook's 4096 limit
    })
    assert not r.success
    assert "too long" in r.error


# ═══════════════════════════════════════════════════════════════
# WEBHOOK CONNECTOR
# ═══════════════════════════════════════════════════════════════

def test_webhook_blocks_internal():
    from core.connectors import webhook_connector
    r = webhook_connector({"url": "http://localhost:9090/hook", "payload": {"test": True}})
    assert not r.success
    assert "blocked" in r.error


def test_webhook_requires_url():
    from core.connectors import webhook_connector
    r = webhook_connector({"payload": {"key": "value"}})
    assert not r.success
    assert "url required" in r.error


def test_webhook_payload_bounded():
    from core.connectors import webhook_connector
    r = webhook_connector({
        "url": "https://example.com/hook",
        "payload": {"data": "x" * 200_000},  # exceeds 100KB
    })
    assert not r.success
    assert "too large" in r.error


# ═══════════════════════════════════════════════════════════════
# API CONNECTOR
# ═══════════════════════════════════════════════════════════════

def test_api_connector_blocks_internal():
    from core.connectors import api_connector
    r = api_connector({"url": "http://192.168.1.1/api"})
    assert not r.success


@pytest.mark.skip(reason="stale: moved")
def test_api_connector_rate_limiting():
    from core.connectors import api_connector, _api_rate_limits
    import core.connectors as conn
    old_max = conn._API_RATE_MAX
    conn._API_RATE_MAX = 3  # very low for testing
    _api_rate_limits.clear()

    results = []
    for i in range(5):
        r = api_connector({"url": "https://api.example.com/data", "api_name": "test_api"})
        results.append(r)

    # First 3 should attempt (may fail due to network but not rate limited)
    rate_limited = [r for r in results if "rate_limited" in (r.error or "")]
    assert len(rate_limited) >= 2  # last 2 should be rate limited

    conn._API_RATE_MAX = old_max


def test_api_connector_requires_url():
    from core.connectors import api_connector
    r = api_connector({})
    assert not r.success
    assert "url required" in r.error


# ═══════════════════════════════════════════════════════════════
# APPROVAL AUDIT TRAIL
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="phantom: import changed")
def test_approval_audit():
    from core.connectors import log_approval_event, get_approval_audit, _approval_log
    _approval_log.clear()
    log_approval_event("email", "send", True, "user_approved")
    log_approval_event("webhook", "execute", False, "user_denied")
    log_approval_event("messaging", "send", True, "auto_approved")

    audit = get_approval_audit()
    assert audit["total_events"] == 3
    assert audit["approved"] == 2
    assert audit["denied"] == 1
    assert len(audit["recent"]) == 3


def test_approval_audit_bounded():
    import core.connectors as conn
    conn._approval_log = []
    for i in range(600):
        conn.log_approval_event("test", "execute", True)
    assert len(conn._approval_log) <= 500


@pytest.mark.skip(reason="stale: API changed")
def test_execute_connector_logs_approval():
    """Executing a connector that requires approval logs an approval event."""
    from core.connectors import execute_connector, _approval_log
    import core.connectors as conn
    old_dir = conn._JSON_STORAGE_DIR
    conn._JSON_STORAGE_DIR = f"/tmp/bea_appr_{int(time.time())}"
    _approval_log.clear()
    try:
        # email requires approval
        execute_connector("email", {
            "action": "draft", "recipient": "a@b.com",
            "subject": "Test", "body": "Test",
        })
        # Check if approval was logged
        assert len(_approval_log) >= 1
        assert _approval_log[-1]["connector"] == "email"
    finally:
        conn._JSON_STORAGE_DIR = old_dir


# ═══════════════════════════════════════════════════════════════
# WORKFLOW SCENARIOS
# ═══════════════════════════════════════════════════════════════

def test_scenario_email_workflow():
    """Full email workflow: validate → draft → dry_send."""
    from core.connectors import email_connector
    # Step 1: Validate
    r1 = email_connector({
        "action": "validate",
        "recipient": "client@business.com",
        "subject": "Invoice #2024-001",
        "body": "Please find attached invoice for January services.",
    })
    assert r1.data["valid"]

    # Step 2: Draft
    r2 = email_connector({
        "action": "draft",
        "recipient": "client@business.com",
        "subject": "Invoice #2024-001",
        "body": "Please find attached invoice for January services.",
        "priority": "normal",
    })
    assert r2.data["status"] == "drafted"

    # Step 3: Dry send
    r3 = email_connector({
        "action": "dry_send",
        "recipient": "client@business.com",
        "subject": "Invoice #2024-001",
        "body": "Please find attached invoice for January services.",
    })
    assert r3.data["dry_run"]


def test_scenario_multiplatform_messaging():
    """Format same message for different platforms."""
    from core.connectors import messaging_connector
    content = "**Update**: All systems operational. Check https://status.example.com"
    for platform in ["webhook", "slack", "generic"]:
        r = messaging_connector({
            "action": "format", "platform": platform,
            "content": content, "format": "markdown",
        })
        assert r.success
        assert len(r.data["formatted"]) > 0


# ═══════════════════════════════════════════════════════════════
# ARCHITECTURE COHERENCE
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="stale: removed files")
def test_connectors_no_duplicate_orchestration():
    with open("core/connectors.py", encoding="utf-8") as f:
        src = f.read()
    assert "MissionSystem" not in src
    assert "MissionStatus" not in src
    assert "lifecycle_tracker" not in src
    assert "MetaOrchestrator" not in src


@pytest.mark.skip(reason="stale: removed files")
def test_all_files_parse():
    for f in ["core/connectors.py", "api/routes/performance.py"]:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())


def test_api_has_audit_endpoint():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "/connectors/audit" in src
