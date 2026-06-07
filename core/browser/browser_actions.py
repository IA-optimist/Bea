"""
BEA MAX — Browser Actions
================================
Structured browser action execution with policy enforcement.

Each action is a dataclass describing WHAT to do.
The BrowserAgent evaluates policy BEFORE executing.
Results are always structured, never raw HTML blobs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActionResult:
    """Result of a browser action."""
    success: bool
    action: str
    data: dict = field(default_factory=dict)
    error: str = ""
    screenshot_path: str = ""
    needs_approval: bool = False
    approval_request: dict | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success, "action": self.action,
            "data": self.data, "error": self.error[:200],
            "has_screenshot": bool(self.screenshot_path),
            "needs_approval": self.needs_approval,
        }


@dataclass
class NavigateAction:
    url: str
    wait_for: str = ""           # CSS selector to wait for
    timeout_ms: int = 30000

@dataclass
class ClickAction:
    selector: str
    text: str = ""               # Click element containing this text

@dataclass
class TypeAction:
    selector: str
    value: str
    clear_first: bool = True
    is_secret: bool = False      # If True, value comes from vault

@dataclass
class SelectAction:
    selector: str
    value: str

@dataclass
class UploadAction:
    selector: str
    file_path: str

@dataclass
class DownloadAction:
    trigger_selector: str        # Element to click to start download
    expected_filename: str = ""

@dataclass
class ExtractAction:
    mode: str = "text"           # text, links, table, forms, title, metadata
    selector: str = ""           # Scope extraction to this element

@dataclass
class ScreenshotAction:
    full_page: bool = False
    selector: str = ""           # Screenshot specific element

@dataclass
class SecretInjectionAction:
    """Inject a secret from vault into a form field."""
    selector: str
    secret_id: str
    identity_id: str = ""
    domain: str = ""
    purpose: str = ""


# ── Extraction Results ──

@dataclass
class ExtractedData:
    """Structured extraction result."""
    title: str = ""
    text: str = ""
    links: list[dict] = field(default_factory=list)     # [{text, href}]
    tables: list[list[list[str]]] = field(default_factory=list)  # [[[cell]]]
    forms: list[dict] = field(default_factory=list)      # [{action, method, fields}]
    metadata: dict = field(default_factory=dict)         # {description, og:*, etc}

    def to_dict(self) -> dict:
        return {
            "title": self.title[:200],
            "text_length": len(self.text),
            "text_preview": self.text[:500],
            "links": self.links[:50],
            "tables": len(self.tables),
            "forms": self.forms[:10],
            "metadata": {k: v[:200] for k, v in self.metadata.items()},
        }


# ── Login Flow ──

@dataclass
class LoginFlow:
    """Structured login sequence for a service."""
    identity_id: str
    url: str
    steps: list[dict] = field(default_factory=list)
    # Each step: {action: "type|click|wait", selector: "...", value: "secret:role" or literal}
    success_indicator: str = ""  # Selector that appears on success
    failure_indicator: str = ""  # Selector that appears on failure

    def to_dict(self) -> dict:
        return {
            "identity_id": self.identity_id,
            "url": self.url,
            "steps": len(self.steps),
            "has_success_check": bool(self.success_indicator),
        }
