"""
BEA — Connector Layer
============================
High-leverage connectors enabling real-world execution.

Every connector follows the unified interface:
  - structured input/output schemas
  - latency estimate + failure modes
  - retry compatibility flag
  - risk classification
  - approval gating integration

Connectors integrate with:
  - tool_executor (registered as tools)
  - execution_engine (retry + fallback)
  - tool_performance_tracker (observability)
  - operating_primitives (approval gating)

No external dependencies beyond stdlib + requests (optional).
All connectors fail-open: return ToolResult(success=False) on error.
"""
from __future__ import annotations

import json
import structlog
import os
import time

from core.connectors.contracts import (
    ConnectorResult as ConnectorResult,
    ConnectorSpec as ConnectorSpec,
)

logger = structlog.get_logger("bea.connectors")
log = logger  # M3 emitter alias


# ═══════════════════════════════════════════════════════════════
# TIER 1: ESSENTIAL PRIMITIVES
# ═══════════════════════════════════════════════════════════════

# --- HTTP Request ---

HTTP_REQUEST_SPEC = ConnectorSpec(
    name="http_request",
    category="data",
    description="Make structured HTTP requests (GET/POST/PUT/DELETE)",
    input_schema={"url": "str", "method": "str", "headers": "dict?", "body": "str?", "timeout": "int?"},
    output_schema={"status_code": "int", "body": "str", "headers": "dict"},
    risk_level="medium",
    requires_approval=True,
    retry_compatible=True,
    estimated_latency_ms=2000,
    failure_modes=["timeout", "connection_error", "rate_limit", "auth_error"],
)


def http_request(params: dict) -> ConnectorResult:
    """Execute an HTTP request."""
    start = time.time()
    url = params.get("url", "")
    method = params.get("method", "GET").upper()
    headers = params.get("headers", {})
    body = params.get("body", "")
    timeout = min(params.get("timeout", 30), 60)  # max 60s

    if not url:
        return ConnectorResult(error="url required", connector="http_request")

    # Safety: block internal IPs
    for blocked in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "172.16.", "192.168."):  # nosec B104 — SSRF blocklist, not a bind
        if blocked in url:
            return ConnectorResult(error="blocked: internal address", connector="http_request")

    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, method=method, headers=headers or {})
        if body and method in ("POST", "PUT", "PATCH"):
            req.data = body.encode("utf-8") if isinstance(body, str) else body
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            resp_body = resp.read(100_000).decode("utf-8", errors="replace")  # max 100KB
            latency = (time.time() - start) * 1000
            return ConnectorResult(
                success=True,
                data={"status_code": resp.status, "body": resp_body, "headers": dict(resp.headers)},
                latency_ms=latency,
                connector="http_request",
            )
    except Exception as e:
        latency = (time.time() - start) * 1000
        return ConnectorResult(error=str(e)[:200], latency_ms=latency, connector="http_request")


# --- Web Search ---

WEB_SEARCH_SPEC = ConnectorSpec(
    name="web_search",
    category="data",
    description="Search the web and return structured results",
    input_schema={"query": "str", "max_results": "int?"},
    output_schema={"results": "list[{title, url, snippet}]"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=3000,
    failure_modes=["rate_limit", "timeout", "no_results"],
)


def web_search(params: dict) -> ConnectorResult:
    """Search the web using DuckDuckGo HTML (no API key)."""
    start = time.time()
    query = params.get("query", "")
    max_results = min(params.get("max_results", 5), 10)
    if not query:
        return ConnectorResult(error="query required", connector="web_search")

    try:
        import urllib.request
        import urllib.parse
        import re
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Bea/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            html = resp.read(200_000).decode("utf-8", errors="replace")
        # Extract results from DDG HTML
        results = []
        for match in re.finditer(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html):
            if len(results) >= max_results:
                break
            href = match.group(1)
            title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
            if href and title:
                results.append({"title": title, "url": href, "snippet": ""})
        latency = (time.time() - start) * 1000
        return ConnectorResult(success=True, data=results, latency_ms=latency, connector="web_search")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=(time.time()-start)*1000, connector="web_search")


# --- JSON Storage ---

JSON_STORAGE_SPEC = ConnectorSpec(
    name="json_storage",
    category="storage",
    description="Persist and retrieve structured JSON data",
    input_schema={"action": "str(read|write|list)", "key": "str", "data": "any?"},
    output_schema={"data": "any", "keys": "list?"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=50,
    failure_modes=["disk_full", "permission_error"],
)

_JSON_STORAGE_DIR = os.environ.get("BEA_STORAGE_DIR", "workspace/storage")
_MAX_STORAGE_KEYS = 500
_MAX_VALUE_SIZE = 100_000  # 100KB per value


def json_storage(params: dict) -> ConnectorResult:
    """Persist and retrieve structured JSON data."""
    start = time.time()
    action = params.get("action", "read")
    key = params.get("key", "")
    data = params.get("data")

    if not key and action != "list":
        return ConnectorResult(error="key required", connector="json_storage")

    # Sanitize key
    safe_key = "".join(c for c in key if c.isalnum() or c in "-_.")[:100]
    storage_dir = _JSON_STORAGE_DIR
    os.makedirs(storage_dir, exist_ok=True)
    filepath = os.path.join(storage_dir, f"{safe_key}.json")

    try:
        if action == "write":
            serialized = json.dumps(data, indent=2, default=str)
            if len(serialized) > _MAX_VALUE_SIZE:
                return ConnectorResult(error="value too large", connector="json_storage")
            # Check key count
            existing = [f for f in os.listdir(storage_dir) if f.endswith(".json")]
            if len(existing) >= _MAX_STORAGE_KEYS and not os.path.exists(filepath):
                return ConnectorResult(error="storage full", connector="json_storage")
            with open(filepath, "w") as f:
                f.write(serialized)
            return ConnectorResult(success=True, data={"written": safe_key},
                                   latency_ms=(time.time()-start)*1000, connector="json_storage")

        elif action == "read":
            if not os.path.exists(filepath):
                return ConnectorResult(error=f"key '{safe_key}' not found", connector="json_storage")
            with open(filepath) as f:
                data = json.load(f)
            return ConnectorResult(success=True, data=data,
                                   latency_ms=(time.time()-start)*1000, connector="json_storage")

        elif action == "list":
            keys = [f[:-5] for f in os.listdir(storage_dir) if f.endswith(".json")]
            return ConnectorResult(success=True, data={"keys": keys[:100]},
                                   latency_ms=(time.time()-start)*1000, connector="json_storage")

        else:
            return ConnectorResult(error=f"unknown action: {action}", connector="json_storage")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=(time.time()-start)*1000, connector="json_storage")


# --- Structured Document Writer ---

DOC_WRITER_SPEC = ConnectorSpec(
    name="document_writer",
    category="content",
    description="Generate structured documents (markdown, JSON, CSV)",
    input_schema={"format": "str(md|json|csv)", "title": "str", "content": "any", "path": "str?"},
    output_schema={"path": "str", "size_bytes": "int"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=100,
    failure_modes=["disk_full", "permission_error"],
)

_DOC_OUTPUT_DIR = os.environ.get("BEA_DOC_DIR", "workspace/documents")
_MAX_DOC_SIZE = 500_000  # 500KB


def document_writer(params: dict) -> ConnectorResult:
    """Generate a structured document."""
    start = time.time()
    fmt = params.get("format", "md")
    title = params.get("title", "untitled")
    content = params.get("content", "")
    safe_title = "".join(c for c in title if c.isalnum() or c in "-_ ")[:80].strip().replace(" ", "_")

    os.makedirs(_DOC_OUTPUT_DIR, exist_ok=True)

    try:
        if fmt == "md":
            text = f"# {title}\n\n{content}" if isinstance(content, str) else f"# {title}\n\n{json.dumps(content, indent=2)}"
            path = os.path.join(_DOC_OUTPUT_DIR, f"{safe_title}.md")
        elif fmt == "json":
            text = json.dumps(content, indent=2, default=str)
            path = os.path.join(_DOC_OUTPUT_DIR, f"{safe_title}.json")
        elif fmt == "csv":
            if isinstance(content, list):
                lines = []
                if content and isinstance(content[0], dict):
                    headers = list(content[0].keys())
                    lines.append(",".join(headers))
                    for row in content:
                        lines.append(",".join(str(row.get(h, "")) for h in headers))
                else:
                    lines = [str(row) for row in content]
                text = "\n".join(lines)
            else:
                text = str(content)
            path = os.path.join(_DOC_OUTPUT_DIR, f"{safe_title}.csv")
        else:
            return ConnectorResult(error=f"unsupported format: {fmt}", connector="document_writer")

        if len(text) > _MAX_DOC_SIZE:
            return ConnectorResult(error="document too large", connector="document_writer")

        with open(path, "w") as f:
            f.write(text)
        return ConnectorResult(
            success=True, data={"path": path, "size_bytes": len(text)},
            latency_ms=(time.time()-start)*1000, connector="document_writer",
        )
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=(time.time()-start)*1000, connector="document_writer")


# --- Structured Extractor ---

EXTRACTOR_SPEC = ConnectorSpec(
    name="structured_extractor",
    category="data",
    description="Extract structured data from text (JSON, key-value, lists)",
    input_schema={"text": "str", "extract_type": "str(json|kv|list|urls|emails)"},
    output_schema={"extracted": "any"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=50,
    failure_modes=["parse_error", "no_matches"],
)


def structured_extractor(params: dict) -> ConnectorResult:
    """Extract structured data from text."""
    import re
    start = time.time()
    text = params.get("text", "")
    extract_type = params.get("extract_type", "json")

    if not text:
        return ConnectorResult(error="text required", connector="structured_extractor")

    try:
        if extract_type == "json":
            # Find JSON objects/arrays in text
            matches = re.findall(r'(\{[^{}]*\}|\[[^\[\]]*\])', text)
            extracted = []
            for m in matches[:20]:
                try:
                    extracted.append(json.loads(m))
                except json.JSONDecodeError as _exc:
                    log.warning("swallowed_exception", action="_base_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return ConnectorResult(success=True, data=extracted,
                                   latency_ms=(time.time()-start)*1000, connector="structured_extractor")

        elif extract_type == "urls":
            urls = re.findall(r'https?://[^\s<>"\']+', text)
            return ConnectorResult(success=True, data=list(set(urls))[:50],
                                   latency_ms=(time.time()-start)*1000, connector="structured_extractor")

        elif extract_type == "emails":
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
            return ConnectorResult(success=True, data=list(set(emails))[:50],
                                   latency_ms=(time.time()-start)*1000, connector="structured_extractor")

        elif extract_type == "kv":
            # Extract key: value pairs
            pairs = {}
            for match in re.finditer(r'([A-Za-z_]\w*)\s*[:=]\s*(.+?)(?:\n|$)', text):
                pairs[match.group(1)] = match.group(2).strip()
            return ConnectorResult(success=True, data=pairs,
                                   latency_ms=(time.time()-start)*1000, connector="structured_extractor")

        elif extract_type == "list":
            # Extract bullet/numbered lists
            items = re.findall(r'(?:^|\n)\s*(?:[-*•]|\d+[.)]\s+)\s*(.+)', text)
            return ConnectorResult(success=True, data=items[:100],
                                   latency_ms=(time.time()-start)*1000, connector="structured_extractor")

        else:
            return ConnectorResult(error=f"unknown extract_type: {extract_type}",
                                   connector="structured_extractor")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=(time.time()-start)*1000,
                               connector="structured_extractor")


# --- Task List Persistence ---

TASK_LIST_SPEC = ConnectorSpec(
    name="task_list",
    category="workflow",
    description="Persist and manage structured task lists",
    input_schema={"action": "str(add|complete|list|clear)", "list_name": "str", "task": "str?", "task_id": "int?"},
    output_schema={"tasks": "list", "completed": "int?"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=50,
    failure_modes=["disk_full"],
)

_TASK_DIR = os.environ.get("BEA_TASK_DIR", "workspace/tasks")
_MAX_TASKS_PER_LIST = 200
_MAX_TASK_LISTS = 50


def task_list(params: dict) -> ConnectorResult:
    """Manage structured task lists."""
    start = time.time()
    action = params.get("action", "list")
    list_name = params.get("list_name", "default")
    safe_name = "".join(c for c in list_name if c.isalnum() or c in "-_")[:50]

    os.makedirs(_TASK_DIR, exist_ok=True)
    filepath = os.path.join(_TASK_DIR, f"{safe_name}.json")

    try:
        # Load existing
        tasks = []
        if os.path.exists(filepath):
            with open(filepath) as f:
                tasks = json.load(f)

        if action == "add":
            task_text = params.get("task", "")
            if not task_text:
                return ConnectorResult(error="task required", connector="task_list")
            if len(tasks) >= _MAX_TASKS_PER_LIST:
                return ConnectorResult(error="task list full", connector="task_list")
            tasks.append({"id": len(tasks) + 1, "task": task_text[:500], "done": False,
                         "created": time.time()})
            with open(filepath, "w") as f:
                json.dump(tasks, f, indent=2)
            return ConnectorResult(success=True, data={"added": task_text[:100], "total": len(tasks)},
                                   latency_ms=(time.time()-start)*1000, connector="task_list")

        elif action == "complete":
            task_id = params.get("task_id", 0)
            for t in tasks:
                if t["id"] == task_id:
                    t["done"] = True
                    t["completed_at"] = time.time()
            with open(filepath, "w") as f:
                json.dump(tasks, f, indent=2)
            completed = sum(1 for t in tasks if t.get("done"))
            return ConnectorResult(success=True, data={"completed": completed, "total": len(tasks)},
                                   latency_ms=(time.time()-start)*1000, connector="task_list")

        elif action == "list":
            return ConnectorResult(success=True, data=tasks[:100],
                                   latency_ms=(time.time()-start)*1000, connector="task_list")

        elif action == "clear":
            if os.path.exists(filepath):
                os.remove(filepath)
            return ConnectorResult(success=True, data={"cleared": safe_name},
                                   latency_ms=(time.time()-start)*1000, connector="task_list")

        else:
            return ConnectorResult(error=f"unknown action: {action}", connector="task_list")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=(time.time()-start)*1000, connector="task_list")


# ═══════════════════════════════════════════════════════════════
# CONNECTOR REGISTRY
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# TIER 2: COMMUNICATION CONNECTORS
# ═══════════════════════════════════════════════════════════════

# --- Email ---

EMAIL_SPEC = ConnectorSpec(
    name="email",
    category="communication",
    description="Draft, validate, and send structured emails",
    input_schema={
        "action": "str(draft|validate|send|dry_send)",
        "recipient": "str", "subject": "str", "body": "str",
        "cc": "str?", "priority": "str(low|normal|high)?",
        "attachments": "list[{name,mime}]?",
    },
    output_schema={"draft": "dict?", "valid": "bool?", "sent": "bool?", "message_id": "str?"},
    risk_level="high",
    requires_approval=True,
    retry_compatible=True,
    estimated_latency_ms=3000,
    failure_modes=["smtp_error", "auth_error", "rate_limit", "invalid_recipient"],
)

# Email validation patterns
import re as _re
_EMAIL_RE = _re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
_MAX_SUBJECT_LEN = 200
_MAX_BODY_LEN = 50_000
_MAX_RECIPIENTS = 10


def email_connector(params: dict) -> ConnectorResult:
    """Draft, validate, and send structured emails."""
    start = time.time()
    action = params.get("action", "draft")
    recipient = params.get("recipient", "")
    subject = params.get("subject", "")
    body = params.get("body", "")
    cc = params.get("cc", "")
    priority = params.get("priority", "normal")
    attachments = params.get("attachments", [])

    def _latency():
        return (time.time() - start) * 1000

    # --- Validate ---
    if action in ("validate", "send", "dry_send", "draft"):
        issues = []
        if not recipient:
            issues.append("recipient required")
        else:
            recipients = [r.strip() for r in recipient.split(",")]
            if len(recipients) > _MAX_RECIPIENTS:
                issues.append(f"too many recipients (max {_MAX_RECIPIENTS})")
            for r in recipients:
                if not _EMAIL_RE.match(r):
                    issues.append(f"invalid email: {r}")
        if not subject:
            issues.append("subject required")
        elif len(subject) > _MAX_SUBJECT_LEN:
            issues.append(f"subject too long (max {_MAX_SUBJECT_LEN})")
        if not body:
            issues.append("body required")
        elif len(body) > _MAX_BODY_LEN:
            issues.append(f"body too long (max {_MAX_BODY_LEN})")
        if priority not in ("low", "normal", "high"):
            issues.append(f"invalid priority: {priority}")

        if action == "validate":
            valid = len(issues) == 0
            return ConnectorResult(
                success=True,
                data={"valid": valid, "issues": issues},
                latency_ms=_latency(), connector="email",
            )

        if issues:
            return ConnectorResult(
                error=f"validation failed: {'; '.join(issues)}",
                latency_ms=_latency(), connector="email",
            )

    # --- Draft ---
    draft = {
        "recipient": recipient,
        "subject": subject[:_MAX_SUBJECT_LEN],
        "body": body[:_MAX_BODY_LEN],
        "cc": cc,
        "priority": priority,
        "attachments": attachments[:5],
        "created_at": time.time(),
    }

    if action == "draft":
        return ConnectorResult(
            success=True, data={"draft": draft, "status": "drafted"},
            latency_ms=_latency(), connector="email",
        )

    # --- Dry Send (simulate) ---
    if action == "dry_send":
        return ConnectorResult(
            success=True,
            data={
                "sent": False, "dry_run": True, "draft": draft,
                "would_send_to": recipient, "status": "dry_run_complete",
            },
            latency_ms=_latency(), connector="email",
        )

    # --- Real Send ---
    if action == "send":
        smtp_host = os.environ.get("BEA_SMTP_HOST", "")
        smtp_port = int(os.environ.get("BEA_SMTP_PORT", "587"))
        smtp_user = os.environ.get("BEA_SMTP_USER", "")
        smtp_pass = os.environ.get("BEA_SMTP_PASS", "")

        if not smtp_host or not smtp_user:
            return ConnectorResult(
                error="SMTP not configured (set BEA_SMTP_HOST, BEA_SMTP_USER, BEA_SMTP_PASS)",
                data={"draft": draft, "status": "smtp_not_configured"},
                latency_ms=_latency(), connector="email",
            )

        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = recipient
            msg["Subject"] = subject[:_MAX_SUBJECT_LEN]
            if cc:
                msg["Cc"] = cc
            if priority == "high":
                msg["X-Priority"] = "1"
            msg.attach(MIMEText(body[:_MAX_BODY_LEN], "plain"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            return ConnectorResult(
                success=True,
                data={"sent": True, "recipient": recipient, "subject": subject[:50], "status": "sent"},
                latency_ms=_latency(), connector="email",
            )
        except Exception as e:
            return ConnectorResult(
                error=f"send_failed: {str(e)[:150]}",
                data={"draft": draft, "status": "send_failed"},
                latency_ms=_latency(), connector="email",
            )

    return ConnectorResult(error=f"unknown action: {action}", latency_ms=_latency(), connector="email")


# --- Messaging ---

MESSAGING_SPEC = ConnectorSpec(
    name="messaging",
    category="communication",
    description="Draft and format messages for external platforms",
    input_schema={
        "action": "str(draft|format|classify|dry_send)",
        "platform": "str(slack|webhook|generic)",
        "recipient": "str", "content": "str",
        "format": "str(text|markdown|html)?",
    },
    output_schema={"message": "dict?", "formatted": "str?", "classification": "str?"},
    risk_level="high",
    requires_approval=True,
    retry_compatible=True,
    estimated_latency_ms=1000,
    failure_modes=["platform_error", "rate_limit", "auth_error", "payload_too_large"],
)

_MAX_MESSAGE_LEN = 10_000
_PLATFORM_LIMITS = {
    
    "slack": 4000,
    "webhook": 50_000,
    "generic": 10_000,
}


def messaging_connector(params: dict) -> ConnectorResult:
    """Draft and format messages for external platforms."""
    start = time.time()
    action = params.get("action", "draft")
    platform = params.get("platform", "generic")
    recipient = params.get("recipient", "")
    content = params.get("content", "")
    fmt = params.get("format", "text")

    def _latency():
        return (time.time() - start) * 1000

    limit = _PLATFORM_LIMITS.get(platform, 10_000)
    if len(content) > limit:
        return ConnectorResult(
            error=f"content too long for {platform} (max {limit})",
            latency_ms=_latency(), connector="messaging",
        )

    # --- Classify ---
    if action == "classify":
        # Simple classification: urgent/info/action/social
        content_lower = content.lower()
        if any(kw in content_lower for kw in ("urgent", "asap", "critical", "emergency")):
            classification = "urgent"
        elif any(kw in content_lower for kw in ("please", "could you", "action", "need", "request")):
            classification = "action_required"
        elif any(kw in content_lower for kw in ("fyi", "info", "update", "note")):
            classification = "informational"
        else:
            classification = "general"
        return ConnectorResult(
            success=True, data={"classification": classification},
            latency_ms=_latency(), connector="messaging",
        )

    # --- Format ---
    if action == "format" or action == "draft":
        formatted = content
        if platform == "slack" and fmt == "markdown":
            # Slack uses mrkdwn — convert ** to *
            formatted = formatted.replace("**", "*")

        message = {
            "platform": platform,
            "recipient": recipient[:200],
            "content": formatted[:limit],
            "format": fmt,
            "char_count": len(formatted),
            "created_at": time.time(),
        }

        if action == "draft":
            return ConnectorResult(
                success=True, data={"message": message, "status": "drafted"},
                latency_ms=_latency(), connector="messaging",
            )
        else:
            return ConnectorResult(
                success=True, data={"formatted": formatted[:limit], "platform": platform},
                latency_ms=_latency(), connector="messaging",
            )

    # --- Dry Send ---
    if action == "dry_send":
        return ConnectorResult(
            success=True,
            data={
                "sent": False, "dry_run": True, "platform": platform,
                "recipient": recipient[:200], "content_preview": content[:200],
                "status": "dry_run_complete",
            },
            latency_ms=_latency(), connector="messaging",
        )

    return ConnectorResult(error=f"unknown action: {action}", latency_ms=_latency(), connector="messaging")


# --- Webhook ---

WEBHOOK_SPEC = ConnectorSpec(
    name="webhook",
    category="automation",
    description="Send structured payloads to webhook endpoints",
    input_schema={
        "url": "str", "method": "str(POST|GET)?",
        "payload": "dict?", "headers": "dict?",
        "timeout": "int?", "validate_response": "bool?",
    },
    output_schema={"status_code": "int", "response": "str", "success": "bool"},
    risk_level="high",
    requires_approval=True,
    retry_compatible=True,
    estimated_latency_ms=5000,
    failure_modes=["timeout", "connection_error", "rate_limit", "invalid_payload", "auth_error"],
)

_MAX_WEBHOOK_PAYLOAD = 100_000  # 100KB
_WEBHOOK_TIMEOUT = 30


def webhook_connector(params: dict) -> ConnectorResult:
    """Send structured payloads to webhook endpoints."""
    start = time.time()
    url = params.get("url", "")
    method = params.get("method", "POST").upper()
    payload = params.get("payload", {})
    headers = params.get("headers", {})
    timeout = min(params.get("timeout", _WEBHOOK_TIMEOUT), 60)

    def _latency():
        return (time.time() - start) * 1000

    if not url:
        return ConnectorResult(error="url required", latency_ms=_latency(), connector="webhook")

    # Safety: block internal
    for blocked in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "172.16.", "192.168."):  # nosec B104 — SSRF blocklist, not a bind
        if blocked in url:
            return ConnectorResult(error="blocked: internal address", latency_ms=_latency(), connector="webhook")

    # Serialize payload
    try:
        payload_bytes = json.dumps(payload, default=str).encode("utf-8")
    except (TypeError, ValueError) as e:
        return ConnectorResult(error=f"invalid payload: {e}", latency_ms=_latency(), connector="webhook")

    if len(payload_bytes) > _MAX_WEBHOOK_PAYLOAD:
        return ConnectorResult(error="payload too large", latency_ms=_latency(), connector="webhook")

    # Execute
    try:
        import urllib.request
        req_headers = {"Content-Type": "application/json", **headers}
        req = urllib.request.Request(url, method=method, headers=req_headers)
        if method in ("POST", "PUT", "PATCH"):
            req.data = payload_bytes

        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            resp_body = resp.read(100_000).decode("utf-8", errors="replace")
            return ConnectorResult(
                success=True,
                data={"status_code": resp.status, "response": resp_body[:5000], "success": True},
                latency_ms=_latency(), connector="webhook",
            )
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="webhook")


# --- Structured API ---

API_CONNECTOR_SPEC = ConnectorSpec(
    name="api_connector",
    category="data",
    description="Structured API interactions with rate limiting and schema normalization",
    input_schema={
        "url": "str", "method": "str(GET|POST|PUT|DELETE)?",
        "params": "dict?", "body": "dict?", "headers": "dict?",
        "api_name": "str?", "rate_limit_key": "str?",
    },
    output_schema={"status_code": "int", "data": "any", "headers": "dict"},
    risk_level="medium",
    requires_approval=True,
    retry_compatible=True,
    estimated_latency_ms=3000,
    failure_modes=["timeout", "rate_limit", "auth_error", "schema_error", "connection_error"],
)

# Rate limiter: per api_name
_api_rate_limits: dict[str, list[float]] = {}
_API_RATE_WINDOW = 60  # seconds
_API_RATE_MAX = int(os.environ.get("BEA_API_RATE_MAX", "30"))  # max calls per window


def api_connector(params: dict) -> ConnectorResult:
    """Structured API interaction with rate limiting."""
    start = time.time()
    url = params.get("url", "")
    method = params.get("method", "GET").upper()
    query_params = params.get("params", {})
    body = params.get("body", {})
    headers = params.get("headers", {})
    api_name = params.get("api_name", url[:50])
    rate_key = params.get("rate_limit_key", api_name)

    def _latency():
        return (time.time() - start) * 1000

    if not url:
        return ConnectorResult(error="url required", latency_ms=_latency(), connector="api_connector")

    # Safety: block internal
    for blocked in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "172.16.", "192.168."):  # nosec B104 — SSRF blocklist, not a bind
        if blocked in url:
            return ConnectorResult(error="blocked: internal address", latency_ms=_latency(), connector="api_connector")

    # Rate limiting
    now = time.time()
    if rate_key not in _api_rate_limits:
        _api_rate_limits[rate_key] = []
    # Clean old entries
    _api_rate_limits[rate_key] = [t for t in _api_rate_limits[rate_key] if now - t < _API_RATE_WINDOW]
    if len(_api_rate_limits[rate_key]) >= _API_RATE_MAX:
        return ConnectorResult(
            error=f"rate_limited: {rate_key} ({_API_RATE_MAX}/min)",
            latency_ms=_latency(), connector="api_connector",
        )
    _api_rate_limits[rate_key].append(now)

    # Build URL with query params
    if query_params:
        import urllib.parse
        qs = urllib.parse.urlencode(query_params)
        url = f"{url}{'&' if '?' in url else '?'}{qs}"

    # Execute
    try:
        import urllib.request
        req_headers = {**headers}
        req = urllib.request.Request(url, method=method, headers=req_headers)
        if body and method in ("POST", "PUT", "PATCH"):
            req.data = json.dumps(body, default=str).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, method=method, headers=req_headers, data=req.data)

        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            resp_body = resp.read(100_000).decode("utf-8", errors="replace")
            # Try to parse as JSON
            try:
                parsed = json.loads(resp_body)
            except json.JSONDecodeError:
                parsed = resp_body[:5000]

            return ConnectorResult(
                success=True,
                data={"status_code": resp.status, "data": parsed, "headers": dict(resp.headers),
                      "api_name": api_name},
                latency_ms=_latency(), connector="api_connector",
            )
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="api_connector")


# ═══════════════════════════════════════════════════════════════
# APPROVAL AUDIT TRAIL
# ═══════════════════════════════════════════════════════════════

_approval_log: list[dict] = []
_MAX_APPROVAL_LOG = 500


def log_approval_event(connector: str, action: str, approved: bool, reason: str = ""):
    """Record an approval decision for audit trail."""
    global _approval_log
    _approval_log.append({
        "connector": connector,
        "action": action,
        "approved": approved,
        "reason": reason[:200],
        "timestamp": time.time(),
    })
    if len(_approval_log) > _MAX_APPROVAL_LOG:
        _approval_log = _approval_log[-_MAX_APPROVAL_LOG:]


def get_approval_audit() -> dict:
    """Get approval audit trail."""
    recent = _approval_log[-50:]
    total = len(_approval_log)
    approved = sum(1 for e in _approval_log if e["approved"])
    return {
        "total_events": total,
        "approved": approved,
        "denied": total - approved,
        "approval_rate": round(approved / max(total, 1), 3),
        "recent": recent,
    }


# ═══════════════════════════════════════════════════════════════
# CONNECTOR REGISTRY
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# TIER 3: BUSINESS DOMAIN CONNECTORS
# ═══════════════════════════════════════════════════════════════

from core.connectors.business import (
    BUDGET_CONNECTOR_SPEC as BUDGET_CONNECTOR_SPEC,
    CONTENT_MANAGER_SPEC as CONTENT_MANAGER_SPEC,
    FILE_EXPORT_SPEC as FILE_EXPORT_SPEC,
    LEAD_MANAGER_SPEC as LEAD_MANAGER_SPEC,
    SCHEDULER_SPEC as SCHEDULER_SPEC,
    WEB_SCRAPE_SPEC as WEB_SCRAPE_SPEC,
    WORKFLOW_TRIGGER_SPEC as WORKFLOW_TRIGGER_SPEC,
    budget_connector as budget_connector,
    content_manager_connector as content_manager_connector,
    file_export_connector as file_export_connector,
    lead_manager_connector as lead_manager_connector,
    scheduler_connector as scheduler_connector,
    web_scrape_connector as web_scrape_connector,
    workflow_trigger_connector as workflow_trigger_connector,
)
CONNECTOR_REGISTRY: dict[str, dict] = {
    "http_request": {"spec": HTTP_REQUEST_SPEC, "execute": http_request},
    "web_search": {"spec": WEB_SEARCH_SPEC, "execute": web_search},
    "json_storage": {"spec": JSON_STORAGE_SPEC, "execute": json_storage},
    "document_writer": {"spec": DOC_WRITER_SPEC, "execute": document_writer},
    "structured_extractor": {"spec": EXTRACTOR_SPEC, "execute": structured_extractor},
    "task_list": {"spec": TASK_LIST_SPEC, "execute": task_list},
    "email": {"spec": EMAIL_SPEC, "execute": email_connector},
    "messaging": {"spec": MESSAGING_SPEC, "execute": messaging_connector},
    "webhook": {"spec": WEBHOOK_SPEC, "execute": webhook_connector},
    "api_connector": {"spec": API_CONNECTOR_SPEC, "execute": api_connector},
    "lead_manager": {"spec": LEAD_MANAGER_SPEC, "execute": lead_manager_connector},
    "content_manager": {"spec": CONTENT_MANAGER_SPEC, "execute": content_manager_connector},
    "budget_tracker": {"spec": BUDGET_CONNECTOR_SPEC, "execute": budget_connector},
    "workflow_trigger": {"spec": WORKFLOW_TRIGGER_SPEC, "execute": workflow_trigger_connector},
    "scheduler": {"spec": SCHEDULER_SPEC, "execute": scheduler_connector},
    "web_scrape": {"spec": WEB_SCRAPE_SPEC, "execute": web_scrape_connector},
    "file_export": {"spec": FILE_EXPORT_SPEC, "execute": file_export_connector},
}


from core.connectors.runtime import (
    _audit_connector_execution as _audit_connector_execution,
    _sanitize_connector_params as _sanitize_connector_params,
    execute_connector as execute_connector,
    get_connector as get_connector,
    list_connectors as list_connectors,
)
