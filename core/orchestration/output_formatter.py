"""
core/orchestration/output_formatter.py — Structured output formatting.

Takes raw mission output and produces cleaner, more actionable results.
Applies formatting based on task type: summaries, reports, lists, JSON.

Does NOT hallucinate structure. Only cleans and organizes existing content.
"""
from __future__ import annotations

import json
import re

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("orchestration.output_formatter")


def format_output(
    raw_output: str,
    task_type: str = "other",
    goal: str = "",
) -> str:
    """
    Format raw output based on task type.
    Returns cleaned output. Never invents content.
    """
    if not raw_output or not raw_output.strip():
        return raw_output

    output = raw_output.strip()

    # Remove common LLM artifacts
    output = _clean_artifacts(output)

    # Task-type-specific formatting
    if task_type in ("research", "analysis"):
        output = _format_analysis(output, goal)
    elif task_type == "query":
        output = _format_answer(output)

    return output


def _clean_artifacts(text: str) -> str:
    """Remove common LLM noise without changing content."""
    # Remove "Sure! Here's..." preambles
    preamble_patterns = [
        r"^(?:Sure[!,.]?\s*)?(?:Here'?s?\s+(?:is\s+)?(?:the\s+)?(?:a\s+)?)",
        r"^(?:Certainly[!,.]?\s*)",
        r"^(?:Of course[!,.]?\s*)",
        r"^(?:I'd be happy to help[!,.]?\s*)",
    ]
    for pattern in preamble_patterns:
        text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()

    # Remove trailing "Let me know if..." filler
    trailing_patterns = [
        r"\n*(?:Let me know if (?:you )?(?:need|want|have).*$)",
        r"\n*(?:Feel free to (?:ask|reach).*$)",
        r"\n*(?:Hope (?:this|that) helps[!.]?\s*$)",
        r"\n*(?:Is there anything else.*$)",
    ]
    for pattern in trailing_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    return text


def _format_analysis(text: str, goal: str) -> str:
    """Light formatting for analysis/research outputs."""
    # If output lacks structure but is long, it's fine as-is
    if len(text) < 100:
        return text

    # If it already has markdown headers, leave it
    if re.search(r'^#{1,3}\s', text, re.MULTILINE):
        return text

    # If it has bullet points, it's already structured
    if text.count('\n- ') >= 2 or text.count('\n* ') >= 2:
        return text

    return text


def _format_answer(text: str) -> str:
    """Format simple query answers."""
    # Remove unnecessary verbosity for simple answers
    lines = text.strip().split('\n')
    if len(lines) == 1 and len(text) < 200:
        return text  # Already concise

    return text


def try_extract_json(text: str) -> dict | list | None:
    """Try to extract JSON from text output. Returns None if not JSON."""
    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        _silent_log.debug("suppressed_exception", src='output_formatter.py')

    # Try to find JSON block in markdown
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            _silent_log.debug("suppressed_exception", src='output_formatter.py')

    return None
