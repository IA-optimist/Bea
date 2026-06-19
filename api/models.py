"""
BEA MAX — Phase 9 Mission Control models.
MissionLogEvent and MissionSummary dataclasses.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum


class LogEventType(str, Enum):
    AGENT_DECISION   = "agent_decision"
    TOOL_CALL        = "tool_call"
    TOOL_RESULT      = "tool_result"
    MEMORY_WRITE     = "memory_write"
    ERROR            = "error"
    FALLBACK         = "fallback"
    STATUS_CHANGE    = "status_change"
    APPROVAL_REQUEST = "approval_request"
    USER_ACTION      = "user_action"


@dataclass
class MissionLogEvent:
    mission_id:  str
    event_type:  LogEventType
    message:     str
    agent_id:    str   = ""
    tool_name:   str   = ""
    risk_level:  str   = "safe"
    data:        dict[str, object] = field(default_factory=dict)
    event_id:    str   = field(default_factory=lambda: str(uuid.uuid4())[:10])
    timestamp:   float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        # Ensure event_type is a string value
        d["event_type"] = self.event_type.value if hasattr(self.event_type, "value") else str(self.event_type)
        return d


@dataclass
class MissionSummary:
    mission_id:        str
    goal:              str
    status:            str
    tools_used:        list[str]
    agents_involved:   list[str]
    errors:            list[str]
    lessons_learned:   list[str]
    performance_score: float      # 0-1
    duration_ms:       int
    created_at:        float
    completed_at:      float = 0.0
    metadata:          dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
