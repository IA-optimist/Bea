"""Business, workflow, scrape, and export connector implementations."""
from __future__ import annotations

import json
import os
import time

from core.connectors.contracts import ConnectorResult, ConnectorSpec

LEAD_MANAGER_SPEC = ConnectorSpec(
    name="lead_manager",
    category="workflow",
    description="Manage business leads through the pipeline",
    input_schema={
        "action": "str(add|advance|update|list|summary)",
        "name": "str?", "lead_id": "str?", "stage": "str?",
        "value_estimate": "float?", "source": "str?", "tags": "list?",
    },
    output_schema={"lead": "dict?", "leads": "list?", "summary": "dict?"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=50,
    failure_modes=["not_found", "limit_reached", "invalid_stage"],
)


def lead_manager_connector(params: dict) -> ConnectorResult:
    """Manage leads through the business pipeline."""
    start = time.time()
    action = params.get("action", "list")

    def _latency():
        return (time.time() - start) * 1000

    try:
        from core.business_pipeline import get_lead_tracker
        lt = get_lead_tracker()

        if action == "add":
            lead = lt.add_lead(
                name=params.get("name", ""),
                source=params.get("source", ""),
                value_estimate=params.get("value_estimate", 0),
                tags=params.get("tags", []),
                contact_info=params.get("contact_info", {}),
                notes=params.get("notes", ""),
                objective_id=params.get("objective_id", ""),
            )
            return ConnectorResult(success=True, data=lead.to_dict(),
                                   latency_ms=_latency(), connector="lead_manager")

        elif action == "advance":
            lead = lt.advance_lead(params.get("lead_id", ""), params.get("stage", ""),
                                   params.get("note", ""))
            if lead:
                return ConnectorResult(success=True, data=lead.to_dict(),
                                       latency_ms=_latency(), connector="lead_manager")
            return ConnectorResult(error="lead not found or invalid stage",
                                   latency_ms=_latency(), connector="lead_manager")

        elif action == "update":
            kwargs = {k: v for k, v in params.items() if k not in ("action", "lead_id")}
            lead = lt.update_lead(params.get("lead_id", ""), **kwargs)
            if lead:
                return ConnectorResult(success=True, data=lead.to_dict(),
                                       latency_ms=_latency(), connector="lead_manager")
            return ConnectorResult(error="lead not found",
                                   latency_ms=_latency(), connector="lead_manager")

        elif action == "list":
            leads = lt.list_leads(stage=params.get("stage", ""), tag=params.get("tag", ""))
            return ConnectorResult(success=True, data=leads,
                                   latency_ms=_latency(), connector="lead_manager")

        elif action == "summary":
            return ConnectorResult(success=True, data=lt.get_pipeline_summary(),
                                   latency_ms=_latency(), connector="lead_manager")

        return ConnectorResult(error=f"unknown action: {action}",
                               latency_ms=_latency(), connector="lead_manager")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="lead_manager")


CONTENT_MANAGER_SPEC = ConnectorSpec(
    name="content_manager",
    category="content",
    description="Manage content items through the creation pipeline",
    input_schema={
        "action": "str(create|advance|update_body|list|summary)",
        "title": "str?", "content_id": "str?", "stage": "str?",
        "body": "str?", "content_type": "str?",
    },
    output_schema={"item": "dict?", "items": "list?", "summary": "dict?"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=50,
    failure_modes=["not_found", "limit_reached", "invalid_stage"],
)


def content_manager_connector(params: dict) -> ConnectorResult:
    """Manage content through the creation pipeline."""
    start = time.time()
    action = params.get("action", "list")

    def _latency():
        return (time.time() - start) * 1000

    try:
        from core.business_pipeline import get_content_pipeline
        cp = get_content_pipeline()

        if action == "create":
            item = cp.create(
                title=params.get("title", ""),
                content_type=params.get("content_type", "article"),
                body=params.get("body", ""),
                tags=params.get("tags", []),
                lead_id=params.get("lead_id", ""),
                objective_id=params.get("objective_id", ""),
            )
            return ConnectorResult(success=True, data=item.to_dict(),
                                   latency_ms=_latency(), connector="content_manager")

        elif action == "advance":
            item = cp.advance(params.get("content_id", ""), params.get("stage", ""))
            if item:
                return ConnectorResult(success=True, data=item.to_dict(),
                                       latency_ms=_latency(), connector="content_manager")
            return ConnectorResult(error="not found or invalid stage",
                                   latency_ms=_latency(), connector="content_manager")

        elif action == "update_body":
            item = cp.update_body(params.get("content_id", ""), params.get("body", ""))
            if item:
                return ConnectorResult(success=True, data=item.to_dict(),
                                       latency_ms=_latency(), connector="content_manager")
            return ConnectorResult(error="not found",
                                   latency_ms=_latency(), connector="content_manager")

        elif action == "list":
            items = cp.list_items(stage=params.get("stage", ""),
                                  content_type=params.get("content_type", ""))
            return ConnectorResult(success=True, data=items,
                                   latency_ms=_latency(), connector="content_manager")

        elif action == "summary":
            return ConnectorResult(success=True, data=cp.get_summary(),
                                   latency_ms=_latency(), connector="content_manager")

        return ConnectorResult(error=f"unknown action: {action}",
                               latency_ms=_latency(), connector="content_manager")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="content_manager")


BUDGET_CONNECTOR_SPEC = ConnectorSpec(
    name="budget_tracker",
    category="workflow",
    description="Track costs and revenue",
    input_schema={
        "action": "str(record|summary|list)",
        "category": "str?", "amount": "float?", "description": "str?",
        "objective_id": "str?", "days": "int?",
    },
    output_schema={"entry": "dict?", "summary": "dict?", "entries": "list?"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=50,
    failure_modes=["limit_reached"],
)


def budget_connector(params: dict) -> ConnectorResult:
    """Track costs and revenue."""
    start = time.time()
    action = params.get("action", "summary")

    def _latency():
        return (time.time() - start) * 1000

    try:
        from core.business_pipeline import get_budget_tracker
        bt = get_budget_tracker()

        if action == "record":
            entry = bt.record(
                category=params.get("category", ""),
                amount=params.get("amount", 0),
                description=params.get("description", ""),
                objective_id=params.get("objective_id", ""),
                lead_id=params.get("lead_id", ""),
                mission_id=params.get("mission_id", ""),
                tags=params.get("tags", []),
            )
            return ConnectorResult(success=True, data=entry.to_dict(),
                                   latency_ms=_latency(), connector="budget_tracker")

        elif action == "summary":
            return ConnectorResult(
                success=True,
                data=bt.get_summary(
                    objective_id=params.get("objective_id", ""),
                    days=params.get("days", 30),
                ),
                latency_ms=_latency(), connector="budget_tracker",
            )

        elif action == "list":
            return ConnectorResult(success=True, data=bt.list_entries(params.get("limit", 50)),
                                   latency_ms=_latency(), connector="budget_tracker")

        return ConnectorResult(error=f"unknown action: {action}",
                               latency_ms=_latency(), connector="budget_tracker")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="budget_tracker")


# ═══════════════════════════════════════════════════════════════
# TIER 4: WORKFLOW OPERATIONS CONNECTORS
# ═══════════════════════════════════════════════════════════════

# --- Workflow Trigger ---

WORKFLOW_TRIGGER_SPEC = ConnectorSpec(
    name="workflow_trigger",
    category="automation",
    description="Create and trigger workflows from the workflow runtime",
    input_schema={
        "action": "str(create|run|pause|resume|cancel|status|list)",
        "name": "str?", "execution_id": "str?",
        "steps": "list?",
    },
    output_schema={"execution": "dict?", "result": "dict?"},
    risk_level="medium",
    requires_approval=True,
    retry_compatible=True,
    estimated_latency_ms=500,
    failure_modes=["limit_reached", "not_found", "workflow_failed"],
)


def workflow_trigger_connector(params: dict) -> ConnectorResult:
    """Create and trigger workflows."""
    start = time.time()
    action = params.get("action", "list")

    def _latency():
        return (time.time() - start) * 1000

    try:
        from core.workflow_runtime import get_workflow_engine
        engine = get_workflow_engine()

        if action == "create":
            wf = engine.create_workflow(
                name=params.get("name", "unnamed"),
                steps=params.get("steps", []),
                version=params.get("version", 1),
                metadata=params.get("metadata", {}),
            )
            return ConnectorResult(success=True, data=wf.to_dict(),
                                   latency_ms=_latency(), connector="workflow_trigger")

        elif action == "run":
            result = engine.run_all(params.get("execution_id", ""))
            return ConnectorResult(success=True, data=result,
                                   latency_ms=_latency(), connector="workflow_trigger")

        elif action == "pause":
            ok = engine.pause(params.get("execution_id", ""))
            return ConnectorResult(success=ok, data={"paused": ok},
                                   latency_ms=_latency(), connector="workflow_trigger")

        elif action == "resume":
            ok = engine.resume(params.get("execution_id", ""))
            return ConnectorResult(success=ok, data={"resumed": ok},
                                   latency_ms=_latency(), connector="workflow_trigger")

        elif action == "cancel":
            ok = engine.cancel(params.get("execution_id", ""))
            return ConnectorResult(success=ok, data={"cancelled": ok},
                                   latency_ms=_latency(), connector="workflow_trigger")

        elif action == "status":
            ex = engine.get_execution(params.get("execution_id", ""))
            if ex:
                return ConnectorResult(success=True, data=ex,
                                       latency_ms=_latency(), connector="workflow_trigger")
            return ConnectorResult(error="not found",
                                   latency_ms=_latency(), connector="workflow_trigger")

        elif action == "list":
            return ConnectorResult(
                success=True,
                data=engine.list_executions(params.get("status", "")),
                latency_ms=_latency(), connector="workflow_trigger",
            )

        return ConnectorResult(error=f"unknown action: {action}",
                               latency_ms=_latency(), connector="workflow_trigger")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="workflow_trigger")


# --- Scheduler ---

SCHEDULER_SPEC = ConnectorSpec(
    name="scheduler",
    category="automation",
    description="Schedule and manage recurring tasks",
    input_schema={
        "action": "str(schedule|unschedule|pause|resume|list|due|trigger)",
        "name": "str?", "task_id": "str?",
        "schedule_type": "str(interval|fixed_time|manual)?",
        "interval_s": "int?", "fixed_time": "str?",
    },
    output_schema={"task": "dict?", "tasks": "list?"},
    risk_level="medium",
    requires_approval=True,
    retry_compatible=True,
    estimated_latency_ms=100,
    failure_modes=["limit_reached", "not_found"],
)


def scheduler_connector(params: dict) -> ConnectorResult:
    """Schedule and manage recurring tasks."""
    start = time.time()
    action = params.get("action", "list")

    def _latency():
        return (time.time() - start) * 1000

    try:
        from core.workflow_runtime import get_scheduler, ScheduledTask
        mgr = get_scheduler()

        if action == "schedule":
            task = mgr.schedule(ScheduledTask(
                name=params.get("name", "unnamed"),
                schedule_type=params.get("schedule_type", "interval"),
                interval_s=params.get("interval_s", 3600),
                fixed_time=params.get("fixed_time", ""),
                action=params.get("task_action", ""),
                workflow_id=params.get("workflow_id", ""),
                params=params.get("task_params", {}),
            ))
            return ConnectorResult(success=True, data=task.to_dict(),
                                   latency_ms=_latency(), connector="scheduler")

        elif action == "unschedule":
            ok = mgr.unschedule(params.get("task_id", ""))
            return ConnectorResult(success=ok, data={"removed": ok},
                                   latency_ms=_latency(), connector="scheduler")

        elif action == "pause":
            ok = mgr.pause(params.get("task_id", ""))
            return ConnectorResult(success=ok, data={"paused": ok},
                                   latency_ms=_latency(), connector="scheduler")

        elif action == "resume":
            ok = mgr.resume(params.get("task_id", ""))
            return ConnectorResult(success=ok, data={"resumed": ok},
                                   latency_ms=_latency(), connector="scheduler")

        elif action == "list":
            return ConnectorResult(success=True, data=mgr.list_tasks(),
                                   latency_ms=_latency(), connector="scheduler")

        elif action == "due":
            due = mgr.get_due_tasks()
            return ConnectorResult(success=True, data=[t.to_dict() for t in due],
                                   latency_ms=_latency(), connector="scheduler")

        elif action == "trigger":
            task = mgr.trigger_manual(params.get("task_id", ""))
            if task:
                return ConnectorResult(success=True, data=task.to_dict(),
                                       latency_ms=_latency(), connector="scheduler")
            return ConnectorResult(error="not found or disabled",
                                   latency_ms=_latency(), connector="scheduler")

        return ConnectorResult(error=f"unknown action: {action}",
                               latency_ms=_latency(), connector="scheduler")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="scheduler")


# --- Web Scrape (stdlib) ---

WEB_SCRAPE_SPEC = ConnectorSpec(
    name="web_scrape",
    category="data",
    description="Fetch and extract structured data from web pages (stdlib only)",
    input_schema={
        "url": "str", "extract": "str(text|links|meta|all)?",
        "max_size": "int?",
    },
    output_schema={"content": "str?", "links": "list?", "meta": "dict?"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=5000,
    failure_modes=["timeout", "connection_error", "blocked", "size_exceeded"],
)

_SCRAPE_MAX_SIZE = 200_000  # 200KB
_SCRAPE_TIMEOUT = 15


def web_scrape_connector(params: dict) -> ConnectorResult:
    """Fetch and extract structured data from a web page."""
    start = time.time()
    url = params.get("url", "")
    extract = params.get("extract", "text")
    max_size = min(params.get("max_size", _SCRAPE_MAX_SIZE), _SCRAPE_MAX_SIZE)

    def _latency():
        return (time.time() - start) * 1000

    if not url:
        return ConnectorResult(error="url required", latency_ms=_latency(), connector="web_scrape")

    # Safety: block internal
    for blocked in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "172.16.", "192.168."):  # nosec B104 — SSRF blocklist, not a bind
        if blocked in url:
            return ConnectorResult(error="blocked: internal address",
                                   latency_ms=_latency(), connector="web_scrape")

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "JarvisMax/1.0 (research bot)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        })
        with urllib.request.urlopen(req, timeout=_SCRAPE_TIMEOUT) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            raw = resp.read(max_size).decode("utf-8", errors="replace")

        result = {}

        if extract in ("text", "all"):
            # Strip HTML tags for text
            import re
            text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            result["content"] = text[:50_000]

        if extract in ("links", "all"):
            import re
            links = re.findall(r'href=["\']([^"\']+)["\']', raw)
            # Deduplicate and limit
            seen = set()
            unique_links = []
            for link in links:
                if link not in seen and link.startswith("http"):
                    seen.add(link)
                    unique_links.append(link)
            result["links"] = unique_links[:100]

        if extract in ("meta", "all"):
            import re
            title_match = re.search(r'<title[^>]*>(.*?)</title>', raw, re.IGNORECASE | re.DOTALL)
            desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', raw, re.IGNORECASE)
            result["meta"] = {
                "title": title_match.group(1).strip()[:200] if title_match else "",
                "description": desc_match.group(1).strip()[:500] if desc_match else "",
                "size_bytes": len(raw),
                "url": url,
            }

        if not result:
            result["content"] = raw[:50_000]

        return ConnectorResult(success=True, data=result,
                               latency_ms=_latency(), connector="web_scrape")
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="web_scrape")


# --- File Export ---

FILE_EXPORT_SPEC = ConnectorSpec(
    name="file_export",
    category="content",
    description="Export structured data to files in various formats",
    input_schema={
        "format": "str(json|csv|md|txt|html)",
        "filename": "str",
        "data": "any",
        "template": "str?",
    },
    output_schema={"path": "str", "size_bytes": "int", "format": "str"},
    risk_level="low",
    requires_approval=False,
    retry_compatible=True,
    estimated_latency_ms=100,
    failure_modes=["write_error", "invalid_format", "size_exceeded"],
)

_EXPORT_DIR = os.environ.get("JARVIS_EXPORT_DIR", "workspace/exports")
_MAX_EXPORT_SIZE = 500_000


def file_export_connector(params: dict) -> ConnectorResult:
    """Export structured data to files."""
    start = time.time()
    fmt = params.get("format", "json")
    filename = params.get("filename", f"export_{int(time.time())}")
    data = params.get("data", "")
    template = params.get("template", "")

    def _latency():
        return (time.time() - start) * 1000

    if fmt not in ("json", "csv", "md", "txt", "html"):
        return ConnectorResult(error=f"unsupported format: {fmt}",
                               latency_ms=_latency(), connector="file_export")

    # Sanitize filename
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")[:100]
    if not safe_name:
        safe_name = f"export_{int(time.time())}"

    os.makedirs(_EXPORT_DIR, exist_ok=True)
    filepath = os.path.join(_EXPORT_DIR, f"{safe_name}.{fmt}")

    try:
        content = ""
        if fmt == "json":
            content = json.dumps(data, indent=2, default=str)
        elif fmt == "csv":
            if isinstance(data, list) and data and isinstance(data[0], dict):
                headers = list(data[0].keys())
                lines = [",".join(headers)]
                for row in data[:1000]:
                    lines.append(",".join(str(row.get(h, "")) for h in headers))
                content = "\n".join(lines)
            else:
                content = str(data)
        elif fmt == "md":
            if template:
                content = template
                if isinstance(data, dict):
                    for k, v in data.items():
                        content = content.replace(f"{{{{{k}}}}}", str(v))
            else:
                content = str(data) if not isinstance(data, str) else data
        elif fmt == "html":
            if isinstance(data, str):
                content = f"<!DOCTYPE html><html><body>{data}</body></html>"
            else:
                content = f"<!DOCTYPE html><html><body><pre>{json.dumps(data, indent=2, default=str)}</pre></body></html>"
        else:
            content = str(data)

        if len(content) > _MAX_EXPORT_SIZE:
            return ConnectorResult(error="export too large",
                                   latency_ms=_latency(), connector="file_export")

        with open(filepath, "w") as f:
            f.write(content)

        return ConnectorResult(
            success=True,
            data={"path": filepath, "size_bytes": len(content), "format": fmt, "filename": safe_name},
            latency_ms=_latency(), connector="file_export",
        )
    except Exception as e:
        return ConnectorResult(error=str(e)[:200], latency_ms=_latency(), connector="file_export")



