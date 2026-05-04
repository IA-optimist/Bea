"""
JARVIS MAX — Browser Session Model
======================================
Session lifecycle for browser automation.
Each session is isolated with its own download sandbox.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path


class SessionStatus:
    ACTIVE = "active"
    PAUSED = "paused"           # Waiting for approval
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class BrowserSession:
    """Isolated browser session state."""
    session_id: str
    identity_id: str = ""
    workspace_id: str = ""
    environment: str = "prod"
    agent_name: str = ""
    purpose: str = ""

    # State
    status: str = "active"
    current_url: str = ""
    page_title: str = ""
    navigation_count: int = 0
    action_count: int = 0

    # Isolation
    downloads_path: str = ""     # Per-session sandbox dir
    cookies_ref: str = ""        # Reference to stored cookies

    # Timing
    start_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    end_time: float | None = None

    # Pending approvals
    pending_approvals: list[dict] = field(default_factory=list)

    # Action history (last N for replay)
    action_history: list[dict] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status == SessionStatus.ACTIVE

    @property
    def duration_s(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    def touch(self) -> None:
        self.last_activity = time.time()

    def record_action(self, action: str, target: str = "", result: str = "success") -> None:
        self.action_history.append({
            "ts": time.time(), "action": action,
            "target": target[:200], "result": result,
        })
        self.action_count += 1
        self.touch()
        # Keep only last 200 actions in memory
        if len(self.action_history) > 200:
            self.action_history = self.action_history[-200:]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "identity_id": self.identity_id,
            "agent": self.agent_name,
            "status": self.status,
            "url": self.current_url[:200],
            "title": self.page_title[:100],
            "navigations": self.navigation_count,
            "actions": self.action_count,
            "duration_s": round(self.duration_s),
            "pending_approvals": len(self.pending_approvals),
            "purpose": self.purpose[:200],
        }

    def close(self, status: str = "completed") -> None:
        self.status = status
        self.end_time = time.time()


def create_session(
    agent_name: str,
    identity_id: str = "",
    workspace_id: str = "",
    environment: str = "prod",
    purpose: str = "",
    sandbox_root: str = "data/browser_sessions",
) -> BrowserSession:
    """Create a new isolated browser session."""
    sid = f"bs-{hashlib.md5(f'{agent_name}{time.time()}'.encode()).hexdigest()[:10]}"

    # Create isolated downloads directory
    downloads = Path(sandbox_root) / sid / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)

    return BrowserSession(
        session_id=sid,
        identity_id=identity_id,
        workspace_id=workspace_id,
        environment=environment,
        agent_name=agent_name,
        purpose=purpose,
        downloads_path=str(downloads),
    )
