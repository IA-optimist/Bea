"""
core/planning/step_retry.py — Step-level adaptive retry with incomplete output detection.

Detects malformed/incomplete LLM outputs and retries with escalating
strategies: same model → lower temperature → simpler prompt → switch model → give up.

Design:
  - Max 3 retries (4 total attempts)
  - Each strategy adapts parameters to increase chance of valid output
  - detect_incomplete_output() checks schema compliance, placeholders, empty fields
  - All operations are synchronous, fail-open
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import structlog

log = structlog.get_logger("planning.step_retry")

MAX_RETRIES = 3  # max retry attempts (4 total including first attempt)

# Known placeholder patterns that indicate non-real content
_PLACEHOLDER_PATTERNS = [
    r"\btodo\b", r"\bplaceholder\b", r"\blorem\s+ipsum\b",
    r"\bexample\b.*\bhere\b", r"\binsert\b.*\bhere\b",
    r"\b\[your\b", r"\b\[fill\b", r"\b\[add\b",
    r"\bTBD\b", r"\bXXX\b", r"\bFIXME\b",
]
_PLACEHOLDER_RE = re.compile("|".join(_PLACEHOLDER_PATTERNS), re.IGNORECASE)


class RetryStrategyType(str, Enum):
    SAME_MODEL = "same_model"
    LOWER_TEMP = "lower_temp"
    SWITCH_MODEL = "switch_model"
    GIVE_UP = "give_up"


@dataclass
class RetryStrategy:
    """Configuration for a single retry attempt."""
    strategy_type: RetryStrategyType
    temperature: float | None = None  # None = use default
    budget_mode: str | None = None    # None = use current
    prompt_suffix: str = ""           # Extra instruction appended to prompt
    simplify: bool = False            # Strip examples from prompt

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_type": self.strategy_type.value,
            "temperature": self.temperature,
            "budget_mode": self.budget_mode,
            "prompt_suffix": self.prompt_suffix[:80] if self.prompt_suffix else "",
            "simplify": self.simplify,
        }


# Escalation chain — ordered strategies for each retry attempt
_ESCALATION = [
    RetryStrategy(
        strategy_type=RetryStrategyType.SAME_MODEL,
        prompt_suffix="\n\nIMPORTANT: Return ONLY a valid JSON object. No markdown, no explanation.",
    ),
    RetryStrategy(
        strategy_type=RetryStrategyType.LOWER_TEMP,
        temperature=0.1,
        prompt_suffix="\n\nReturn ONLY valid JSON matching the schema. Be precise and complete.",
    ),
    RetryStrategy(
        strategy_type=RetryStrategyType.SWITCH_MODEL,
        budget_mode="budget",
        simplify=True,
        prompt_suffix="\n\nReturn a complete JSON object with ALL required fields filled with real content.",
    ),
]


def detect_incomplete_output(output: dict[str, Any], schema: list[dict[str, Any]]) -> list[str]:
    """
    Detect if LLM output is incomplete or malformed.

    Returns list of issue descriptions. Empty list = output is acceptable.

    Checks:
      1. Has 'raw_output' key → JSON parse failed
      2. Missing required schema fields
      3. Placeholder content in fields
      4. Empty fields where content expected
    """
    issues: list[str] = []

    if not output:
        issues.append("empty_output: output dict is empty")
        return issues

    # Check 1: raw_output means JSON parse failed entirely
    if "raw_output" in output and len(output) <= 2:
        issues.append("json_parse_failed: output contains raw_output (JSON parse failed)")

    # Get schema field names
    schema_fields: dict[str, Any] = {}
    for s in (schema or []):
        name = s.get("name", "")
        if name:
            schema_fields[name] = s.get("type", "text")

    if not schema_fields:
        return issues  # No schema to validate against

    # Check 2: Missing required fields
    for field_name, field_type in schema_fields.items():
        if field_name not in output:
            issues.append(f"missing_field: '{field_name}' not in output")

    # Check 3 & 4: Placeholder or empty content
    for field_name, field_type in schema_fields.items():
        value = output.get(field_name)

        if value is None:
            issues.append(f"null_field: '{field_name}' is None")
            continue

        # Empty check based on type
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                issues.append(f"empty_field: '{field_name}' is empty string")
            elif _PLACEHOLDER_RE.search(stripped):
                issues.append(f"placeholder: '{field_name}' contains placeholder content")
        elif isinstance(value, list):
            if len(value) == 0 and field_type in ("list", "array"):
                issues.append(f"empty_list: '{field_name}' is empty list")
        elif isinstance(value, dict):
            if len(value) == 0 and field_type in ("object", "dict"):
                issues.append(f"empty_dict: '{field_name}' is empty dict")

    return issues


def should_retry(issues: list[str], attempt: int) -> bool:
    """
    Determine if we should retry based on issues found and attempt count.

    Returns True if retry is warranted and we haven't exhausted attempts.
    """
    if not issues:
        return False
    if attempt >= MAX_RETRIES:
        return False
    # Always retry if we have issues and haven't hit max
    return True


def get_retry_strategy(attempt: int) -> RetryStrategy | None:
    """
    Get the retry strategy for a given attempt number (0-indexed).

    Returns None if attempt exceeds available strategies (give up).
    """
    if attempt < 0 or attempt >= len(_ESCALATION):
        return None
    return _ESCALATION[attempt]


def apply_strategy_to_prompt(prompt: str, strategy: RetryStrategy) -> str:
    """
    Apply retry strategy modifications to the prompt.

    - Adds suffix instruction
    - Optionally simplifies by removing example blocks
    """
    modified = prompt

    if strategy.simplify:
        # Remove example blocks (common pattern: "Example:" or "For example:" followed by content)
        modified = re.sub(
            r"(?:Example|For example|E\.g\.)[:\s].*?(?=\n\n|\n##|\Z)",
            "",
            modified,
            flags=re.DOTALL | re.IGNORECASE,
        )

    if strategy.prompt_suffix:
        modified = modified.rstrip() + strategy.prompt_suffix

    return modified


@dataclass
class RetryTrace:
    """Records all retry attempts for a step execution."""
    total_attempts: int = 1
    strategies_used: list[dict[str, Any]] = field(default_factory=list)
    issues_per_attempt: list[list[str]] = field(default_factory=list)
    final_attempt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_attempts": self.total_attempts,
            "strategies_used": self.strategies_used,
            "issues_per_attempt": self.issues_per_attempt,
            "final_attempt": self.final_attempt,
        }
