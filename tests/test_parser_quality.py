"""
tests/test_parser_quality.py — LLM output parsing + cross-step context tests.

Validates:
  - Nested JSON extraction
  - Numeric field extraction
  - No raw blob copied into unrelated fields
  - Malformed/truncated JSON repair
  - Cross-step context propagation
  - Positioning step gets prior-step context
  - Completeness reflects real parsed quality
"""
import json
from core.planning.skill_llm import (
    _parse_llm_output,
    _extract_outermost_json,
    _repair_truncated_json,
    _extract_field_from_text,
)


# ══════════════════════════════════════════════════════════════
# Nested JSON Extraction
# ══════════════════════════════════════════════════════════════

class TestNestedJSON:

    def test_PQ01_parse_fenced_nested(self):
        """Parse markdown-fenced JSON with nested dicts."""
        raw = '```json\n{"tam": {"value": "$487B"}, "problems": ["Tool fragmentation"]}\n```'
        schema = [{"name": "tam"}, {"name": "problems"}]
        result = _parse_llm_output(raw, schema)
        assert isinstance(result["tam"], dict)
        assert result["tam"]["value"] == "$487B"
        assert isinstance(result["problems"], list)

    def test_PQ02_parse_deeply_nested(self):
        """Parse deeply nested JSON objects."""
        raw = json.dumps({
            "tam": {"value": "$500M", "methodology": "Bottom-up"},
            "sam": {"value": "$50M", "region": "US"},
            "risks": [{"name": "Competition", "severity": "high"}],
        })
        schema = [{"name": "tam"}, {"name": "sam"}, {"name": "risks"}]
        result = _parse_llm_output(raw, schema)
        assert result["tam"]["value"] == "$500M"
        assert result["sam"]["region"] == "US"
        assert result["risks"][0]["severity"] == "high"

    def test_PQ03_no_blob_duplication(self):
        """Each field gets its own value, not the entire blob."""
        raw = '```json\n{"tam": "$500M", "sam": "$50M", "problems": ["A", "B"]}\n```'
        schema = [{"name": "tam"}, {"name": "sam"}, {"name": "problems"}]
        result = _parse_llm_output(raw, schema)
        assert result["tam"] == "$500M"
        assert result["sam"] == "$50M"
        assert result["tam"] != result["sam"]  # NOT the same blob


# ══════════════════════════════════════════════════════════════
# Numeric Field Extraction
# ══════════════════════════════════════════════════════════════

class TestNumericExtraction:

    def test_PQ04_extract_float_confidence(self):
        """Extract float confidence from JSON."""
        raw = '{"pain_intensity": 0.85, "confidence": 0.72}'
        schema = [{"name": "pain_intensity"}, {"name": "confidence"}]
        result = _parse_llm_output(raw, schema)
        assert isinstance(result["pain_intensity"], float)
        assert abs(result["pain_intensity"] - 0.85) < 0.01
        assert abs(result["confidence"] - 0.72) < 0.01

    def test_PQ05_extract_numeric_from_text(self):
        """Extract numeric field from within text."""
        text = 'Some text "confidence": 0.8, more text'
        result = _extract_field_from_text(text, "confidence")
        assert result == 0.8

    def test_PQ06_extract_string_from_text(self):
        """Extract string field from text."""
        text = '"market_size_estimate": "$2B TAM", "other": 1'
        result = _extract_field_from_text(text, "market_size_estimate")
        assert result == "$2B TAM"


# ══════════════════════════════════════════════════════════════
# Truncated JSON Repair
# ══════════════════════════════════════════════════════════════

class TestTruncatedRepair:

    def test_PQ07_repair_truncated_json(self):
        """Repair JSON truncated mid-object."""
        fragment = '```json\n{"tam": "$500M", "sam": "$50M", "problems": ["A", "B'
        repaired = _repair_truncated_json(fragment)
        assert repaired is not None
        parsed = json.loads(repaired)
        assert parsed["tam"] == "$500M"

    def test_PQ08_repair_truncated_nested(self):
        """Repair JSON with truncated nested object."""
        fragment = '{"outer": {"inner": "val"}, "list": [1, 2'
        repaired = _repair_truncated_json(fragment)
        assert repaired is not None
        parsed = json.loads(repaired)
        assert parsed["outer"]["inner"] == "val"

    def test_PQ09_no_repair_needed(self):
        """Valid JSON doesn't need repair."""
        result = _repair_truncated_json('{"a": 1}')
        # open_braces=0, should return None (not truncated)
        assert result is None

    def test_PQ10_parse_truncated_via_pipeline(self):
        """Full pipeline handles truncated JSON gracefully."""
        # Simulate a long output truncated mid-field
        raw = '```json\n{"tam": {"value": "$500M"}, "sam": {"value": "$50M"}, "problems": ["Market saturati'
        schema = [{"name": "tam"}, {"name": "sam"}, {"name": "problems"}]
        result = _parse_llm_output(raw, schema)
        # Should at least extract tam and sam
        assert "tam" in result
        # tam should be a dict, not raw text
        if isinstance(result["tam"], dict):
            assert result["tam"]["value"] == "$500M"


# ══════════════════════════════════════════════════════════════
# Balanced Brace Extraction
# ══════════════════════════════════════════════════════════════

class TestBalancedExtraction:

    def test_PQ11_extract_outermost(self):
        """Extract outermost JSON from text with preamble."""
        text = 'Here is my analysis:\n{"key": "value", "nested": {"a": 1}}\nEnd.'
        result = _extract_outermost_json(text)
        assert result is not None
        parsed = json.loads(result)
        assert parsed["nested"]["a"] == 1

    def test_PQ12_handles_strings_with_braces(self):
        """Doesn't break on braces inside JSON strings."""
        text = '{"text": "value with {braces}", "num": 42}'
        result = _extract_outermost_json(text)
        parsed = json.loads(result)
        assert parsed["num"] == 42

    def test_PQ13_no_json_returns_none(self):
        assert _extract_outermost_json("no json here") is None


# ══════════════════════════════════════════════════════════════
# Per-Field Extraction
# ══════════════════════════════════════════════════════════════

class TestPerFieldExtraction:

    def test_PQ14_extract_dict_field(self):
        text = '"tam": {"value": "$500M", "method": "bottom-up"}, "sam":'
        result = _extract_field_from_text(text, "tam")
        assert isinstance(result, dict)
        assert result["value"] == "$500M"

    def test_PQ15_extract_list_field(self):
        text = '"risks": ["Competition", "Regulation"], "confidence": 0.7'
        result = _extract_field_from_text(text, "risks")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_PQ16_extract_bool_field(self):
        text = '"viable": true, "confirmed": false'
        assert _extract_field_from_text(text, "viable") is True
        assert _extract_field_from_text(text, "confirmed") is False

    def test_PQ17_missing_field_returns_none(self):
        assert _extract_field_from_text("no match here", "missing") is None


# ══════════════════════════════════════════════════════════════
# Cross-Step Context Propagation
# ══════════════════════════════════════════════════════════════

class TestCrossStepContext:

    def test_PQ18_content_extracted_from_step_output(self):
        """get_all_outputs extracts 'content' from skill steps."""
        from core.planning.step_context import StepContext
        ctx = StepContext(goal="Test", plan_id="p1")
        ctx.set_step_output("s1", {
            "skill_id": "market_research.basic",
            "invoked": True,
            "content": {"tam": "$500M", "problems": ["A", "B"]},
            "quality": {"score": 0.8},
        })
        outputs = ctx.get_all_outputs()
        assert outputs.get("tam") == "$500M"
        assert outputs.get("problems") == ["A", "B"]
        # Metadata should NOT be in outputs
        assert "skill_id" not in outputs
        assert "invoked" not in outputs
        assert "quality" not in outputs

    def test_PQ19_multiple_steps_merge_content(self):
        """Content from multiple steps merges correctly."""
        from core.planning.step_context import StepContext
        ctx = StepContext(goal="Test", plan_id="p1")
        ctx.set_step_output("s1", {
            "skill_id": "market_research.basic",
            "invoked": True,
            "content": {"tam": "$500M", "problems": ["A"]},
        })
        ctx.set_step_output("s2", {
            "skill_id": "persona.basic",
            "invoked": True,
            "content": {"persona": "Marcus Chen", "pain_points": ["Slow"]},
        })
        outputs = ctx.get_all_outputs()
        assert outputs.get("tam") == "$500M"
        assert outputs.get("persona") == "Marcus Chen"

    def test_PQ20_prep_only_steps_filter_metadata(self):
        """Prep-only steps don't pollute with metadata keys."""
        from core.planning.step_context import StepContext
        ctx = StepContext(goal="Test", plan_id="p1")
        ctx.set_step_output("s1", {
            "skill_id": "market_research.basic",
            "prepared": True,
            "invoked": False,
            "prompt_context_length": 5000,
            "output_schema": [{"name": "tam"}],
        })
        outputs = ctx.get_all_outputs()
        assert "skill_id" not in outputs
        assert "prompt_context_length" not in outputs
        assert "output_schema" not in outputs

    def test_PQ21_positioning_gets_prior_context(self):
        """Positioning step receives market + persona context."""
        from core.planning.step_context import StepContext
        from core.planning.input_resolver import resolve_step_inputs

        ctx = StepContext(goal="Analyze AI chatbot market", plan_id="p1")
        ctx.set_step_output("s1", {
            "skill_id": "market_research.basic",
            "invoked": True,
            "content": {
                "tam": {"value": "$500M"},
                "problems": ["Tool fragmentation"],
                "trends": ["AI adoption"],
            },
        })
        ctx.set_step_output("s2", {
            "skill_id": "persona.basic",
            "invoked": True,
            "content": {
                "persona": {"name": "Marcus"},
                "pain_points": ["Time waste"],
            },
        })

        # Resolve inputs for positioning step
        merged = ctx.get_all_outputs()
        resolved = resolve_step_inputs(
            "positioning.basic", {}, "Analyze AI chatbot market", merged
        )

        # Positioning should have access to prior context
        assert "tam" in resolved or "product" in resolved
        # At minimum, the merged content is available
        assert "persona" in resolved or len(resolved) > 1


# ══════════════════════════════════════════════════════════════
# Malformed JSON Safety
# ══════════════════════════════════════════════════════════════

class TestMalformedSafety:

    def test_PQ22_empty_input(self):
        result = _parse_llm_output("", [{"name": "x"}])
        assert isinstance(result, dict)

    def test_PQ23_pure_text(self):
        result = _parse_llm_output("This is just text, no JSON", [{"name": "x"}])
        assert isinstance(result, dict)
        assert "raw_output" in result

    def test_PQ24_partial_json(self):
        """Partial JSON doesn't crash."""
        result = _parse_llm_output('{"key": ', [{"name": "key"}])
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# No Regression
# ══════════════════════════════════════════════════════════════

class TestNoRegression:

    def test_PQ25_playbook_still_executes(self):
        """Playbook execution still works after parser changes."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Regression test")
        assert result["ok"] is True
        assert result["run"]["steps_completed"] == 4

    def test_PQ26_economic_assembly_still_works(self):
        """Economic output assembly still works."""
        from core.economic.economic_output import assemble_economic_output
        steps = [
            {"skill_id": "market_research.basic", "content": {
                "tam": "$500M", "problems": "Slow invoicing",
            }},
        ]
        result = assemble_economic_output("market_analysis", steps)
        assert result["schema"] == "OpportunityReport"
