"""Tests pour memory.consolidator — fonction pure, résumeur stub."""
from __future__ import annotations

from memory.consolidator import consolidate


def _summarizer(texts):
    return f"SUMMARY[{len(texts)}]: " + " | ".join(texts)


def test_no_op_under_threshold():
    items = [{"content": "a", "ts": 1}, {"content": "b", "ts": 2}]
    out = consolidate(items, max_items=5, summarizer=_summarizer)
    assert out == items


def test_folds_oldest_into_summary():
    items = [{"content": f"m{i}", "ts": i} for i in range(10)]
    out = consolidate(items, max_items=4, summarizer=_summarizer)
    # borné à max_items
    assert len(out) == 4
    # le 1er est la synthèse
    assert out[0]["kind"] == "summary"
    assert out[0]["folded"] == 7  # 10 - 4 + 1
    # les plus récents sont conservés intacts
    assert out[-1]["content"] == "m9"
    assert "m0" in out[0]["content"] and "m6" in out[0]["content"]


def test_summary_keeps_recent_timestamp_of_folded():
    items = [{"content": f"m{i}", "ts": i} for i in range(6)]
    out = consolidate(items, max_items=3, summarizer=_summarizer)
    assert out[0]["kind"] == "summary"
    # ts de la synthèse = le plus récent des items repliés (indices 0..3 -> ts 3)
    assert out[0]["ts"] == 3


def test_handles_empty_and_bad_input():
    assert consolidate([], max_items=5, summarizer=_summarizer) == []
    assert consolidate([{"content": "x", "ts": 1}], max_items=0, summarizer=_summarizer)
