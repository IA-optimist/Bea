"""
BEA MAX — Self-Critic
CriticAgent evaluates agent outputs and triggers reruns when quality is insufficient.

Scoring dimensions (0–10 each):
    correctness  — is the output factually/logically sound?
    completeness — does it fully address the task?
    safety       — does it contain harmful/dangerous content?
    efficiency   — is it concise and well-structured?

Decision rules:
    should_rerun() → True if any score < 5 OR overall < 6.0
    Max 2 reruns per task (tracked by task_hash in rerun_counts)

Usage:
    critic = get_critic(settings)
    report = await critic.evaluate(session_id, "coder-agent", task, output)
    if critic.should_rerun(report):
        augmented = critic.build_rerun_prompt(task, output, report.feedback)
        # caller re-runs with augmented prompt
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any

import structlog

from kernel.evaluation.scorer import CRITIC_OVERALL_PASS_THRESHOLD

log = structlog.get_logger(__name__)

_MAX_REPORTS    = 200   # bounded deque
_MAX_RERUN_SCOPES = 1024
CRITIC_DIMENSION_PASS_THRESHOLD = 5.0
CRITIC_MAX_RERUNS = 2
_MAX_RERUNS     = CRITIC_MAX_RERUNS
_RERUN_TTL_S    = 3600  # rerun counter TTL (1 hour)

# Patterns that damage safety score
_DANGEROUS_PATTERNS = re.compile(
    r"rm\s+-rf|DROP\s+TABLE|DELETE\s+FROM\s+\w+\s+WHERE\s+1=1|"
    r"os\.system\s*\(|subprocess\.call\s*\(\s*['\"]sh|"
    r"eval\s*\(\s*input|exec\s*\(\s*input|"
    r"\/etc\/passwd|\/etc\/shadow",
    re.IGNORECASE,
)


@dataclass
class CriticScores:
    correctness:  float = 8.0
    completeness: float = 8.0
    safety:       float = 10.0
    efficiency:   float = 8.0

    def __post_init__(self) -> None:
        for field_name in ("correctness", "completeness", "safety", "efficiency"):
            value = getattr(self, field_name)
            if isinstance(value, bool):
                raise ValueError(f"{field_name} must be numeric")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field_name} must be numeric") from exc
            if not math.isfinite(number) or not 0.0 <= number <= 10.0:
                raise ValueError(
                    f"{field_name} must be finite and within [0, 10]"
                )
            setattr(self, field_name, number)

    @property
    def overall(self) -> float:
        return round(
            (self.correctness + self.completeness + self.safety + self.efficiency) / 4, 2
        )

    def to_dict(self) -> dict:
        return {
            "correctness":  round(self.correctness, 2),
            "completeness": round(self.completeness, 2),
            "safety":       round(self.safety, 2),
            "efficiency":   round(self.efficiency, 2),
            "overall":      self.overall,
        }


@dataclass
class CriticReport:
    report_id:   str         = field(default_factory=lambda: str(uuid.uuid4()))
    session_id:  str         = ""
    agent_name:  str         = ""
    task:        str         = ""
    task_hash:   str         = ""
    rerun_scope: str         = ""
    output:      str         = ""
    scores:      CriticScores = field(default_factory=CriticScores)
    feedback:    str         = ""
    suggestions: list[str]   = field(default_factory=list)
    rerun_count: int         = 0
    timestamp:   float       = field(default_factory=time.time)

    @property
    def overall(self) -> float:
        return self.scores.overall

    def to_dict(self) -> dict:
        return {
            "report_id":   self.report_id,
            "session_id":  self.session_id,
            "agent_name":  self.agent_name,
            "task":        self.task[:200],
            "task_hash":   self.task_hash,
            "scores":      self.scores.to_dict(),
            "feedback":    self.feedback,
            "suggestions": self.suggestions,
            "rerun_count": self.rerun_count,
            "timestamp":   self.timestamp,
        }


class CriticAgent:
    """
    Evaluates agent outputs using heuristics (+ optional LLM scoring).
    Stores only redacted report history in a bounded deque.
    Tracks bounded, mission-scoped rerun counts to enforce MAX_RERUNS.
    """

    def __init__(self, settings=None):
        self.s             = settings
        self._reports:     deque[CriticReport] = deque(maxlen=_MAX_REPORTS)
        # mission/agent/task scope hash -> (count, last_ts)
        self._rerun_counts: dict[str, tuple[int, float]] = {}
        self._rerun_lock = threading.RLock()
        self._report_lock = threading.RLock()

    # ── Public API ────────────────────────────────────────────

    async def evaluate(
        self,
        session_id: str,
        agent_name: str,
        task:       str,
        output:     Any,
    ) -> CriticReport:
        """
        Evaluate an agent output. Tries LLM scoring first; falls back to heuristics.
        Stores report in internal deque.
        """
        output_str = str(output) if output is not None else ""
        task_hash  = _hash_task(task)
        rerun_scope = _hash_rerun_scope(session_id, agent_name, task)

        # Look up existing rerun count
        rerun_count = self._get_rerun_count(rerun_scope)

        # Score
        try:
            scores, feedback, suggestions = await self._llm_score(
                task, output_str, agent_name
            )
        except Exception:
            scores, feedback, suggestions = self._heuristic_score(task, output_str)

        report = CriticReport(
            session_id  = session_id,
            agent_name  = agent_name,
            task        = task,
            task_hash   = task_hash,
            rerun_scope = rerun_scope,
            output      = output_str[:500],
            scores      = scores,
            feedback    = feedback,
            suggestions = suggestions,
            rerun_count = rerun_count,
        )
        # History is diagnostic only: retain no task, output, feedback, raw session
        # identifier, or suggestions in the process-global compatibility instance.
        history_report = replace(
            report,
            session_id=_hash_session_scope(session_id),
            task="",
            output="",
            feedback="",
            suggestions=[],
        )
        with self._report_lock:
            self._reports.append(history_report)

        log.debug(
            "critic_evaluated",
            agent=agent_name,
            overall=report.overall,
            rerun_count=rerun_count,
            session=session_id,
        )
        return report

    def should_rerun(self, report: CriticReport) -> bool:
        """
        True if output quality is insufficient AND reruns remain.
        Threshold: any single score < 5 OR overall < 6.0
        """
        s = report.scores
        below_threshold = (
            s.correctness < CRITIC_DIMENSION_PASS_THRESHOLD
            or s.completeness < CRITIC_DIMENSION_PASS_THRESHOLD
            or s.safety < CRITIC_DIMENSION_PASS_THRESHOLD
            or s.efficiency < CRITIC_DIMENSION_PASS_THRESHOLD
            or s.overall < CRITIC_OVERALL_PASS_THRESHOLD
        )
        return below_threshold and report.rerun_count < _MAX_RERUNS

    def build_rerun_prompt(
        self,
        task:            str,
        original_output: str,
        feedback:        str,
        suggestions:     list[str] | None = None,
    ) -> str:
        """
        Build an augmented prompt for re-execution.
        Caller is responsible for running it.
        """
        lines = [
            "[SELF-CRITIC FEEDBACK]",
            feedback,
        ]
        if suggestions:
            lines.append("\nSuggestions to address:")
            for i, s in enumerate(suggestions, 1):
                lines.append(f"  {i}. {s}")
        lines += [
            "\n[PREVIOUS OUTPUT — improve upon this]",
            original_output[:600],
            "\n[ORIGINAL TASK]",
            task,
        ]
        return "\n".join(lines)

    def reserve_rerun(self, report: CriticReport) -> bool:
        """Atomically reserve one rerun in the report's mission-scoped budget."""
        rerun_scope = report.rerun_scope or _hash_rerun_scope(
            report.session_id, report.agent_name, report.task
        )
        with self._rerun_lock:
            count = self._get_rerun_count(rerun_scope)
            if count >= _MAX_RERUNS:
                return False
            self._rerun_counts[rerun_scope] = (count + 1, time.time())
            self._purge_stale_reruns()
            return True

    def increment_rerun(self, rerun_scope: str) -> int:
        """Increment rerun counter. Returns new count."""
        with self._rerun_lock:
            count = self._get_rerun_count(rerun_scope)
            if count >= _MAX_RERUNS:
                return count
            new_count = count + 1
            self._rerun_counts[rerun_scope] = (new_count, time.time())
            self._purge_stale_reruns()
            return new_count

    # ── Reporting ─────────────────────────────────────────────

    def get_reports(
        self,
        session_id: str,
        agent_name: str | None = None,
        limit:      int        = 20,
    ) -> list[CriticReport]:
        """Return redacted diagnostics for one correlation scope.

        ``session_id`` is never an authorization identity. Callers remain
        responsible for authenticated access before invoking this internal API.
        """
        session_scope = _hash_session_scope(session_id)
        with self._report_lock:
            reports = [
                report
                for report in self._reports
                if report.session_id == session_scope
            ]
        if agent_name:
            reports = [r for r in reports if r.agent_name == agent_name]
        return reports[-limit:]

    def agent_summary(self, session_id: str, agent_name: str) -> dict:
        reports = self.get_reports(session_id, agent_name=agent_name)
        if not reports:
            return {"agent": agent_name, "total": 0}
        overalls = [r.overall for r in reports]
        reruns   = sum(1 for r in reports if r.rerun_count > 0)
        return {
            "agent":        agent_name,
            "total":        len(reports),
            "avg_overall":  round(sum(overalls) / len(overalls), 2),
            "min_overall":  round(min(overalls), 2),
            "max_overall":  round(max(overalls), 2),
            "rerun_count":  reruns,
        }

    # ── Scoring ───────────────────────────────────────────────

    async def _llm_score(
        self, task: str, output: str, agent_name: str
    ) -> tuple[CriticScores, str, list[str]]:
        """LLM-based scoring — only runs if OpenAI key is configured."""
        api_key = getattr(self.s, "openai_api_key", None) if self.s else None
        if not api_key:
            raise RuntimeError("No LLM available for scoring")

        import openai
        client = openai.AsyncOpenAI(api_key=api_key)

        prompt = (
            f"You are a strict code/task quality evaluator.\n"
            f"Task: {task[:500]}\n"
            f"Agent: {agent_name}\n"
            f"Output: {output[:800]}\n\n"
            f"Rate this output on 4 dimensions (0-10 each):\n"
            f"1. correctness — factually/logically sound?\n"
            f"2. completeness — fully addresses the task?\n"
            f"3. safety — no dangerous content?\n"
            f"4. efficiency — concise and well-structured?\n\n"
            f"Respond ONLY as JSON:\n"
            f'{{ "correctness": 7, "completeness": 8, "safety": 10, "efficiency": 7, '
            f'"feedback": "...", "suggestions": ["...", "..."] }}'
        )

        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=300,
        )
        import json
        raw = resp.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip("`").strip()
        data = json.loads(raw)

        scores = CriticScores(
            correctness  = float(data.get("correctness",  7)),
            completeness = float(data.get("completeness", 7)),
            safety       = float(data.get("safety",      10)),
            efficiency   = float(data.get("efficiency",   7)),
        )
        feedback    = data.get("feedback", "")
        suggestions = data.get("suggestions", [])
        return scores, feedback, suggestions

    @staticmethod
    def _heuristic_score(
        task: str, output: str
    ) -> tuple[CriticScores, str, list[str]]:
        """Fast heuristic scoring — no LLM required."""
        feedback:    list[str] = []
        suggestions: list[str] = []

        # ── Correctness ────────────────────────────────────────
        if not output.strip():
            correctness = 0.0
            feedback.append("Output is empty.")
            suggestions.append("Produce a non-empty response addressing the task.")
        elif re.search(r"traceback|exception|error:", output, re.IGNORECASE):
            correctness = 3.0
            feedback.append("Output contains error traces.")
            suggestions.append("Handle exceptions and return clean output.")
        elif len(output) < 20:
            correctness = 4.0
            feedback.append("Output is very short — may be incomplete.")
        else:
            correctness = 8.0

        # ── Completeness ───────────────────────────────────────
        min_expected = max(len(task) * 1.5, 80)
        ratio = len(output) / min_expected
        if ratio < 0.3:
            completeness = 3.0
            suggestions.append("Provide a more thorough response.")
        elif ratio < 0.7:
            completeness = 6.0
        elif ratio > 10.0:
            completeness = 7.0   # penalise bloat slightly
            suggestions.append("Be more concise — output is very long.")
        else:
            completeness = 9.0

        # ── Safety ─────────────────────────────────────────────
        if _DANGEROUS_PATTERNS.search(output):
            safety = 1.0
            feedback.append("Output contains potentially dangerous commands/patterns.")
            suggestions.append("Remove or sandbox any dangerous shell/SQL commands.")
        else:
            safety = 10.0

        # ── Efficiency ─────────────────────────────────────────
        # Penalise excessive repetition
        words = output.lower().split()
        if words:
            unique_ratio = len(set(words)) / len(words)
            efficiency = round(min(10.0, unique_ratio * 12), 1)
        else:
            efficiency = 0.0

        scores = CriticScores(
            correctness  = correctness,
            completeness = completeness,
            safety       = safety,
            efficiency   = efficiency,
        )
        fb_str = " ".join(feedback) if feedback else (
            f"Overall score {scores.overall:.1f}/10 — "
            + (
                "acceptable."
                if scores.overall >= CRITIC_OVERALL_PASS_THRESHOLD
                else "needs improvement."
            )
        )
        return scores, fb_str, suggestions

    # ── Helpers ───────────────────────────────────────────────

    def _get_rerun_count(self, rerun_scope: str) -> int:
        with self._rerun_lock:
            count, ts = self._rerun_counts.get(rerun_scope, (0, 0.0))
            if time.time() - ts > _RERUN_TTL_S:
                self._rerun_counts.pop(rerun_scope, None)
                return 0
            return count

    def _purge_stale_reruns(self) -> None:
        with self._rerun_lock:
            cutoff = time.time() - _RERUN_TTL_S
            stale  = [k for k, (_, ts) in self._rerun_counts.items() if ts < cutoff]
            for k in stale:
                del self._rerun_counts[k]
            overflow = len(self._rerun_counts) - _MAX_RERUN_SCOPES
            if overflow > 0:
                oldest = sorted(
                    self._rerun_counts.items(),
                    key=lambda item: item[1][1],
                )[:overflow]
                for rerun_scope, _ in oldest:
                    del self._rerun_counts[rerun_scope]


def _hash_task(task: str) -> str:
    return hashlib.sha256(task.encode()).hexdigest()[:16]


def _hash_session_scope(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:24]


def _hash_rerun_scope(session_id: str, agent_name: str, task: str) -> str:
    payload = "\0".join((session_id, agent_name, task))
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


# ── Singleton ─────────────────────────────────────────────────

_critic: CriticAgent | None = None


def get_critic(settings=None) -> CriticAgent:
    global _critic
    if _critic is None:
        _critic = CriticAgent(settings)
    return _critic
