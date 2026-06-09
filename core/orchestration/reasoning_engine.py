"""
core/orchestration/reasoning_engine.py — Practical Reasoning Engine.

The intelligence upgrade: before acting, Bea reasons about WHAT matters.

This module provides:
1. Problem Framing — identify the real task, bottleneck, success criteria
2. Prioritization — rank issues by leverage, not by order encountered
3. Output Shape Selection — choose the right response format for the task
4. Self-Critique — detect weak/generic answers and improve them
5. Repo-Aware Reasoning — understand codebase context before proposing changes

All functions work with or without LLM. When LLM is available, reasoning
is richer. When not, heuristic fallback ensures consistent operation.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum

import structlog

log = structlog.get_logger("reasoning_engine")


# ═══════════════════════════════════════════════════════════════
# PHASE 1 — PROBLEM FRAMING
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProblemFrame:
    """Structured understanding of what the task actually requires."""
    real_problem: str          # The actual problem (may differ from stated goal)
    true_objective: str        # What success actually looks like
    likely_bottleneck: str     # Most probable blocker
    essential: list[str]       # Must-do items
    optional: list[str]        # Nice-to-have but not required
    do_not_do: list[str]       # Explicitly excluded actions
    smallest_next_move: str    # Minimum viable progress
    complexity_class: str      # "direct_answer", "small_fix", "multi_step", "investigation"
    confidence: float = 0.7

    def to_dict(self) -> dict:
        return {
            "real_problem": self.real_problem,
            "true_objective": self.true_objective,
            "likely_bottleneck": self.likely_bottleneck,
            "essential": self.essential,
            "optional": self.optional,
            "do_not_do": self.do_not_do,
            "smallest_next_move": self.smallest_next_move,
            "complexity_class": self.complexity_class,
            "confidence": self.confidence,
        }

    def to_prompt_context(self) -> str:
        """Concise prompt injection for downstream agents."""
        lines = [
            f"PROBLEM: {self.real_problem}",
            f"OBJECTIVE: {self.true_objective}",
            f"BOTTLENECK: {self.likely_bottleneck}",
            f"NEXT MOVE: {self.smallest_next_move}",
        ]
        if self.do_not_do:
            lines.append(f"DO NOT: {'; '.join(self.do_not_do)}")
        return "\n".join(lines)


def frame_problem(
    goal: str,
    classification: dict | None = None,
    prior_failures: list[str] | None = None,
    repo_context: dict | None = None,
) -> ProblemFrame:
    """
    Analyze a goal to extract the real problem, bottleneck, and next move.
    Uses LLM when available, heuristic fallback otherwise.
    """
    goal_lower = goal.lower().strip()
    goal_words = set(re.findall(r"[a-z]{3,}", goal_lower))

    # ── Complexity classification ─────────────────────
    complexity = _classify_complexity(goal_lower, goal_words)

    # ── Bottleneck detection ──────────────────────────
    bottleneck = _detect_bottleneck(goal_lower, classification, prior_failures)

    # ── Essential vs optional decomposition ───────────
    essential, optional, do_not = _decompose_requirements(goal_lower, goal_words)

    # ── Smallest next move ────────────────────────────
    next_move = _smallest_next_move(goal_lower, complexity, bottleneck)

    # ── Real problem extraction ───────────────────────
    real_problem = _extract_real_problem(goal, goal_lower, goal_words)

    # ── True objective ────────────────────────────────
    true_objective = _extract_true_objective(goal_lower, classification)

    # ── LLM enhancement (optional) ────────────────────
    frame = ProblemFrame(
        real_problem=real_problem,
        true_objective=true_objective,
        likely_bottleneck=bottleneck,
        essential=essential,
        optional=optional,
        do_not_do=do_not,
        smallest_next_move=next_move,
        complexity_class=complexity,
    )

    frame = _try_llm_enhance_frame(frame, goal)
    return frame


def _classify_complexity(goal: str, words: set) -> str:
    """Determine if this needs a direct answer, small fix, investigation, or multi-step plan."""

    # ── Gate 0 : fix/bug patterns détectés EN PREMIER (priorité absolue) ─────
    # Ces patterns doivent être testés avant le gate de longueur pour que
    # "fix this bug" (12 chars) ne soit pas capturé comme direct_answer.
    # NOTE (2026-04-04): réordonné — anciennement après le gate de longueur.
    _fix_patterns_early = [
        r"\bfix\b", r"\bbug\b", r"\berror\b", r"\bcrash\b",
        r"\bbroken\b", r"\bnot work", r"\b404\b", r"\b401\b",
        r"\bcorrige\b", r"\berreur\b", r"\bplante\b",
        r"\bne\s+fonctionne\s+pas\b", r"\bne\s+marche\s+pas\b",
    ]
    if (any(re.search(p, goal, re.IGNORECASE) for p in _fix_patterns_early)
            and len(goal) < 200):
        return "small_fix"

    # ── Gate 1 : messages courts / salutations (FR + EN) ──────────────────
    # Un message ≤ 30 chars sans verbe d'action fort (déjà testé ci-dessus)
    # est forcément une question directe ou une salutation — jamais un patch.
    # NOTE (2026-04-04): fix du bug "shape=patch pour bonjour presente toi".
    # Tous les patterns ci-dessous étaient EN-only → les messages FR tombaient
    # en fallback "small_fix" → select_output_shape retournait PATCH.
    if len(goal) <= 30:
        return "direct_answer"

    # Salutations et questions simples FR + EN (indépendant de la longueur)
    direct_patterns_fr_en = [
        # English originals
        r"^what (is|are|was|were)\b", r"^how (do|does|can|to)\b",
        r"^explain\b", r"^define\b", r"^list\b", r"^show\b",
        r"^tell me\b", r"^describe\b",
        # French greetings / simple questions
        r"^(bonjour|salut|hello|coucou|hi|hey)\b",
        r"^(pr[eé]sente[- ]toi|qui\s+es[- ]tu|c.est\s+quoi|qu.est[- ]ce)\b",
        r"^(explique|dis[- ]moi|d[eé]cris|montre|liste|d[eé]finis)\b",
        r"^(qu.est[- ]ce\s+que|comment\s+(tu|[çc]a)\s+fonctionne)\b",
        r"^(c.est\s+qui|tu\s+(es|fais|peux)|que\s+(fais|peut))\b",
    ]
    for p in direct_patterns_fr_en:
        if re.search(p, goal, re.IGNORECASE):
            return "direct_answer"

    # Investigation indicators (EN + FR)
    investigate_patterns = [
        r"\banalyze\b", r"\binvestigate\b", r"\bdiagnose\b",
        r"\bwhy\b", r"\bread.*code\b", r"\baudit\b", r"\breview\b",
        # FR
        r"\banalyse\b", r"\banalyser\b", r"\bpourquoi\b",
        r"\bdiagnostiquer?\b", r"\binspecte\b", r"\bv[eé]rifie\b",
    ]
    if any(re.search(p, goal, re.IGNORECASE) for p in investigate_patterns):
        return "investigation"

    # Multi-step: long goals, 1+ strong action verbs in a substantive message, or explicit structure
    _ACTION_VERBS = {
        "build", "create", "implement", "design", "deploy", "test",
        "refactor", "migrate", "upgrade", "integrate", "generate",
        "write", "develop", "setup", "configure",
        # FR equivalents
        "construis", "cree", "implemente", "deploie", "developpe",
        "migre", "integre", "ecris", "genere", "crees",
    }
    verb_count = sum(1 for w in words if w in _ACTION_VERBS)
    # 1 action verb in a message > 30 chars already warrants multi_step
    if verb_count >= 1 or len(goal) > 300:
        return "multi_step"

    # ── Bash/shell execution gate (FR + EN) — doit rester juste avant le fallback ──
    # "Executer la commande bash", "run this bash command", "lancer le script"
    # → small_fix (PATCH shape) pour inclure forge-builder dans le plan d'agents.
    _bash_exec_patterns = [
        r"\bexecut[ei]?r?\s+(la\s+)?(commande|bash|shell|script|cmd)\b",
        r"\blance[rz]?\s+(la\s+)?(commande|bash|shell|script)\b",
        r"\brun\s+(bash|shell|this\s+command|cmd|script)\b",
        r"\bexecut[ei]?r?\s+.*\b(echo|python[23]?|npm|git|pip|docker)\b",
    ]
    if any(re.search(p, goal, re.IGNORECASE) for p in _bash_exec_patterns):
        return "small_fix"

    # ── Default changed: "direct_answer" is safer than "small_fix" ──────────
    # The old default "small_fix" caused select_output_shape to return PATCH
    # for ANY unrecognized input (especially French). A direct_answer is always
    # safe to return; the agent can escalate if needed.
    return "direct_answer"


def _detect_bottleneck(
    goal: str,
    classification: dict | None,
    prior_failures: list[str] | None,
) -> str:
    """Identify the most likely blocker for this task."""
    # Prior failures are the strongest signal
    if prior_failures:
        return f"Similar tasks have failed before: {prior_failures[0][:80]}"

    # Classification-based bottleneck
    if classification:
        risk = classification.get("risk_level", "low")
        if risk in ("high", "critical"):
            return "High-risk task requires careful validation before execution"
        complexity = classification.get("complexity", "simple")
        if complexity == "complex":
            return "Complex task — needs decomposition before execution"

    # Goal-based bottleneck detection
    if re.search(r"\bexternal\b|\bapi\b|\bthird[- ]party", goal):
        return "External dependency — availability/auth may block"
    if re.search(r"\bpermission\b|\baccess\b|\bauth", goal):
        return "Access/permission may need configuration"
    if re.search(r"\blegacy\b|\bold\b|\bdeprecated", goal):
        return "Legacy code — side effects and undocumented behavior"
    if re.search(r"\bperformance\b|\bslow\b|\boptimiz", goal):
        return "Need measurements before optimization"

    return "No obvious bottleneck — proceed carefully"


def _decompose_requirements(goal: str, words: set) -> tuple[list[str], list[str], list[str]]:
    """Split task into essential, optional, and do-not-do."""
    essential = []
    optional = []
    do_not = []

    # Sentence-level decomposition
    sentences = re.split(r"[.;]\s+|\n", goal)
    for s in sentences:
        s = s.strip()
        if not s or len(s) < 5:
            continue
        sl = s.lower()

        # Explicit negation
        if re.search(r"\bdo not\b|\bdon'?t\b|\bavoid\b|\bnot\b.*\bshould\b|\bnever\b", sl):
            do_not.append(s)
        # Optional markers
        elif re.search(r"\boptional\b|\bif possible\b|\bnice to have\b|\bbonus\b|\bideal\b", sl):
            optional.append(s)
        # Everything else is essential
        else:
            essential.append(s)

    # If no explicit decomposition, the whole goal is essential
    if not essential and not optional:
        essential = [goal[:200]]

    # Always add: don't break existing functionality
    if not any("break" in d.lower() for d in do_not):
        do_not.append("Don't break existing functionality")

    return essential[:5], optional[:3], do_not[:3]


def _smallest_next_move(goal: str, complexity: str, bottleneck: str) -> str:
    """Determine the minimum viable next action."""
    if complexity == "direct_answer":
        return "Answer the question directly"
    if complexity == "small_fix":
        return "Locate the bug, fix it, verify"
    if "failed before" in bottleneck:
        return "Understand why previous attempt failed before retrying"
    if "external" in bottleneck.lower():
        return "Verify external service availability first"
    if complexity == "investigation":
        return "Read relevant code/data before forming conclusions"
    return "Identify the single most impactful change and implement it"


def _extract_real_problem(goal: str, goal_lower: str, words: set) -> str:
    """Extract the core problem, stripping noise."""
    # Remove meta-instructions (formatting requests, etc.)
    noise_patterns = [
        r"please\s+", r"can you\s+", r"i need you to\s+",
        r"i want you to\s+", r"make sure to\s+",
    ]
    cleaned = goal_lower
    for p in noise_patterns:
        cleaned = re.sub(p, "", cleaned)
    cleaned = cleaned.strip()

    # First sentence is usually the core problem
    first_sentence = re.split(r"[.;]\s+|\n", cleaned)[0].strip()
    if len(first_sentence) > 10:
        return first_sentence[:200]
    return cleaned[:200]


def _extract_true_objective(goal_lower: str, classification: dict | None) -> str:
    """What does success actually look like?"""
    if classification:
        task_type = classification.get("task_type", "")
        if task_type == "code":
            return "Working code that solves the stated problem without regressions"
        if task_type == "research":
            return "Actionable findings with specific recommendations"
        if task_type == "debug":
            return "Root cause identified and fixed, verified working"
        if task_type == "deploy":
            return "Service running and accessible with verified health"

    # Fallback: infer from keywords
    if re.search(r"\bfix\b|\bbug\b|\berror\b", goal_lower):
        return "Bug fixed and verified — no regressions"
    if re.search(r"\bbuild\b|\bcreate\b|\bimplement\b", goal_lower):
        return "Working implementation that meets stated requirements"
    if re.search(r"\banalyze\b|\bresearch\b|\binvestigate\b", goal_lower):
        return "Clear analysis with actionable conclusions"
    return "Task completed with verifiable results"


def _try_llm_enhance_frame(frame: ProblemFrame, goal: str) -> ProblemFrame:
    """Optionally use LLM to improve problem framing. Fail-open."""
    try:
        from core.llm_factory import get_llm
        import os
        if not os.getenv("OPENROUTER_API_KEY"):
            return frame

        llm = get_llm(role="fast")
        prompt = (
            "You are a reasoning pre-pass. Given this task, answer in 4 lines max:\n"
            f"TASK: {goal[:500]}\n\n"
            "1. REAL PROBLEM: (what actually needs solving)\n"
            "2. BOTTLENECK: (most likely blocker)\n"
            "3. NEXT MOVE: (smallest useful action)\n"
            "4. DO NOT: (what to avoid)\n"
            "Be concise. No fluff."
        )
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)

        # Parse structured response
        for line in text.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("1.") or line.upper().startswith("REAL PROBLEM"):
                val = re.sub(r"^[\d.]+\s*\.?\s*(REAL PROBLEM:?\s*)?", "", line, flags=re.I).strip()
                if val:
                    frame.real_problem = val[:200]
            elif line.upper().startswith("2.") or line.upper().startswith("BOTTLENECK"):
                val = re.sub(r"^[\d.]+\s*\.?\s*(BOTTLENECK:?\s*)?", "", line, flags=re.I).strip()
                if val:
                    frame.likely_bottleneck = val[:200]
            elif line.upper().startswith("3.") or line.upper().startswith("NEXT MOVE"):
                val = re.sub(r"^[\d.]+\s*\.?\s*(NEXT MOVE:?\s*)?", "", line, flags=re.I).strip()
                if val:
                    frame.smallest_next_move = val[:200]
            elif line.upper().startswith("4.") or line.upper().startswith("DO NOT"):
                val = re.sub(r"^[\d.]+\s*\.?\s*(DO NOT:?\s*)?", "", line, flags=re.I).strip()
                if val:
                    frame.do_not_do = [val[:200]]

        frame.confidence = 0.85  # LLM-enhanced
        log.info("problem_frame_llm_enhanced", real_problem=frame.real_problem[:60])
    except Exception as e:
        log.debug("problem_frame_llm_skipped", err=str(e)[:60])
    return frame


# ═══════════════════════════════════════════════════════════════
# PHASE 2 — PRIORITIZATION
# ═══════════════════════════════════════════════════════════════

class Priority(str, Enum):
    CRITICAL_BLOCKER = "critical_blocker"
    IMPORTANT = "important"
    USEFUL_LATER = "useful_later"
    NOISE = "noise"


@dataclass
class PrioritizedIssue:
    description: str
    priority: Priority
    leverage: float      # 0.0-1.0 — how much fixing this unlocks
    reason: str

    def to_dict(self) -> dict:
        return {
            "description": self.description[:200],
            "priority": self.priority.value,
            "leverage": self.leverage,
            "reason": self.reason,
        }


def prioritize_issues(
    issues: list[str],
    goal: str = "",
    context: dict | None = None,
) -> list[PrioritizedIssue]:
    """
    Rank issues by real leverage, not by order encountered.
    Returns sorted list (highest leverage first).
    """
    if not issues:
        return []

    goal_lower = goal.lower()
    prioritized = []

    for issue in issues:
        issue_lower = issue.lower()

        # ── Priority classification ───────────────────
        priority, leverage, reason = _classify_issue(issue_lower, goal_lower)
        prioritized.append(PrioritizedIssue(
            description=issue,
            priority=priority,
            leverage=leverage,
            reason=reason,
        ))

    # Sort by leverage descending
    prioritized.sort(key=lambda x: x.leverage, reverse=True)
    return prioritized


def _classify_issue(issue: str, goal: str) -> tuple[Priority, float, str]:
    """Classify a single issue by priority and leverage."""
    # Critical blockers — prevent all progress
    blocker_signals = [
        (r"\bcrash\b|\bfatal\b|\bcannot start\b", 0.95, "System crash/fatal — blocks everything"),
        (r"\bauth.*fail\b|\b401\b|\b403\b|\bunauthorized\b", 0.90, "Auth failure — blocks all operations"),
        (r"\bdata loss\b|\bcorrupt\b", 0.95, "Data integrity — immediate attention required"),
        (r"\bsecurity\b.*\bvuln\b|\bexposed\b.*\bsecret\b", 0.95, "Security vulnerability — immediate"),
        (r"\bimport error\b|\bmodule not found\b", 0.85, "Import failure — blocks functionality"),
    ]
    for pattern, lev, reason in blocker_signals:
        if re.search(pattern, issue):
            return Priority.CRITICAL_BLOCKER, lev, reason

    # Important — affects quality but doesn't block
    important_signals = [
        (r"\bslow\b|\bperformance\b|\btimeout\b", 0.6, "Performance issue — affects user experience"),
        (r"\btest.*fail\b|\bregression\b", 0.7, "Test failure — quality degradation"),
        (r"\bduplicate\b|\bredundant\b", 0.4, "Duplication — maintenance overhead"),
        (r"\bdeprecated\b|\blegacy\b", 0.35, "Legacy code — future maintenance risk"),
        (r"\bmissing.*test\b|\bno test\b", 0.45, "Missing tests — safety risk"),
    ]
    for pattern, lev, reason in important_signals:
        if re.search(pattern, issue):
            return Priority.IMPORTANT, lev, reason

    # Goal relevance — boost issues that relate to the current goal
    goal_words = set(re.findall(r"[a-z]{3,}", goal))
    issue_words = set(re.findall(r"[a-z]{3,}", issue))
    overlap = len(goal_words & issue_words) / max(len(goal_words), 1)
    if overlap > 0.3:
        return Priority.IMPORTANT, 0.5 + overlap * 0.3, f"Directly related to current goal (overlap={overlap:.0%})"

    # Noise detection
    noise_signals = [
        r"\bstyle\b|\bformat\b|\bwhitespace\b",
        r"\bcomment\b|\bdocstring\b.*missing\b",
        r"\btype hint\b|\bannotation\b",
        r"\bnaming\b|\brename\b",
    ]
    for pattern in noise_signals:
        if re.search(pattern, issue):
            return Priority.NOISE, 0.1, "Style/cosmetic — not blocking"

    return Priority.USEFUL_LATER, 0.3, "No strong signal — useful but not urgent"


# ═══════════════════════════════════════════════════════════════
# PHASE 3 — OUTPUT SHAPE SELECTION
# ═══════════════════════════════════════════════════════════════

class OutputShape(str, Enum):
    DIRECT_ANSWER = "direct_answer"     # Short factual response
    DIAGNOSIS = "diagnosis"             # Root cause + fix
    PLAN = "plan"                       # Multi-step execution plan
    PATCH = "patch"                     # Code change
    REPORT = "report"                   # Analysis/research report
    WARNING = "warning"                 # Risk alert, don't proceed


def select_output_shape(
    goal: str,
    frame: ProblemFrame | None = None,
    classification: dict | None = None,
) -> OutputShape:
    """Choose the right response format for the task."""
    goal_lower = goal.lower()
    complexity = frame.complexity_class if frame else "multi_step"

    # Direct questions → direct answers
    if complexity == "direct_answer":
        return OutputShape.DIRECT_ANSWER

    # Fix/bug → diagnosis or patch
    if complexity == "small_fix":
        if re.search(r"\bwhy\b|\bdiagnose\b|\bexplain\b", goal_lower):
            return OutputShape.DIAGNOSIS
        return OutputShape.PATCH

    # Risk signals → warning
    if frame and any("security" in d.lower() or "data loss" in d.lower() for d in frame.do_not_do):
        return OutputShape.WARNING

    # Research/analysis → report (EN + FR)
    if re.search(
        r"\banalyze\b|\bresearch\b|\bcompare\b|\baudit\b|\breview\b"
        r"|\banalyse\b|\banalyser\b|\brecherche\b|\bcompare\b|\br[eé]sume\b"
        r"|\bsynth[eé]tise\b|\b[eé]value\b|\bexplore\b",
        goal_lower,
    ):
        return OutputShape.REPORT

    # Build/implement → plan or patch (EN + FR)
    if re.search(
        r"\bbuild\b|\bcreate\b|\bimplement\b|\bdesign\b"
        r"|\bcr[eé]e\b|\bconstruis\b|\bimpl[eé]mente\b|\bd[eé]veloppe\b"
        r"|\bmet[sz]\s+en\s+place\b|\br[eé]alise\b",
        goal_lower,
    ):
        if complexity == "multi_step":
            return OutputShape.PLAN
        return OutputShape.PATCH

    # Direct answer — never return PATCH for greetings/short questions
    # NOTE (2026-04-04): added guard so direct_answer complexity always → DIRECT_ANSWER
    # even if the goal somehow slipped past the complexity gate above.
    if complexity == "direct_answer":
        return OutputShape.DIRECT_ANSWER

    # Investigation → diagnosis
    if complexity == "investigation":
        return OutputShape.DIAGNOSIS

    return OutputShape.PLAN  # Default: structured plan


# ═══════════════════════════════════════════════════════════════
# PHASE 4 — SELF-CRITIQUE
# ═══════════════════════════════════════════════════════════════

@dataclass
class CritiqueResult:
    """Result of self-critique analysis."""
    is_weak: bool
    weaknesses: list[str]
    improvement_suggestion: str
    specificity_score: float    # 0.0 (generic) to 1.0 (specific)
    completeness_score: float   # 0.0 (incomplete) to 1.0 (complete)
    usability_score: float      # 0.0 (unusable) to 1.0 (immediately usable)
    overall_score: float

    def to_dict(self) -> dict:
        return {
            "is_weak": self.is_weak,
            "weaknesses": self.weaknesses,
            "improvement_suggestion": self.improvement_suggestion,
            "specificity": self.specificity_score,
            "completeness": self.completeness_score,
            "usability": self.usability_score,
            "overall": self.overall_score,
        }


def critique_output(
    goal: str,
    output: str,
    output_shape: OutputShape | None = None,
    frame: ProblemFrame | None = None,
) -> CritiqueResult:
    """
    Before finalizing, check:
    - Did I actually solve the problem?
    - Is this answer too generic?
    - Is this overcomplicated?
    - Did I miss the most important issue?
    - Is this usable right now?
    """
    weaknesses = []
    if not output or not output.strip():
        return CritiqueResult(
            is_weak=True, weaknesses=["Empty output"],
            improvement_suggestion="Produce any output",
            specificity_score=0.0, completeness_score=0.0,
            usability_score=0.0, overall_score=0.0,
        )

    output_lower = output.lower()
    goal.lower()

    # ── 1. Generic detection ──────────────────────────
    specificity = _score_specificity(output, goal)
    if specificity < 0.3:
        weaknesses.append("Output is too generic — doesn't address the specific task")

    # ── 2. Completeness check ─────────────────────────
    completeness = _score_completeness(output, goal, frame)
    if completeness < 0.4:
        weaknesses.append("Output doesn't cover key aspects of the task")

    # ── 3. Usability check ────────────────────────────
    usability = _score_usability(output, output_shape)
    if usability < 0.4:
        weaknesses.append("Output is not immediately actionable")

    # ── 4. Over-complexity check ──────────────────────
    if _is_overcomplicated(output, goal):
        weaknesses.append("Output is overcomplicated for the task complexity")
        usability -= 0.15

    # ── 5. Missed core issue ──────────────────────────
    if frame and frame.likely_bottleneck:
        bottleneck_words = set(re.findall(r"[a-z]{3,}", frame.likely_bottleneck.lower()))
        output_words = set(re.findall(r"[a-z]{3,}", output_lower))
        if bottleneck_words and not (bottleneck_words & output_words):
            weaknesses.append(f"Doesn't address likely bottleneck: {frame.likely_bottleneck[:80]}")
            completeness -= 0.2

    # ── 6. Error message masquerading as result ───────
    error_indicators = sum(1 for p in [
        r"traceback", r"error:", r"exception:", r"failed to",
        r"unable to", r"internal server error",
    ] if re.search(p, output_lower))
    if error_indicators >= 2:
        weaknesses.append("Output contains error messages instead of results")
        usability -= 0.3

    # Clamp scores
    specificity = max(0.0, min(1.0, specificity))
    completeness = max(0.0, min(1.0, completeness))
    usability = max(0.0, min(1.0, usability))
    overall = round(0.3 * specificity + 0.35 * completeness + 0.35 * usability, 3)

    is_weak = overall < 0.5 or len(weaknesses) >= 2

    # Improvement suggestion
    suggestion = ""
    if weaknesses:
        suggestion = _generate_improvement_suggestion(weaknesses, goal, frame)

    return CritiqueResult(
        is_weak=is_weak,
        weaknesses=weaknesses,
        improvement_suggestion=suggestion,
        specificity_score=round(specificity, 3),
        completeness_score=round(completeness, 3),
        usability_score=round(usability, 3),
        overall_score=overall,
    )


def _score_specificity(output: str, goal: str) -> float:
    """How specific is the output to this particular task?"""
    # Keyword overlap with goal
    goal_words = set(re.findall(r"[a-z]{3,}", goal.lower())) - _STOP_WORDS
    output_words = set(re.findall(r"[a-z]{3,}", output.lower())) - _STOP_WORDS

    if not goal_words:
        return 0.5

    overlap = len(goal_words & output_words) / len(goal_words)

    # Penalize filler/generic phrases
    generic_patterns = [
        r"in general", r"typically", r"it depends",
        r"there are many ways", r"it is important to",
        r"best practices suggest", r"as mentioned",
    ]
    generic_count = sum(1 for p in generic_patterns if re.search(p, output.lower()))
    specificity = overlap - (generic_count * 0.1)

    # Bonus for concrete artifacts (code, filenames, numbers)
    if re.search(r"```", output):
        specificity += 0.15
    if re.search(r"\b\w+\.(py|js|ts|dart|html|json|yaml|md)\b", output):
        specificity += 0.1
    if re.search(r"\d+\.\d+", output):
        specificity += 0.05

    return specificity


def _score_completeness(output: str, goal: str, frame: ProblemFrame | None) -> float:
    """Does the output cover all essential aspects?"""
    if not frame:
        # Fallback: simple length heuristic
        return min(1.0, len(output.strip()) / 500)

    essential = frame.essential
    if not essential:
        return 0.6  # Neutral if no decomposition

    output_lower = output.lower()
    covered = 0
    for req in essential:
        req_words = set(re.findall(r"[a-z]{3,}", req.lower())) - _STOP_WORDS
        output_words = set(re.findall(r"[a-z]{3,}", output_lower))
        if req_words and len(req_words & output_words) / len(req_words) > 0.3:
            covered += 1

    return covered / max(len(essential), 1)


def _score_usability(output: str, shape: OutputShape | None) -> float:
    """Is the output immediately actionable?"""
    score = 0.5

    # Code outputs should have code blocks
    if shape == OutputShape.PATCH:
        if "```" in output:
            score += 0.3
        else:
            score -= 0.2
        # Should mention file path
        if re.search(r"\b\w+\.(py|js|dart|html)\b", output):
            score += 0.1

    # Direct answers should be concise
    elif shape == OutputShape.DIRECT_ANSWER:
        if len(output.strip()) < 500:
            score += 0.2
        if len(output.strip()) > 2000:
            score -= 0.2

    # Reports should have structure
    elif shape == OutputShape.REPORT:
        headers = len(re.findall(r"^#+\s|^\*\*[^*]+\*\*", output, re.M))
        if headers >= 2:
            score += 0.2
        bullets = len(re.findall(r"^[-*]\s", output, re.M))
        if bullets >= 3:
            score += 0.1

    # Plans should have numbered steps
    elif shape == OutputShape.PLAN:
        steps = len(re.findall(r"^\d+[.)]\s", output, re.M))
        if steps >= 2:
            score += 0.3

    return score


def _is_overcomplicated(output: str, goal: str) -> bool:
    """Is the output more complex than the task requires?"""
    goal_len = len(goal.strip())
    output_len = len(output.strip())

    # Short task, huge output → likely overcomplicated
    if goal_len < 100 and output_len > 3000:
        return True

    # Too many headers for a simple task
    headers = len(re.findall(r"^#+\s", output, re.M))
    if goal_len < 150 and headers > 5:
        return True

    return False


def _generate_improvement_suggestion(weaknesses: list[str], goal: str, frame: ProblemFrame | None) -> str:
    """Generate a focused improvement suggestion."""
    if not weaknesses:
        return ""

    # Pick the most impactful weakness
    w = weaknesses[0]
    if "generic" in w.lower():
        return f"Add specific details: file names, function names, concrete values from '{goal[:60]}...'"
    if "bottleneck" in w.lower():
        bn = frame.likely_bottleneck if frame else ""
        return f"Address the bottleneck first: {bn[:80]}"
    if "incomplete" in w.lower() or "cover" in w.lower():
        return "Cover all essential requirements listed in the task"
    if "actionable" in w.lower():
        return "Include concrete next steps or code that can be executed immediately"
    if "overcomplicated" in w.lower():
        return "Simplify: give the direct answer instead of a framework"
    if "error" in w.lower():
        return "Investigate and fix the error before presenting results"
    return f"Address: {w[:80]}"


# ═══════════════════════════════════════════════════════════════
# PHASE 5 — REPO-AWARE REASONING
# ═══════════════════════════════════════════════════════════════

@dataclass
class RepoAwareness:
    """Understanding of codebase context for a proposed change."""
    target_layer: str           # kernel, core, api, executor, business, etc.
    canonical_module: str       # The right file to modify
    related_modules: list[str]  # Files likely affected
    existing_patterns: list[str]  # Patterns to follow
    anti_patterns: list[str]    # Things to avoid
    risk_level: str             # low, medium, high

    def to_dict(self) -> dict:
        return {
            "target_layer": self.target_layer,
            "canonical_module": self.canonical_module,
            "related_modules": self.related_modules[:5],
            "existing_patterns": self.existing_patterns[:3],
            "anti_patterns": self.anti_patterns[:3],
            "risk_level": self.risk_level,
        }


# Layer classification for BeaMax
_LAYER_MAP = {
    "kernel/": "kernel",
    "core/orchestration/": "orchestration",
    "core/planning/": "planning",
    "core/execution/": "execution",
    "core/model_intelligence/": "model_intelligence",
    "core/capability_routing/": "routing",
    "core/security/": "security",
    "core/self_improvement/": "self_improvement",
    "core/": "core",
    "api/routes/": "api_routes",
    "api/": "api",
    "executor/": "executor",
    "business/": "business",
    "agents/": "agents",
    "memory/": "memory",
    "static/": "frontend",
    "tests/": "test",
}


def assess_repo_context(
    goal: str,
    proposed_files: list[str] | None = None,
) -> RepoAwareness:
    """Understand codebase context before proposing changes."""
    goal_lower = goal.lower()

    # Identify target layer from goal keywords
    layer = "core"
    canonical = ""
    related = []
    patterns = []
    anti_patterns = [
        "Don't create parallel abstractions for existing functionality",
        "Don't bypass the existing fail-open pattern",
    ]

    # Keyword → layer mapping
    layer_keywords = {
        "kernel": ["kernel", "contract", "event type", "capability registry"],
        "orchestration": ["orchestrator", "mission lifecycle", "routing decision"],
        "planning": ["plan", "step", "playbook", "execution plan"],
        "execution": ["artifact", "build pipeline", "deploy"],
        "api": ["endpoint", "route", "api", "rest"],
        "memory": ["memory", "rag", "vector", "embedding"],
        "security": ["vault", "secret", "auth", "rbac"],
        "frontend": ["ui", "dashboard", "screen", "html", "flutter"],
    }

    for lyr, keywords in layer_keywords.items():
        if any(k in goal_lower for k in keywords):
            layer = lyr
            break

    # Pattern detection from layer
    if layer in ("core", "orchestration", "planning", "execution"):
        patterns.append("All operations fail-open (try/except with logging)")
        patterns.append("Use structlog for logging")
        patterns.append("Dataclasses for typed structures")
    if layer == "kernel":
        patterns.append("Pure contracts — no external dependencies")
        anti_patterns.append("Don't import from core/ in kernel/")
    if layer == "api":
        patterns.append("FastAPI router with auth dependency")
        patterns.append("Return {ok: True, data: ...} envelope")

    # Risk assessment
    risk = "low"
    if proposed_files:
        for f in proposed_files:
            for prefix, lyr in _LAYER_MAP.items():
                if f.startswith(prefix) and lyr in ("kernel", "security", "orchestration"):
                    risk = "high"
                    break

    if "delete" in goal_lower or "remove" in goal_lower or "rewrite" in goal_lower:
        risk = "high"

    return RepoAwareness(
        target_layer=layer,
        canonical_module=canonical,
        related_modules=related,
        existing_patterns=patterns,
        anti_patterns=anti_patterns,
        risk_level=risk,
    )


# ═══════════════════════════════════════════════════════════════
# PHASE 6 — JUDGMENT SIGNALS (tracking)
# ═══════════════════════════════════════════════════════════════

@dataclass
class JudgmentSignals:
    """Track signals of good/bad judgment across missions."""
    unnecessary_steps: int = 0
    root_cause_accuracy: float = 0.0
    first_choice_correct: bool = True
    retries_needed: int = 0
    output_usefulness: float = 0.0
    duplicate_work: bool = False
    overcomplicated: bool = False

    def to_dict(self) -> dict:
        return {
            "unnecessary_steps": self.unnecessary_steps,
            "root_cause_accuracy": self.root_cause_accuracy,
            "first_choice_correct": self.first_choice_correct,
            "retries_needed": self.retries_needed,
            "output_usefulness": self.output_usefulness,
            "duplicate_work": self.duplicate_work,
            "overcomplicated": self.overcomplicated,
        }


def compute_judgment_signals(
    frame: ProblemFrame,
    critique: CritiqueResult,
    retries: int = 0,
    duration_ms: int = 0,
) -> JudgmentSignals:
    """Compute judgment quality signals from mission execution."""
    return JudgmentSignals(
        unnecessary_steps=max(0, retries - 1),
        root_cause_accuracy=frame.confidence,
        first_choice_correct=retries == 0,
        retries_needed=retries,
        output_usefulness=critique.overall_score,
        duplicate_work=False,
        overcomplicated=any("overcomplicated" in w.lower() for w in critique.weaknesses),
    )


# ═══════════════════════════════════════════════════════════════
# INTEGRATED REASONING PRE-PASS
# ═══════════════════════════════════════════════════════════════

@dataclass
class ReasoningResult:
    """Full reasoning pre-pass result — injected into mission context."""
    frame: ProblemFrame
    output_shape: OutputShape
    repo_awareness: RepoAwareness | None
    reasoning_ms: int
    enriched_goal: str          # Original goal + reasoning context

    def to_dict(self) -> dict:
        d = {
            "frame": self.frame.to_dict(),
            "output_shape": self.output_shape.value,
            "reasoning_ms": self.reasoning_ms,
        }
        if self.repo_awareness:
            d["repo_awareness"] = self.repo_awareness.to_dict()
        return d

    def to_prompt_injection(self) -> str:
        """Concise context string for agent prompts."""
        lines = [self.frame.to_prompt_context()]
        lines.append(f"OUTPUT FORMAT: {self.output_shape.value}")
        if self.repo_awareness:
            lines.append(f"TARGET LAYER: {self.repo_awareness.target_layer}")
            if self.repo_awareness.anti_patterns:
                lines.append(f"AVOID: {'; '.join(self.repo_awareness.anti_patterns[:2])}")
        return "\n".join(lines)


def reason(
    goal: str,
    classification: dict | None = None,
    prior_failures: list[str] | None = None,
) -> ReasoningResult:
    """
    Full reasoning pre-pass. Run BEFORE mission execution.
    Returns enriched understanding + goal injection.
    """
    t0 = time.time()

    # Phase 1: Frame the problem
    frame = frame_problem(goal, classification, prior_failures)

    # Phase 3: Select output shape
    shape = select_output_shape(goal, frame, classification)

    # Phase 5: Repo awareness (for code-related tasks)
    repo_ctx = None
    if classification and classification.get("task_type") in ("code", "debug", "refactor"):
        repo_ctx = assess_repo_context(goal)
    elif any(w in goal.lower() for w in ("fix", "bug", "implement", "build", "refactor", "code")):
        repo_ctx = assess_repo_context(goal)

    # Build enriched goal
    reasoning_context = frame.to_prompt_context()
    enriched = f"{goal}\n\n---\nReasoning pre-pass:\n{reasoning_context}"
    if repo_ctx:
        enriched += f"\nTarget: {repo_ctx.target_layer}"
        if repo_ctx.existing_patterns:
            enriched += f"\nFollow: {'; '.join(repo_ctx.existing_patterns[:2])}"

    ms = int((time.time() - t0) * 1000)

    result = ReasoningResult(
        frame=frame,
        output_shape=shape,
        repo_awareness=repo_ctx,
        reasoning_ms=ms,
        enriched_goal=enriched,
    )

    log.info("reasoning_complete",
             complexity=frame.complexity_class,
             shape=shape.value,
             bottleneck=frame.likely_bottleneck[:40],
             ms=ms)

    return result


# ── Stop words for specificity scoring ────────────────────────
_STOP_WORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "are",
    "was", "were", "been", "have", "has", "had", "not", "but",
    "all", "can", "will", "just", "more", "some", "than", "them",
    "then", "when", "what", "which", "who", "how", "its", "does",
    "did", "should", "would", "could", "about", "into", "over",
    "such", "also", "each", "other", "very", "most", "only",
})