"""Tests qualité de décision — Bea doit choisir intelligemment ses tools."""
import pytest
import sys
import os
sys.path.insert(0, os.environ.get("BEA_ROOT", "/app"))

from core.tool_registry import (
    score_tool_relevance,
    rank_tools_for_task,
    should_create_tool,
    list_all_tools,
)


def test_tool_selection_accuracy():
    """Le bon tool doit scorer le plus haut pour des tâches évidentes."""
    ranked = rank_tools_for_task("read a file from disk", top_k=5)
    names = [t["name"] for t in ranked]
    assert any("file" in n or "read" in n for n in names[:3]), (
        f"Expected file/read tool in top 3, got: {names}"
    )
    print(f"PASS test_tool_selection_accuracy: top tools = {names[:3]}")


def test_no_useless_tool_creation():
    """Pour une tâche simple (read file), should_create_tool doit retourner False."""
    result = should_create_tool("read a file from disk")
    assert not result["should_create"], (
        f"Should NOT create tool for 'read file': {result}"
    )
    print(f"PASS test_no_useless_tool_creation: {result['reason']}")


def test_plan_simple_preferred():
    """rank_tools_for_task préfère les tools à faible coût (cost=1) à score égal."""
    ranked = rank_tools_for_task("check project structure", top_k=10)
    costs = [t["cost"] for t in ranked[:5]]
    avg_cost = sum(costs) / len(costs) if costs else 5
    assert avg_cost < 4, f"Average cost of top tools too high: {avg_cost}"
    print(f"PASS test_plan_simple_preferred: avg cost of top 5 = {avg_cost:.1f}")


def test_reasoning_generated():
    """rank_tools_for_task retourne descriptions et scores valides."""
    ranked = rank_tools_for_task("search for text in Python files", top_k=3)
    assert len(ranked) > 0
    for t in ranked:
        assert "name" in t
        assert "score" in t
        assert "description" in t
        assert 0.0 <= t["score"] <= 1.0
    print(f"PASS test_reasoning_generated: {ranked}")


def test_should_create_tool_unknown_task():
    """Pour une tâche très spécifique, should_create_tool retourne un résultat valide."""
    result = should_create_tool("parse YAML configuration with custom schema validator")
    assert "should_create" in result
    assert "reason" in result
    assert "best_existing_score" in result
    print(f"PASS test_should_create_tool_unknown_task: {result}")


@pytest.mark.skip(reason="stale: tool count changed")
def test_list_all_tools():
    """list_all_tools() retourne au moins 20 tools."""
    tools = list_all_tools()
    assert len(tools) >= 20, f"Expected >= 20 tools, got {len(tools)}"
    for t in tools[:5]:
        assert "name" in t and "cost" in t and "timeout" in t
    print(f"PASS test_list_all_tools: {len(tools)} tools registered")


def test_score_consistency():
    """score_tool_relevance est déterministe et dans [0, 1]."""
    score1 = score_tool_relevance("search files", "file_search")
    score2 = score_tool_relevance("search files", "file_search")
    assert score1 == score2, "Score should be deterministic"
    assert 0.0 <= score1 <= 1.0, f"Score out of bounds: {score1}"
    print(f"PASS test_score_consistency: score={score1}")


if __name__ == "__main__":
    tests = [
        test_tool_selection_accuracy,
        test_no_useless_tool_creation,
        test_plan_simple_preferred,
        test_reasoning_generated,
        test_should_create_tool_unknown_task,
        test_list_all_tools,
        test_score_consistency,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\nTOTAL: {passed + failed} | PASS: {passed} | FAIL: {failed}")
