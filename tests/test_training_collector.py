"""Unit tests for core.training_collector + core.llm_wrapper."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core.training_collector as tc
from core.llm_wrapper import _extract_text, _extract_tokens, patch_llm_factory


class TestClassifyDomain(unittest.TestCase):
    def test_patch_keyword(self):
        self.assertEqual(tc.classify_domain("apply this patch to the codebase"), "patch")

    def test_agent_keyword(self):
        self.assertEqual(tc.classify_domain("orchestrate the agent workflow"), "agent")

    def test_security_maps_to_cyber(self):
        self.assertEqual(tc.classify_domain("audit the SQL injection vulnerability"), "cyber")

    def test_code_keyword(self):
        self.assertEqual(tc.classify_domain("debug this Python function"), "code")

    def test_business_falls_to_general(self):
        self.assertEqual(tc.classify_domain("forecast the revenue for Q4"), "general")

    def test_unknown_falls_to_general(self):
        self.assertEqual(tc.classify_domain("hello"), "general")

    def test_source_hint_picks_agent(self):
        self.assertEqual(tc.classify_domain("hi", source="builder_agent"), "agent")

    def test_source_hint_picks_patch(self):
        self.assertEqual(tc.classify_domain("hi", source="self_improvement_loop"), "patch")


class TestAutoScore(unittest.TestCase):
    def test_empty_response_zero(self):
        self.assertEqual(tc.auto_score("q", ""), 0.0)

    def test_refusal_lowers_score(self):
        s = tc.auto_score("q", "I cannot help with that as an AI ...")
        self.assertLess(s, 5.0)

    def test_error_marker_lowers_score(self):
        s = tc.auto_score("q", "Traceback (most recent call last): ...")
        self.assertLess(s, 5.0)

    def test_valid_json_when_expected_boosts(self):
        s = tc.auto_score("Return JSON", '{"ok": true, "value": 42}')
        self.assertGreater(s, 5.0)

    def test_invalid_json_when_expected_drops(self):
        s = tc.auto_score("Return JSON", "sorry, I cannot")
        self.assertLess(s, 4.0)

    def test_long_response_boosted(self):
        s_short = tc.auto_score("q", "ok ok ok ok ok ok ok")
        s_long = tc.auto_score("q", "x" * 500)
        self.assertGreater(s_long, s_short)

    def test_score_bounded_0_10(self):
        s = tc.auto_score("q" * 10, "y" * 1000)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 10.0)


class TestRecordingLifecycle(unittest.TestCase):
    """End-to-end : enable, write, read back."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BEA_TRAINING_COLLECT"] = "1"
        os.environ["BEA_TRAINING_DIR"] = self._tmp.name
        # Reset writer + counters
        with tc._collector_lock:
            for k in tc._stats:
                tc._stats[k] = 0
        # Drop any stale worker so it picks up the new env
        tc._stop_event.set()
        tc._worker = None

    def tearDown(self):
        os.environ.pop("BEA_TRAINING_COLLECT", None)
        os.environ.pop("BEA_TRAINING_DIR", None)
        self._tmp.cleanup()

    def test_disabled_returns_none(self):
        os.environ["BEA_TRAINING_COLLECT"] = "0"
        rid = tc.record_llm_interaction(
            instruction="hi", response="hello", model="m"
        )
        self.assertIsNone(rid)

    def test_record_writes_jsonl(self):
        rid = tc.record_llm_interaction(
            instruction="audit the SQL injection vulnerability",
            response='{"finding": "ok"}',
            model="ollama/qwen",
            tokens_in=10,
            tokens_out=5,
            latency_ms=120,
            source="auditor",
        )
        self.assertIsNotNone(rid)
        self.assertTrue(tc.flush(timeout_s=2.0))

        records = list(tc.iter_records())
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["id"], rid)
        self.assertEqual(rec["model"], "ollama/qwen")
        self.assertEqual(rec["tokens_in"], 10)
        self.assertEqual(rec["latency_ms"], 120)
        self.assertEqual(rec["domain"], "cyber")  # 'security' → 'cyber'
        self.assertFalse(rec["validated"])
        self.assertIsInstance(rec["quality_score"], float)

    def test_get_stats_counts(self):
        for i in range(3):
            tc.record_llm_interaction(
                instruction=f"q{i}", response=f"r{i}", model="m"
            )
        self.assertTrue(tc.flush(timeout_s=2.0))
        s = tc.get_stats()
        self.assertGreaterEqual(s["written"], 3)
        self.assertEqual(s["total_records"], 3)
        self.assertTrue(s["enabled"])

    def test_validate_record(self):
        rid = tc.record_llm_interaction(instruction="q", response="r", model="m")
        self.assertTrue(tc.flush(timeout_s=2.0))
        self.assertTrue(tc.validate_record(rid))
        validated = list(tc.iter_records(validated_only=True))
        self.assertEqual(len(validated), 1)
        self.assertTrue(validated[0]["validated"])
        self.assertEqual(validated[0]["id"], rid)

    def test_validate_unknown_returns_false(self):
        self.assertFalse(tc.validate_record("does-not-exist"))


class TestExportFormats(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["BEA_TRAINING_COLLECT"] = "1"
        os.environ["BEA_TRAINING_DIR"] = self._tmp.name
        tc._stop_event.set()
        tc._worker = None

        tc.record_llm_interaction(
            instruction="Write a hello function",
            response="def hello(): return 'hi'",
            model="m",
            context="Python project",
        )
        self.assertTrue(tc.flush(timeout_s=2.0))

    def tearDown(self):
        os.environ.pop("BEA_TRAINING_COLLECT", None)
        os.environ.pop("BEA_TRAINING_DIR", None)
        self._tmp.cleanup()

    def test_alpaca_format(self):
        out = tc.export_records(format="alpaca")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["instruction"], "Write a hello function")
        self.assertEqual(out[0]["input"], "Python project")
        self.assertEqual(out[0]["output"], "def hello(): return 'hi'")

    def test_chatml_format(self):
        out = tc.export_records(format="chatml")
        msgs = out[0]["messages"]
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertEqual(msgs[0]["content"], "Python project")

    def test_sharegpt_format(self):
        out = tc.export_records(format="sharegpt")
        conv = out[0]["conversations"]
        self.assertEqual([c["from"] for c in conv], ["system", "human", "gpt"])

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            tc.export_records(format="bogus")


class TestAtomicWrite(unittest.TestCase):
    def test_atomic_append_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "out.jsonl"
            tc._atomic_append(target, json.dumps({"x": 1}))
            tc._atomic_append(target, json.dumps({"x": 2}))
            text = target.read_text(encoding="utf-8")
            self.assertEqual(text.strip().splitlines(), ['{"x": 1}', '{"x": 2}'])
            # tmp file should never linger after replace
            self.assertFalse(target.with_suffix(".jsonl.tmp").exists())


class TestLLMWrapperHelpers(unittest.TestCase):
    def test_extract_text_dict_messages(self):
        msgs = [
            {"role": "system", "content": "you are bea"},
            {"role": "user", "content": "hi"},
        ]
        text = _extract_text(msgs)
        self.assertIn("you are bea", text)
        self.assertIn("hi", text)

    def test_extract_tokens_from_response_metadata(self):
        class _Resp:
            response_metadata = {
                "token_usage": {"prompt_tokens": 7, "completion_tokens": 11}
            }

        self.assertEqual(_extract_tokens(_Resp()), (7, 11))

    def test_extract_tokens_missing_returns_zero(self):
        class _Resp:
            response_metadata = {}
        self.assertEqual(_extract_tokens(_Resp()), (0, 0))


class TestPatchIdempotent(unittest.TestCase):
    def test_patch_twice_returns_false_on_second(self):
        class FakeFactory:
            async def safe_invoke(self, messages, role="fast", **kw):
                return "x"

        self.assertTrue(patch_llm_factory(FakeFactory))
        self.assertFalse(patch_llm_factory(FakeFactory))


if __name__ == "__main__":
    unittest.main()
