from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, output: Any = None, **metadata) -> "ToolResult":
        return cls(success=True, output=output, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata) -> "ToolResult":
        return cls(success=False, error=error, metadata=metadata)
