"""
BEA MAX — Tool Intelligence: Smart Selector

TF-IDF based tool selection, confidence scoring, tool chains.
See module docstring in the original tool_intelligence.py for full design.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()


# ── Tool Metadata ─────────────────────────────────────────────

@dataclass
class ToolMetadata:
    """Rich tool description for intelligent selection."""
    name: str
    description: str = ""
    semantic_tags: list[str] = field(default_factory=list)
    risk_level: str = "low"
    timeout_s: int = 10
    cost: int = 3
    requires_network: bool = False
    idempotent: bool = True
    total_calls: int = 0
    success_count: int = 0
    avg_duration_ms: float = 0.0
    last_error: str = ""
    last_used: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_calls if self.total_calls > 0 else 1.0

    @property
    def confidence(self) -> float:
        if self.total_calls == 0:
            return 0.5
        base = self.success_rate
        recency_penalty = 0.0
        if self.last_used > 0:
            hours_since = (time.time() - self.last_used) / 3600
            if hours_since > 24:
                recency_penalty = min(0.1, hours_since / 240)
        sample_factor = min(1.0, self.total_calls / 10)
        return max(0.1, base * sample_factor + 0.5 * (1 - sample_factor) - recency_penalty)


@dataclass
class ToolRecommendation:
    tool: str
    score: float
    confidence: float
    reasoning: str
    risk: str
    alternatives: list[str] = field(default_factory=list)


# ── TF-IDF ────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r'\w+', text.lower()) if len(w) > 2]


def _tfidf_similarity(query_tokens: list[str], doc_tokens: list[str],
                      idf: dict[str, float]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    q_tf = Counter(query_tokens)
    d_tf = Counter(doc_tokens)
    vocab = set(q_tf.keys()) | set(d_tf.keys())
    q_vec = {w: q_tf.get(w, 0) * idf.get(w, 1.0) for w in vocab}
    d_vec = {w: d_tf.get(w, 0) * idf.get(w, 1.0) for w in vocab}
    dot = sum(q_vec[w] * d_vec[w] for w in vocab)
    mag_q = math.sqrt(sum(v**2 for v in q_vec.values())) or 1.0
    mag_d = math.sqrt(sum(v**2 for v in d_vec.values())) or 1.0
    return dot / (mag_q * mag_d)


# ── Tool Chains ──────────────────────────────────────────────

_TOOL_CHAINS: dict[str, list[str]] = {
    "code_fix": ["read_file", "search_codebase", "write_file", "shell_command"],
    "test_and_fix": ["shell_command", "read_file", "write_file", "shell_command"],
    "analyze_repo": ["search_codebase", "read_file", "vector_search"],
    "deploy": ["shell_command", "docker_compose_build", "docker_compose_up", "api_healthcheck"],
    "research": ["http_get", "vector_search", "read_file"],
    "refactor": ["search_codebase", "read_file", "write_file", "shell_command", "read_file"],
    "add_test": ["read_file", "search_codebase", "write_file", "shell_command"],
    "debug": ["read_file", "shell_command", "search_codebase", "write_file"],
    "document": ["read_file", "search_codebase", "write_file"],
}

_WORKFLOW_PATTERNS: dict[str, list[str]] = {
    "code_fix": ["fix", "bug", "patch", "repair", "correct"],
    "test_and_fix": ["test", "validate", "verify", "check", "assert"],
    "analyze_repo": ["analyze", "inspect", "audit", "review", "scan"],
    "deploy": ["deploy", "restart", "build", "start", "docker"],
    "research": ["research", "find", "search", "explore", "learn"],
    "refactor": ["refactor", "restructure", "reorganize", "clean", "improve"],
    "add_test": ["add test", "write test", "create test", "test coverage"],
    "debug": ["debug", "trace", "investigate", "diagnose", "troubleshoot"],
    "document": ["document", "describe", "explain", "readme", "docstring"],
}


# ── Main Class ────────────────────────────────────────────────

class ToolSelector:
    """Smart tool selection engine."""

    def __init__(self):
        self._tools: dict[str, ToolMetadata] = {}
        self._idf: dict[str, float] = {}
        self._tool_docs: dict[str, list[str]] = {}
        self._outcomes: list[dict] = []
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            from core.tool_registry import (
                _SEMANTIC_DESCRIPTIONS, _TOOL_COSTS,
                _EXECUTOR_TIMEOUTS, get_tool_registry,
            )
            from core.capability_intelligence import _TOOL_TO_TAGS, _TOOL_SIDE_EFFECTS

            reg = get_tool_registry()
            reg_tools = {t.name: t for t in reg.list_tools()}

            for name in set(_SEMANTIC_DESCRIPTIONS.keys()) | set(reg_tools.keys()):
                desc = _SEMANTIC_DESCRIPTIONS.get(name, "")
                tags = sorted(_TOOL_TO_TAGS.get(name, set()))
                risk = _TOOL_SIDE_EFFECTS.get(name, "none")
                cost = _TOOL_COSTS.get(name, 3)
                timeout = _EXECUTOR_TIMEOUTS.get(name, 10)
                reg_tool = reg_tools.get(name)

                self._tools[name] = ToolMetadata(
                    name=name, description=desc, semantic_tags=tags,
                    risk_level=risk, timeout_s=timeout, cost=cost,
                    requires_network=getattr(reg_tool, "requires_network", False) if reg_tool else False,
                    idempotent=getattr(reg_tool, "idempotent", True) if reg_tool else True,
                )
                doc_text = f"{name} {desc} {' '.join(tags)}"
                self._tool_docs[name] = _tokenize(doc_text)

            n_docs = len(self._tool_docs) or 1
            all_words: set[str] = set()
            for tokens in self._tool_docs.values():
                all_words.update(tokens)
            for word in all_words:
                doc_count = sum(1 for tokens in self._tool_docs.values() if word in tokens)
                self._idf[word] = math.log(n_docs / (1 + doc_count))
        except Exception as e:
            log.debug("tool_selector_init_degraded", err=str(e)[:100])

    def select_tools(self, goal: str, context: str = "",
                     max_results: int = 5, min_confidence: float = 0.3) -> list[ToolRecommendation]:
        self._ensure_initialized()
        if not self._tools:
            return []

        query_tokens = _tokenize(f"{goal} {context}")
        if not query_tokens:
            return []

        scored: list[tuple[str, float, str]] = []
        for name, meta in self._tools.items():
            doc_tokens = self._tool_docs.get(name, [])
            sim = _tfidf_similarity(query_tokens, doc_tokens, self._idf)
            conf = meta.confidence
            risk_penalty = {"none": 0, "low": 0.02, "medium": 0.05,
                            "high": 0.1, "critical": 0.2}.get(meta.risk_level, 0)
            score = (0.55 * sim) + (0.35 * conf) - risk_penalty
            if score > 0.1:
                scored.append((name, score, f"sim={sim:.2f} conf={conf:.2f}"))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for name, score, reasoning in scored[:max_results]:
            meta = self._tools[name]
            if score < min_confidence:
                continue
            alternatives = [s[0] for s in scored if s[0] != name][:3]
            results.append(ToolRecommendation(
                tool=name, score=round(score, 3), confidence=round(meta.confidence, 3),
                reasoning=reasoning, risk=meta.risk_level, alternatives=alternatives,
            ))
        return results

    def get_tool_chain(self, goal: str) -> list[str]:
        goal_lower = goal.lower()
        best_match = ""
        best_score = 0
        for pattern_name, keywords in _WORKFLOW_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in goal_lower)
            if score > best_score:
                best_score = score
                best_match = pattern_name
        if best_match and best_match in _TOOL_CHAINS:
            return _TOOL_CHAINS[best_match]
        recs = self.select_tools(goal, max_results=4)
        return [r.tool for r in recs]

    def score_tool(self, tool_name: str) -> float:
        self._ensure_initialized()
        meta = self._tools.get(tool_name)
        return meta.confidence if meta else 0.0

    def get_tool_metadata(self, tool_name: str) -> dict:
        self._ensure_initialized()
        meta = self._tools.get(tool_name)
        if not meta:
            return {"name": tool_name, "found": False}
        return {
            "name": meta.name, "found": True, "description": meta.description,
            "tags": meta.semantic_tags, "risk": meta.risk_level,
            "timeout_s": meta.timeout_s, "cost": meta.cost,
            "requires_network": meta.requires_network, "idempotent": meta.idempotent,
            "confidence": round(meta.confidence, 3),
            "success_rate": round(meta.success_rate, 3),
            "total_calls": meta.total_calls,
        }

    def get_all_tool_summaries(self) -> list[dict]:
        self._ensure_initialized()
        return [
            {"name": m.name, "description": m.description[:100], "risk": m.risk_level,
             "confidence": round(m.confidence, 3), "tags": m.semantic_tags[:5]}
            for m in sorted(self._tools.values(), key=lambda m: m.confidence, reverse=True)
        ]

    def record_outcome(self, tool_name: str, success: bool,
                       duration_ms: float = 0, error: str = "") -> None:
        self._ensure_initialized()
        meta = self._tools.get(tool_name)
        if not meta:
            return
        meta.total_calls += 1
        if success:
            meta.success_count += 1
        else:
            meta.last_error = error[:200]
        if duration_ms > 0:
            old_avg = meta.avg_duration_ms
            meta.avg_duration_ms = (old_avg * (meta.total_calls - 1) + duration_ms) / meta.total_calls
        meta.last_used = time.time()
        self._outcomes.append({
            "tool": tool_name, "success": success,
            "duration_ms": duration_ms, "error": error[:100], "ts": time.time(),
        })
        if len(self._outcomes) > 1000:
            self._outcomes = self._outcomes[-500:]


# ── Singleton ─────────────────────────────────────────────────

_instance: ToolSelector | None = None


def get_tool_selector() -> ToolSelector:
    global _instance
    if _instance is None:
        _instance = ToolSelector()
    return _instance
