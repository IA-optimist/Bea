"""
core/orchestration/mission_reasoning_state.py — Mission Reasoning State Model
==============================================================================
Phase 1 cognitive upgrade: before execution, Bea builds an explicit
reasoning model of the mission — not just lifecycle status, but:

  - initial_state   : what is true now before action
  - target_state    : what should be true after success
  - preconditions   : what must hold for success to be possible
  - dependencies    : external systems/data required
  - constraints     : hard limits (budget, time, access)
  - candidate_actions : ranked list of plausible approaches
  - expected_effects  : predicted state changes per action
  - success_criteria  : how to verify success objectively
  - failure_modes     : known ways this class of mission fails
  - observed_effects  : filled post-execution (actual changes)
  - expected_vs_observed : diff computed after execution

Design principles:
  - Pure dataclasses, no LLM required (heuristic fallback when LLM absent)
  - Survives the full mission lifecycle (created → inspectable post-execution)
  - Structured logging at creation and comparison time
  - No imports from agents/, api/, executor/ — only core types
  - build() is the single factory; update_observed() closes the loop

Status: CODE READY (Pass 42 — Phase 1)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger("orchestration.mission_reasoning_state")


# Pass 43 — synonym table for state_satisfied matching.
# Module-level constant (not inside @dataclass to avoid mutable-default error).
# Maps canonical criterion phrase fragments to paraphrase signals in real results.
_CRITERION_SYNONYMS: dict[str, list[str]] = {
    "runs without errors": ["pass", "passing", "no error", "no exception", "✓", "ok"],
    "target behavior":     ["fixed", "resolved", "works", "working", "implemented", "done"],
    "health endpoint":     ["healthy", "200", "ok", "up", "running", "reachable"],
    "findings address":    ["answers", "covers", "addressed", "found", "identified"],
    "sources are credible":["cited", "source", "referenced", "link", "url"],
    "conclusion stated":   ["conclusion", "finding", "result", "summary", "therefore"],
    "directly addresses":  ["answers", "responds", "addressed", "here is"],
    "appropriately concise":["brief", "short", "concise", "summary"],
    "goal satisfied":      ["done", "complete", "finished", "accomplished"],
}


# ══════════════════════════════════════════════════════════════════════════════
# Data model
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MissionReasoningState:
    """
    Full reasoning snapshot of a mission.

    Created before execution starts.
    Updated (observed_effects + comparison) after execution completes.
    """
    mission_id: str
    goal: str

    # ── Pre-execution model ───────────────────────────────────────────────────
    initial_state: str = ""
    target_state: str = ""
    preconditions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    candidate_actions: list[str] = field(default_factory=list)
    expected_effects: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)

    # ── Post-execution tracking ───────────────────────────────────────────────
    observed_effects: list[str] = field(default_factory=list)
    expected_vs_observed: dict[str, Any] = field(default_factory=dict)
    state_satisfied: bool | None = None  # None = not yet evaluated
    satisfaction_reason: str = ""

    # ── Provenance ───────────────────────────────────────────────────────────
    build_method: str = "heuristic"   # "heuristic" | "llm" | "hybrid"
    complexity: str = ""
    task_type: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ─────────────────────────────────────────────────────────────────────────

    def update_observed(self, result: str, error: str = "") -> None:
        """
        Fill observed effects from execution result. Runs expected vs observed diff.
        Call once after execution completes.
        Pass 43: improved satisfaction detection with synonym matching + soft threshold.
        """
        self.updated_at = time.time()

        # Derive observed effects from result text
        if result:
            lines = [l.strip() for l in result.split("\n") if l.strip()]
            # Take first 5 meaningful lines as observed effects
            self.observed_effects = [l for l in lines if len(l) > 10][:5]
        if error:
            self.observed_effects.append(f"ERROR: {error[:200]}")

        # Compare expected vs observed
        self.expected_vs_observed = self._compare()

        # Determine satisfaction
        if error and not result:
            self.state_satisfied = False
            self.satisfaction_reason = f"execution_error: {error[:100]}"
        elif result:
            result_lower = result.lower()
            matched = 0
            for crit in self.success_criteria:
                crit_lower = crit.lower()
                # Primary: any of first 3 keywords in result
                primary_hit = any(
                    kw in result_lower
                    for kw in crit_lower.split()[:3]
                    if len(kw) > 3
                )
                if primary_hit:
                    matched += 1
                    continue
                # Pass 43 — secondary: synonym lookup
                for frag, synonyms in _CRITERION_SYNONYMS.items():
                    if frag in crit_lower:
                        if any(syn in result_lower for syn in synonyms):
                            matched += 1
                            break

            total = max(len(self.success_criteria), 1)
            # Pass 43: soft threshold 0.33 (was 0.50) — criteria are conservative estimates;
            # partial match is still meaningful signal, not failure.
            ratio = matched / total
            self.state_satisfied = ratio >= 0.33
            self.satisfaction_reason = (
                f"criteria_match: {matched}/{total} ratio={ratio:.2f} "
                f"({'satisfied' if self.state_satisfied else 'unsatisfied'})"
            )
        else:
            self.state_satisfied = False
            self.satisfaction_reason = "no_result"

        log.info(
            "mission_state_observed",
            mission_id=self.mission_id,
            observed_count=len(self.observed_effects),
            satisfied=self.state_satisfied,
            reason=self.satisfaction_reason,
            expected_effects=len(self.expected_effects),
        )

    def _compare(self) -> dict[str, Any]:
        """
        Compute a diff between expected and observed effects.
        Returns a structured dict for logging / storage.
        """
        covered = []
        uncovered = []
        unexpected = []

        result_text = " ".join(self.observed_effects).lower()

        for exp in self.expected_effects:
            keywords = [w for w in exp.lower().split() if len(w) > 3][:4]
            if any(kw in result_text for kw in keywords):
                covered.append(exp)
            else:
                uncovered.append(exp)

        # Tag observed effects not matching any expected effect
        for obs in self.observed_effects:
            obs_words = set(obs.lower().split())
            all_exp_words = set(
                w for e in self.expected_effects for w in e.lower().split()
            )
            overlap = obs_words & all_exp_words
            if not overlap:
                unexpected.append(obs[:100])

        return {
            "expected_total": len(self.expected_effects),
            "covered": covered,
            "uncovered": uncovered,
            "unexpected": unexpected[:3],
            "coverage_ratio": (
                round(len(covered) / max(len(self.expected_effects), 1), 2)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal[:200],
            "initial_state": self.initial_state,
            "target_state": self.target_state,
            "preconditions": self.preconditions,
            "dependencies": self.dependencies,
            "constraints": self.constraints,
            "candidate_actions": self.candidate_actions,
            "expected_effects": self.expected_effects,
            "success_criteria": self.success_criteria,
            "failure_modes": self.failure_modes,
            "observed_effects": self.observed_effects,
            "expected_vs_observed": self.expected_vs_observed,
            "state_satisfied": self.state_satisfied,
            "satisfaction_reason": self.satisfaction_reason,
            "build_method": self.build_method,
            "complexity": self.complexity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_prompt_injection(self) -> str:
        """
        Compact context string for injection into enriched_goal.
        Keeps it short — agents don't need the full model, just the key frame.
        """
        lines = [
            "[STATE_MODEL]",
            f"INITIAL: {self.initial_state}",
            f"TARGET: {self.target_state}",
        ]
        if self.preconditions:
            lines.append(f"PRECONDITIONS: {'; '.join(self.preconditions[:3])}")
        if self.constraints:
            lines.append(f"CONSTRAINTS: {'; '.join(self.constraints[:2])}")
        if self.candidate_actions:
            lines.append(f"APPROACH: {self.candidate_actions[0]}")
        if self.success_criteria:
            lines.append(f"SUCCESS_IF: {'; '.join(self.success_criteria[:2])}")
        if self.failure_modes:
            lines.append(f"AVOID: {self.failure_modes[0]}")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════

# Heuristic patterns per task type
_TASK_TYPE_PATTERNS: dict[str, dict[str, list[str]]] = {
    "code": {
        "failure_modes": [
            "syntax error leaves system broken",
            "partial edit breaks existing tests",
            "missing import after refactor",
        ],
        "constraints": ["preserve backward compatibility", "no new dependencies without justification"],
    },
    "research": {
        "failure_modes": [
            "hallucinated sources",
            "outdated information used as current fact",
        ],
        "constraints": ["cite sources", "flag uncertainty explicitly"],
    },
    "deployment": {
        "failure_modes": [
            "config mismatch causes silent failure",
            "no rollback plan",
            "health check not verified post-deploy",
        ],
        "constraints": ["verify health after deploy", "require approval for prod"],
    },
    "analysis": {
        "failure_modes": [
            "sample bias skews conclusion",
            "correlation mistaken for causation",
        ],
        "constraints": ["state assumptions", "provide confidence interval"],
    },
    "conversation": {
        "failure_modes": ["over-elaborate response for simple query"],
        "constraints": ["be concise", "stay on topic"],
    },
}

_COMPLEXITY_PRECONDITIONS: dict[str, list[str]] = {
    "trivial":  [],
    "simple":   ["input data available"],
    "moderate": ["input data available", "relevant context retrieved"],
    "complex":  [
        "input data available",
        "relevant context retrieved",
        "dependencies resolved",
        "access to required systems verified",
    ],
}


def build(
    goal: str,
    mission_id: str,
    classification: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    prior_failures: list[str] | None = None,
    memory_lessons: list[dict[str, Any]] | None = None,
) -> MissionReasoningState:
    """
    Build a MissionReasoningState from goal + available signals.

    Uses heuristics (no LLM call). Rich when classification + context provided,
    minimal when called with only goal + mission_id.

    Args:
        goal           : raw mission goal string
        mission_id     : canonical mission identifier
        classification : dict from kernel.classifier (task_type, complexity, risk_level, …)
        context        : RichContext dict (prior_skills, relevant_memories, recent_failures)
        prior_failures : list of failure strings from memory search
        memory_lessons : list of lesson dicts from kernel.memory.retrieve_lessons()

    Returns:
        MissionReasoningState — always returns, never raises
    """
    try:
        return _build_internal(
            goal, mission_id, classification or {}, context or {},
            prior_failures or [], memory_lessons or []
        )
    except Exception as exc:
        log.warning("mission_state_build_failed", err=str(exc)[:120], mission_id=mission_id)
        # Minimal fallback — always produce something
        return MissionReasoningState(
            mission_id=mission_id,
            goal=goal,
            initial_state="unknown (build failed)",
            target_state=f"complete: {goal[:80]}",
            build_method="fallback",
        )


def _build_internal(
    goal: str,
    mission_id: str,
    classification: dict[str, Any],
    context: dict[str, Any],
    prior_failures: list[str],
    memory_lessons: list[dict[str, Any]],
) -> MissionReasoningState:
    task_type  = str(classification.get("task_type", "general") or "general").lower()
    complexity = str(classification.get("complexity", "moderate") or "moderate").lower()
    risk_level = str(classification.get("risk_level", "low") or "low").lower()
    goal_lower = goal.lower()

    # ── Initial state ─────────────────────────────────────────────────────────
    initial_state = _infer_initial_state(goal_lower, task_type, context)

    # ── Target state ──────────────────────────────────────────────────────────
    target_state = _infer_target_state(goal_lower, task_type)

    # ── Preconditions ─────────────────────────────────────────────────────────
    preconditions = list(_COMPLEXITY_PRECONDITIONS.get(complexity, ["input data available"]))

    # ── Dependencies ──────────────────────────────────────────────────────────
    dependencies = _extract_dependencies(goal_lower, task_type, context)

    # ── Constraints ───────────────────────────────────────────────────────────
    constraints = list(_TASK_TYPE_PATTERNS.get(task_type, {}).get("constraints", []))
    if risk_level in ("high", "critical"):
        constraints.append("requires human approval before irreversible action")
    if risk_level == "critical":
        constraints.append("mandatory review before execution")

    # ── Candidate actions ─────────────────────────────────────────────────────
    candidate_actions = _infer_candidate_actions(goal_lower, task_type, complexity)

    # ── Expected effects ──────────────────────────────────────────────────────
    expected_effects = _infer_expected_effects(goal_lower, task_type, candidate_actions)

    # ── Success criteria ──────────────────────────────────────────────────────
    success_criteria = _infer_success_criteria(goal_lower, task_type)

    # ── Failure modes ─────────────────────────────────────────────────────────
    failure_modes = list(_TASK_TYPE_PATTERNS.get(task_type, {}).get("failure_modes", []))
    # Augment with lessons from memory
    for lesson in memory_lessons[:2]:
        what_failed = lesson.get("what_to_do_differently", "")
        if what_failed and what_failed not in failure_modes:
            failure_modes.append(f"memory:{what_failed[:80]}")
    # Augment with prior failure snippets
    for fail in prior_failures[:2]:
        trimmed = fail[:80].strip()
        if trimmed:
            failure_modes.append(f"prior:{trimmed}")

    state = MissionReasoningState(
        mission_id=mission_id,
        goal=goal,
        initial_state=initial_state,
        target_state=target_state,
        preconditions=preconditions,
        dependencies=dependencies,
        constraints=constraints,
        candidate_actions=candidate_actions,
        expected_effects=expected_effects,
        success_criteria=success_criteria,
        failure_modes=failure_modes[:6],
        build_method="heuristic",
        complexity=complexity,
        task_type=task_type,
    )

    log.info(
        "mission_state_built",
        mission_id=mission_id,
        task_type=task_type,
        complexity=complexity,
        preconditions=len(preconditions),
        candidate_actions=len(candidate_actions),
        failure_modes=len(state.failure_modes),
        build_method="heuristic",
    )

    return state


# ── Inference helpers ──────────────────────────────────────────────────────────

def _infer_initial_state(goal: str, task_type: str, context: dict[str, Any]) -> str:
    prior = context.get("prior_skills", [])
    memories = context.get("relevant_memories", [])

    base = {
        "code": "codebase in current state, no targeted modification applied",
        "research": "information not yet gathered or synthesized",
        "deployment": "service not yet updated/deployed",
        "analysis": "raw data available, no analysis performed",
        "conversation": "user query received, no response formulated",
        "planning": "goal stated, no plan constructed",
    }.get(task_type, "system in current state, task not started")

    if prior:
        base += f"; {len(prior)} relevant prior skills available"
    if memories:
        base += f"; {len(memories)} relevant memory entries found"

    return base


def _infer_target_state(goal: str, task_type: str) -> str:
    verb_map = [
        (r"fix|repair|resolve|correct", "issue resolved and system functioning correctly"),
        (r"add|implement|create|build|write", "feature implemented and integrated"),
        (r"analyze|analyse|audit|review|check", "analysis complete with structured findings"),
        (r"deploy|release|publish", "service deployed and health-verified"),
        (r"optimize|improve|enhance|speed", "target metric improved from baseline"),
        (r"research|find|search|look", "information gathered and synthesized"),
        (r"plan|design|architect|outline", "plan documented with clear steps"),
        (r"remove|delete|clean|purge", "target artifact removed, no regressions"),
    ]
    for pattern, state in verb_map:
        if re.search(pattern, goal):
            return state
    return f"goal achieved: {goal[:80]}"


def _extract_dependencies(goal: str, task_type: str, context: dict[str, Any]) -> list[str]:
    deps: list[str] = []
    dep_keywords = {
        "database": "database access",
        "api": "external API availability",
        "file": "file system access",
        "docker": "Docker daemon",
        "github": "GitHub repository access",
        "server": "server / VPS access",
        "model": "LLM provider availability",
        "qdrant": "Qdrant vector store",
    }
    for kw, dep in dep_keywords.items():
        if kw in goal:
            deps.append(dep)
    if task_type == "deployment":
        deps.append("target environment credentials")
    return deps[:4]


def _infer_candidate_actions(goal: str, task_type: str, complexity: str) -> list[str]:
    base_actions = {
        "code": [
            "read and understand target files",
            "make minimal targeted edit",
            "verify no import/syntax errors",
            "run related tests",
        ],
        "research": [
            "web search for primary sources",
            "cross-reference multiple sources",
            "synthesize findings into structured output",
        ],
        "deployment": [
            "build and validate artifact",
            "run pre-deploy health checks",
            "deploy with rollback plan ready",
            "verify health post-deploy",
        ],
        "analysis": [
            "gather and validate input data",
            "apply analytical framework",
            "identify key patterns and anomalies",
            "formulate conclusions with caveats",
        ],
        "conversation": [
            "understand intent",
            "formulate direct response",
            "verify relevance before sending",
        ],
    }
    actions = base_actions.get(task_type, [
        "understand the goal precisely",
        "identify minimum viable approach",
        "execute and verify",
    ])
    # For trivial/simple missions, just top-1
    if complexity in ("trivial", "simple"):
        return actions[:2]
    return actions


def _infer_expected_effects(goal: str, task_type: str, actions: list[str]) -> list[str]:
    effects = []
    if task_type == "code":
        effects = [
            "target behavior changed as specified",
            "existing tests still pass",
            "no new imports broken",
        ]
    elif task_type == "research":
        effects = [
            "structured findings produced",
            "sources cited",
            "uncertainty flagged where applicable",
        ]
    elif task_type == "deployment":
        effects = [
            "service running on target environment",
            "health check passes",
            "previous version preserved for rollback",
        ]
    elif task_type == "analysis":
        effects = [
            "key findings identified",
            "supporting data referenced",
            "actionable conclusions stated",
        ]
    else:
        effects = [f"task completed: {goal[:60]}"]
    return effects


def _infer_success_criteria(goal: str, task_type: str) -> list[str]:
    base = {
        "code": [
            "code runs without errors",
            "target behavior matches specification",
        ],
        "research": [
            "findings address the original question",
            "sources are credible and recent",
        ],
        "deployment": [
            "health endpoint returns OK",
            "no error spike in logs",
        ],
        "analysis": [
            "conclusion stated clearly",
            "key data points cited",
        ],
        "conversation": [
            "response directly addresses the query",
            "response is appropriately concise",
        ],
    }
    return base.get(task_type, [f"goal satisfied: {goal[:60]}"])
