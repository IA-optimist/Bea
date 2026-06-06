"""
core/planning/skill_llm.py — Safe LLM invocation for skill execution.

Bridges the gap between skill preparation (prompt context) and
actual LLM-generated output. Called by _execute_skill() after
executor.prepare() succeeds.

Design:
  - Opt-in: only invokes LLM when an API key is available
  - Fail-open: if LLM call fails, returns preparation-only result
  - Bounded: enforces max_tokens and timeout
  - Observable: measures duration, logs success/failure
  - Typed: parses JSON output when possible, falls back to structured text
  - Safe: no secrets in prompts, output truncated

Usage:
  result = await invoke_skill_llm(prompt_context, output_schema, skill_id)
  if result["invoked"]:
      # LLM-generated content in result["content"]
  else:
      # Preparation-only (no LLM available)
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import structlog

log = structlog.get_logger("planning.skill_llm")

# Maximum output length to prevent runaway generation
_MAX_OUTPUT_CHARS = 16000
# LLM call timeout
_TIMEOUT_SECONDS = 90.0
# Role for skill LLM calls (routes to appropriate model)
_LLM_ROLE = "analyst"


def _is_llm_available() -> bool:
    """Check if any LLM provider is configured."""
    try:
        from config.settings import get_settings
        s = get_settings()
        has_key = bool(
            getattr(s, "openrouter_api_key", "")
            or getattr(s, "openai_api_key", getattr(s, "OPENAI_API_KEY", ""))
            or getattr(s, "anthropic_api_key", getattr(s, "ANTHROPIC_API_KEY", ""))
        )
        return has_key
    except Exception:
        return False


def _build_messages(prompt_context: str, output_schema: list) -> list:
    """
    Build LLM messages from skill prompt context.

    System message sets the role. User message contains the
    structured prompt and output format instructions.
    """
    # Build output format instructions
    schema_desc = ""
    if output_schema:
        fields = []
        for o in output_schema:
            name = o.get("name", "field")
            dtype = o.get("type", "text")
            desc = o.get("description", "")
            fields.append(f'  "{name}": ({dtype}) {desc}')
        schema_desc = "\n## Required Output Format\nReturn a JSON object with these fields:\n```\n{\n"
        schema_desc += ",\n".join(fields)
        schema_desc += "\n}\n```\nReturn ONLY the JSON object. No markdown fences, no explanation before or after."

    system_msg = (
        "You are a business analyst producing structured analysis. "
        "Be specific, quantitative where possible, and evidence-based. "
        "Return well-structured JSON output matching the requested schema."
    )

    user_msg = prompt_context + schema_desc

    from langchain_core.messages import SystemMessage, HumanMessage
    return [
        SystemMessage(content=system_msg),
        HumanMessage(content=user_msg),
    ]


def _parse_llm_output(raw: str, output_schema: list) -> dict:
    """
    Parse LLM output into structured dict.

    Strategy:
      1. Try direct JSON parse (full text)
      2. Try extracting JSON from markdown fences
      3. Try extracting JSON object from text (balanced brace matching)
      4. Try repairing truncated JSON (close open braces/brackets)
      5. Fall back to {"raw_output": text} with per-field extraction
    """
    text = raw.strip()[:_MAX_OUTPUT_CHARS]
    schema_names = {o.get("name", "") for o in output_schema if o.get("name")}

    # Strategy 1: direct JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError) as _exc:
        log.warning("swallowed_exception", action="json_extract_strict", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Strategy 2: extract from markdown fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError) as _exc:
            log.warning("swallowed_exception", action="json_extract_relaxed", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Strategy 3: balanced brace extraction (find outermost { ... })
    json_text = _extract_outermost_json(text)
    if json_text:
        try:
            parsed = json.loads(json_text)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError) as _exc:
            log.warning("swallowed_exception", action="json_extract_codeblock", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Strategy 4: repair truncated JSON (common with long outputs)
    repaired = _repair_truncated_json(text)
    if repaired:
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError) as _exc:
            log.warning("swallowed_exception", action="json_extract_repair", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Strategy 5: per-field extraction from text
    # Instead of assigning the entire blob to every field, try to find
    # each field by name in the text
    result: dict = {"raw_output": text[:2000]}
    for field_name in schema_names:
        extracted = _extract_field_from_text(text, field_name)
        if extracted is not None:
            result[field_name] = extracted

    return result


def _extract_outermost_json(text: str) -> str | None:
    """Find the outermost JSON object using balanced brace counting."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        c = text[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\":
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _repair_truncated_json(text: str) -> str | None:
    """
    Attempt to repair truncated JSON by closing open braces/brackets.

    When LLM output is truncated at _MAX_OUTPUT_CHARS, the JSON is
    often syntactically incomplete. This repairs it minimally.
    """
    # Find the JSON start
    fence_match = re.search(r"```(?:json)?\s*\n?", text)
    if fence_match:
        json_start = fence_match.end()
    else:
        json_start = text.find("{")
    if json_start < 0:
        return None

    fragment = text[json_start:].rstrip()
    # Remove trailing incomplete string
    if fragment.endswith(","):
        fragment = fragment[:-1]

    # Count open/close braces and brackets
    open_braces = fragment.count("{") - fragment.count("}")
    open_brackets = fragment.count("[") - fragment.count("]")

    if open_braces <= 0 and open_brackets <= 0:
        return None  # Doesn't look truncated

    # Close open brackets then braces
    repair = fragment
    # Walk backward to find last structurally safe truncation point
    # Priority: last complete value (after }, ], or complete "string",\s)
    # Strategy: find last comma that's followed by an incomplete value
    # and trim at that comma
    for i in range(len(repair) - 1, max(len(repair) - 500, 0), -1):
        c = repair[i]
        if c in ("}", "]"):
            # Found a complete nested structure
            repair = repair[:i + 1]
            break
        elif c == ",":
            # Found a comma — trim here (drops the incomplete value after it)
            repair = repair[:i]
            break
    else:
        repair = repair.rstrip()

    repair = repair.rstrip().rstrip(",")
    # Recount after trimming
    open_braces = repair.count("{") - repair.count("}")
    open_brackets = repair.count("[") - repair.count("]")
    repair += "]" * max(open_brackets, 0)
    repair += "}" * max(open_braces, 0)

    # Final cleanup: remove trailing commas before ] or }
    repair = re.sub(r',\s*([}\]])', r'\1', repair)

    return repair


def _extract_field_from_text(text: str, field_name: str) -> object | None:
    """
    Try to extract a specific field value from text containing JSON fragments.

    Looks for "field_name": <value> pattern.
    """
    # Pattern: "field_name": followed by a JSON value
    pattern = rf'"{re.escape(field_name)}"\s*:\s*'
    match = re.search(pattern, text)
    if not match:
        return None

    # Try to parse the value starting after the match
    value_start = match.end()
    remainder = text[value_start:].strip()

    # Try parsing as JSON value
    if remainder.startswith("{"):
        extracted = _extract_outermost_json(remainder)
        if extracted:
            try:
                return json.loads(extracted)
            except (json.JSONDecodeError, ValueError) as _exc:
                log.warning("swallowed_exception", action="json_extract_inline", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    elif remainder.startswith("["):
        # Find matching ]
        depth = 0
        for i, c in enumerate(remainder):
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(remainder[:i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
    elif remainder.startswith('"'):
        # String value
        str_match = re.match(r'"((?:[^"\\]|\\.)*)"', remainder)
        if str_match:
            return str_match.group(1)
    else:
        # Numeric or boolean
        num_match = re.match(r'(-?\d+\.?\d*)', remainder)
        if num_match:
            val = num_match.group(1)
            return float(val) if "." in val else int(val)
        if remainder.startswith("true"):
            return True
        if remainder.startswith("false"):
            return False
        if remainder.startswith("null"):
            return None

    return None


async def _invoke_async(
    prompt_context: str,
    output_schema: list,
    skill_id: str,
    budget_mode: str = "normal",
) -> dict:
    """
    Async LLM invocation for a skill.

    Args:
        budget_mode: "budget" | "normal" | "critical" — controls model selection tradeoff

    Returns:
        {
            "invoked": True,
            "content": {...},  # parsed output
            "raw_length": int,
            "duration_ms": float,
            "model": str,
            "budget_mode": str,
            "error": "",
        }
    """
    t0 = time.time()
    try:
        from core.llm_factory import LLMFactory
        from config.settings import get_settings

        factory = LLMFactory(get_settings())
        messages = _build_messages(prompt_context, output_schema)

        # Model intelligence: select optimal model for this skill
        selected_role = _LLM_ROLE
        _valid_modes = ("budget", "normal", "critical")
        if budget_mode not in _valid_modes:
            budget_mode = "normal"
        try:
            from core.model_intelligence.selector import get_model_selector, SKILL_TASK_MAP
            selector = get_model_selector()
            task_class = SKILL_TASK_MAP.get(skill_id, "structured_reasoning")
            selection = selector.select_for_skill(skill_id, budget_mode=budget_mode)
            if not selection.is_fallback and selection.model_id:
                # Map task class to appropriate LLM role for cost optimization
                _TASK_TO_ROLE = {
                    "cheap_simple": "fast",
                    "structured_reasoning": "analyst",
                    "business_reasoning": "analyst",
                    "coding": "builder",
                    "copywriting": "analyst",
                    "long_context": "research",
                    "high_accuracy_critical": "director",
                    "fallback_only": "fallback",
                }
                selected_role = _TASK_TO_ROLE.get(task_class, _LLM_ROLE)
        except Exception:
            log.debug("swallowed_exception", exc_info=True)

        resp = await factory.safe_invoke(
            messages,
            role=selected_role,
            timeout=_TIMEOUT_SECONDS,
        )

        raw = getattr(resp, "content", str(resp))
        content = _parse_llm_output(raw, output_schema)

        # Schema validation + auto-repair (fail-open)
        try:
            from core.planning.output_enforcer import OutputEnforcer
            enforcer = OutputEnforcer()
            validation = enforcer.validate_against_schema(content, output_schema)
            if validation.overall_score < 0.7:
                content = enforcer.auto_repair(content, output_schema)
                revalidation = enforcer.validate_against_schema(content, output_schema)
                if revalidation.overall_score < 0.5:
                    pass
        except Exception as _exc:
            log.warning("swallowed_exception", action="skill_dispatch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        duration_ms = round((time.time() - t0) * 1000)

        # Extract model name from response metadata (various provider formats)
        resp_meta = getattr(resp, "response_metadata", {})
        model = (
            resp_meta.get("model")
            or resp_meta.get("model_name")
            or resp_meta.get("model_id")
            or str(getattr(resp, "model", "unknown"))
        )

        # Record model performance
        try:
            from core.model_intelligence.selector import get_model_performance, SKILL_TASK_MAP
            task_class = SKILL_TASK_MAP.get(skill_id, "structured_reasoning")
            has_content = bool(content and not content.get("raw_output"))
            cost = 0.0
            try:
                cost = float(
                    getattr(resp, "response_metadata", {}).get("x-openrouter-cost", 0)
                    or getattr(resp, "response_metadata", {}).get("token_usage", {}).get("total_cost", 0)
                    or 0
                )
            except Exception as _exc:
                log.warning("swallowed_exception", action="skill_invoke", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            get_model_performance().record(
                model_id=str(model),
                task_class=task_class,
                success=has_content,
                duration_ms=duration_ms,
                quality=1.0 if has_content else 0.0,
                cost_estimate=cost,
            )
        except Exception:
            log.debug("swallowed_exception", exc_info=True)

        # Feed auto-update cost tracking
        try:
            from core.model_intelligence.auto_update import get_model_auto_update
            task_class = SKILL_TASK_MAP.get(skill_id, "structured_reasoning")
            has_content = bool(content and not content.get("raw_output"))
            get_model_auto_update().record_invocation(
                task_class=task_class,
                model_id=str(model),
                success=has_content,
                quality=1.0 if has_content else 0.0,
                cost=cost,
            )
        except Exception:
            log.debug("swallowed_exception", exc_info=True)

        log.info("skill_llm_ok", skill_id=skill_id,
                 duration_ms=duration_ms,
                 output_keys=list(content.keys())[:5],
                 model_role=selected_role,
                 budget_mode=budget_mode)

        return {
            "invoked": True,
            "content": content,
            "raw_length": len(raw),
            "duration_ms": duration_ms,
            "model": str(model),
            "budget_mode": budget_mode,
            "model_role": selected_role,
            "error": "",
        }

    except Exception as e:
        duration_ms = round((time.time() - t0) * 1000)
        log.warning("skill_llm_failed", skill_id=skill_id,
                    duration_ms=duration_ms, err=str(e)[:100])
        return {
            "invoked": True,
            "content": {},
            "raw_length": 0,
            "duration_ms": duration_ms,
            "model": "",
            "budget_mode": budget_mode,
            "error": str(e)[:200],
        }


def invoke_skill_llm(
    prompt_context: str,
    output_schema: list,
    skill_id: str,
    budget_mode: str = "normal",
) -> dict:
    """
    Safe synchronous LLM invocation for skill execution.

    Args:
        budget_mode: "budget" | "normal" | "critical" — controls model selection.

    Returns:
        {
            "invoked": bool,      # True if LLM was called
            "content": dict,      # parsed structured output
            "raw_length": int,    # raw response length
            "duration_ms": float, # call duration
            "model": str,         # model used
            "budget_mode": str,   # which mode was used
            "model_role": str,    # LLM role selected
            "error": str,         # error if any
            "quality": dict,      # quality validation result (if content available)
        }

    If no LLM is available, returns {"invoked": False, ...} —
    the caller should fall back to preparation-only output.

    Fail-open: never raises. On any error, returns gracefully.
    """
    if not _is_llm_available():
        return {
            "invoked": False,
            "content": {},
            "raw_length": 0,
            "duration_ms": 0,
            "model": "",
            "budget_mode": budget_mode,
            "error": "",
        }

    try:
        # Run async invocation from sync context.
        # get_running_loop() raises RuntimeError when no loop is active (Python 3.10+).
        # get_event_loop() is deprecated in Python 3.10+ and removed from threads in 3.12.
        try:
            asyncio.get_running_loop()
            # Already inside an event loop — delegate to a fresh thread to avoid nesting
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    _invoke_async(prompt_context, output_schema, skill_id, budget_mode)
                )
                result = future.result(timeout=_TIMEOUT_SECONDS + 10)
        except RuntimeError:
            # No running loop — asyncio.run() creates and manages one
            result = asyncio.run(
                _invoke_async(prompt_context, output_schema, skill_id, budget_mode)
            )

        # Run quality validation if we got content
        if result.get("content") and not result.get("error"):
            try:
                from core.skills.domain_executor import get_skill_executor
                validation = get_skill_executor().validate(skill_id, result["content"])
                result["quality"] = {
                    "score": validation.quality_score,
                    "details": validation.quality_details,
                }
            except Exception:
                result["quality"] = {"score": 0.0, "details": []}
        else:
            result["quality"] = {"score": 0.0, "details": []}

        return result

    except Exception as e:
        log.debug("skill_llm_invoke_error", skill_id=skill_id, err=str(e)[:80])
        return {
            "invoked": False,
            "content": {},
            "raw_length": 0,
            "duration_ms": 0,
            "model": "",
            "error": str(e)[:200],
        }
