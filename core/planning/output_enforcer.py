"""
core/planning/output_enforcer.py — Schema validation and auto-repair for LLM outputs.

Validates parsed LLM output against skill output schemas, attempts
type coercion and structural fixes, and builds correction prompts
when auto-repair is insufficient.

Design:
  - Type-aware validation: text, number, list, dict, boolean
  - Auto-repair: coerce types, fill defaults, split strings to lists
  - Scoring: 1.0 (correct), 0.5 (repaired), 0.0 (missing/unfixable)
  - Fail-open: never raises, always returns a result
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


# Schema type normalization
_TYPE_MAP = {
    "text": "string", "string": "string", "str": "string",
    "number": "number", "float": "number", "int": "number", "integer": "number",
    "list": "list", "array": "list",
    "object": "dict", "dict": "dict",
    "boolean": "bool", "bool": "bool",
}


@dataclass
class ValidationResult:
    """Result of validating output against schema."""
    valid: bool
    issues: list[str] = field(default_factory=list)
    field_scores: dict[str, float] = field(default_factory=dict)
    overall_score: float = 1.0

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "issues": self.issues,
            "field_scores": self.field_scores,
            "overall_score": self.overall_score,
        }


class OutputEnforcer:
    """Validates and repairs LLM output against skill schemas."""

    def validate_against_schema(
        self, output: dict, schema: list
    ) -> ValidationResult:
        """
        Validate output dict against schema field definitions.

        Schema format: [{"name": "field_name", "type": "text", "description": "..."}]
        """
        if not schema:
            return ValidationResult(valid=True, overall_score=1.0)

        if not output:
            fields = {s.get("name", ""): 0.0 for s in schema if s.get("name")}
            return ValidationResult(
                valid=False,
                issues=["empty_output"],
                field_scores=fields,
                overall_score=0.0,
            )

        issues: list[str] = []
        field_scores: dict[str, float] = {}

        for spec in schema:
            name = spec.get("name", "")
            if not name:
                continue
            expected_type = _TYPE_MAP.get(spec.get("type", "text"), "string")

            if name not in output:
                issues.append(f"missing: {name}")
                field_scores[name] = 0.0
                continue

            value = output[name]
            if value is None:
                issues.append(f"null: {name}")
                field_scores[name] = 0.0
                continue

            # Type check
            if not self._type_matches(value, expected_type):
                issues.append(f"wrong_type: {name} expected {expected_type}, got {type(value).__name__}")
                field_scores[name] = 0.3  # present but wrong type
            elif self._is_empty(value, expected_type):
                issues.append(f"empty: {name}")
                field_scores[name] = 0.2
            else:
                field_scores[name] = 1.0

        overall = sum(field_scores.values()) / len(field_scores) if field_scores else 1.0
        return ValidationResult(
            valid=len(issues) == 0,
            issues=issues,
            field_scores=field_scores,
            overall_score=round(overall, 3),
        )

    def auto_repair(self, output: dict, schema: list) -> dict:
        """
        Attempt to repair output by coercing types and filling defaults.

        Returns a new dict with repairs applied. Does not modify original.
        """
        if not schema:
            return dict(output) if output else {}

        repaired = dict(output)

        for spec in schema:
            name = spec.get("name", "")
            if not name:
                continue
            expected_type = _TYPE_MAP.get(spec.get("type", "text"), "string")
            value = repaired.get(name)

            if value is None or name not in repaired:
                # Fill default
                repaired[name] = self._default_for_type(expected_type)
                continue

            if not self._type_matches(value, expected_type):
                # Attempt coercion
                coerced = self._coerce(value, expected_type)
                if coerced is not None:
                    repaired[name] = coerced
                else:
                    repaired[name] = self._default_for_type(expected_type)

        return repaired

    def build_correction_prompt(
        self, output: dict, schema: list, issues: list[str]
    ) -> str:
        """Build a prompt asking LLM to fix specific issues in its output."""
        schema_desc = []
        for s in schema:
            name = s.get("name", "")
            dtype = s.get("type", "text")
            desc = s.get("description", "")
            schema_desc.append(f'  "{name}": ({dtype}) {desc}')

        issues_desc = "\n".join(f"  - {i}" for i in issues)

        return (
            "Your previous output had the following issues:\n"
            f"{issues_desc}\n\n"
            "Please fix these issues and return a complete, valid JSON object.\n\n"
            "Required schema:\n{\n" + ",\n".join(schema_desc) + "\n}\n\n"
            "Previous (malformed) output:\n"
            f"```json\n{json.dumps(output, default=str)[:4000]}\n```\n\n"
            "Return ONLY the corrected JSON object."
        )

    # ── Private helpers ────────────────────────────────────────────

    @staticmethod
    def _type_matches(value: object, expected: str) -> bool:
        """Check if value matches expected normalized type."""
        if expected == "string":
            return isinstance(value, str)
        elif expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected == "list":
            return isinstance(value, list)
        elif expected == "dict":
            return isinstance(value, dict)
        elif expected == "bool":
            return isinstance(value, bool)
        return True  # unknown type = permissive

    @staticmethod
    def _is_empty(value: object, expected: str) -> bool:
        """Check if value is empty for its type."""
        if expected == "string":
            return isinstance(value, str) and not value.strip()
        elif expected == "list":
            return isinstance(value, list) and len(value) == 0
        elif expected == "dict":
            return isinstance(value, dict) and len(value) == 0
        return False

    @staticmethod
    def _default_for_type(expected: str) -> object:
        """Return sensible default for a type."""
        defaults = {
            "string": "",
            "number": 0,
            "list": [],
            "dict": {},
            "bool": False,
        }
        return defaults.get(expected, "")

    @staticmethod
    def _coerce(value: object, expected: str) -> object | None:
        """Try to coerce value to expected type. Returns None if impossible."""
        if expected == "list" and isinstance(value, str):
            # Split string into list
            if "\n" in value:
                return [line.strip() for line in value.split("\n") if line.strip()]
            elif "," in value:
                return [item.strip() for item in value.split(",") if item.strip()]
            return [value]

        if expected == "number" and isinstance(value, str):
            match = re.search(r"-?\d+\.?\d*", value)
            if match:
                num_str = match.group()
                return float(num_str) if "." in num_str else int(num_str)

        if expected == "dict" and isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                _silent_log.debug("suppressed_exception", src='output_enforcer.py')

        if expected == "string" and not isinstance(value, str):
            return str(value)

        if expected == "bool":
            if isinstance(value, str):
                return value.lower() in ("true", "yes", "1")
            if isinstance(value, (int, float)):
                return bool(value)

        return None
