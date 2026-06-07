"""
ImprovementCandidate generator.

Takes List[Weakness] and generates up to 3 ImprovementCandidate objects.
Each candidate specifies how to address a detected weakness.

Candidate types:
  PROMPT_TWEAK      — modify workspace/prompts/*.txt
  TOOL_PREFERENCE   — adjust workspace/preferences/tool_prefs.json
  RETRY_STRATEGY    — configure workspace/preferences/retry_config.json
  SKIP_PATTERN      — add to workspace/preferences/skip_patterns.json
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

logger = logging.getLogger("bea.self_improvement.candidate_generator")

VALID_TYPES = frozenset({"PROMPT_TWEAK", "TOOL_PREFERENCE", "RETRY_STRATEGY", "SKIP_PATTERN"})

_SEVERITY_GAIN = {"HIGH": 0.7, "MEDIUM": 0.5, "LOW": 0.3}


@dataclass
class ImprovementCandidate:
    type: str              # PROMPT_TWEAK | TOOL_PREFERENCE | RETRY_STRATEGY | SKIP_PATTERN
    description: str
    expected_gain: float   # 0.0–1.0
    risk: str              # LOW | MEDIUM | HIGH
    domain: str = ""
    weakness_severity: str = "LOW"


class CandidateGenerator:
    """
    Generates at most 3 improvement candidates per run (MAX_IMPROVEMENTS_PER_RUN * 3).
    Deduplicates by candidate type — one candidate per type max.
    """

    MAX_CANDIDATES = 3

    def generate(self, weaknesses: List) -> List[ImprovementCandidate]:
        """
        Generates improvement candidates from detected weaknesses.
        Returns at most 3 candidates, deduplicated by type.

        Args:
            weaknesses: List[Weakness] from WeaknessDetector.detect()

        Returns:
            List[ImprovementCandidate] with len <= 3
        """
        if not weaknesses:
            return self._default_candidates()

        candidates: List[ImprovementCandidate] = []
        for weakness in weaknesses:
            candidates += self._candidates_for_weakness(weakness)

        # Sort by expected_gain descending, deduplicate by type
        candidates.sort(key=lambda c: c.expected_gain, reverse=True)
        seen_types: set[str] = set()
        deduped: List[ImprovementCandidate] = []
        for c in candidates:
            if c.type not in seen_types:
                seen_types.add(c.type)
                deduped.append(c)

        return deduped[: self.MAX_CANDIDATES]

    # ── Domain → candidate mapping ────────────────────────────────────────────

    def _candidates_for_weakness(self, weakness) -> List[ImprovementCandidate]:
        domain = getattr(weakness, "domain", "general")
        severity = getattr(weakness, "severity", "LOW")
        base_gain = _SEVERITY_GAIN.get(severity, 0.3)

        if domain in ("coding", "debugging"):
            return [
                ImprovementCandidate(
                    type="PROMPT_TWEAK",
                    description=(
                        f"Improve {domain} prompt: add step-by-step instructions "
                        f"and error recovery patterns"
                    ),
                    expected_gain=base_gain,
                    risk="LOW" if severity == "LOW" else "MEDIUM",
                    domain=domain,
                    weakness_severity=severity,
                ),
                ImprovementCandidate(
                    type="RETRY_STRATEGY",
                    description=(
                        f"Add retry strategy for {domain} failures: "
                        f"max_retries=3, exponential backoff"
                    ),
                    expected_gain=base_gain * 0.8,
                    risk="LOW",
                    domain=domain,
                    weakness_severity=severity,
                ),
            ]

        if domain == "api_usage":
            return [
                ImprovementCandidate(
                    type="TOOL_PREFERENCE",
                    description=(
                        "Adjust tool preference weights for api_usage: "
                        "prefer stable tools with low error rate"
                    ),
                    expected_gain=base_gain,
                    risk="LOW",
                    domain=domain,
                    weakness_severity=severity,
                ),
                ImprovementCandidate(
                    type="RETRY_STRATEGY",
                    description=(
                        "Add API retry config: max_retries=3, delay=2s "
                        "for transient network errors"
                    ),
                    expected_gain=base_gain * 0.9,
                    risk="LOW",
                    domain=domain,
                    weakness_severity=severity,
                ),
            ]

        if domain == "automation":
            return [
                ImprovementCandidate(
                    type="SKIP_PATTERN",
                    description=(
                        f"Skip known failing automation patterns in {domain} domain"
                    ),
                    expected_gain=base_gain * 0.7,
                    risk="MEDIUM",
                    domain=domain,
                    weakness_severity=severity,
                ),
                ImprovementCandidate(
                    type="RETRY_STRATEGY",
                    description=(
                        "Add retry strategy for automation: "
                        "max_retries=2, delay=5s for slow operations"
                    ),
                    expected_gain=base_gain * 0.6,
                    risk="LOW",
                    domain=domain,
                    weakness_severity=severity,
                ),
            ]

        if domain in ("planning", "research"):
            return [
                ImprovementCandidate(
                    type="PROMPT_TWEAK",
                    description=(
                        f"Improve {domain} prompt: add context retrieval "
                        f"and structured output format instructions"
                    ),
                    expected_gain=base_gain,
                    risk="LOW",
                    domain=domain,
                    weakness_severity=severity,
                ),
            ]

        # Generic fallback
        return [
            ImprovementCandidate(
                type="TOOL_PREFERENCE",
                description=f"Optimize tool selection for {domain} domain",
                expected_gain=base_gain * 0.5,
                risk="LOW",
                domain=domain,
                weakness_severity=severity,
            ),
        ]

    def _default_candidates(self) -> List[ImprovementCandidate]:
        """Safe default when no weaknesses detected."""
        return [
            ImprovementCandidate(
                type="PROMPT_TWEAK",
                description=(
                    "General prompt optimization: add clearer output "
                    "format instructions and structured reasoning steps"
                ),
                expected_gain=0.2,
                risk="LOW",
                domain="general",
                weakness_severity="LOW",
            )
        ]


# ── Singleton ─────────────────────────────────────────────────────────────────

_generator: CandidateGenerator | None = None


def get_candidate_generator() -> CandidateGenerator:
    global _generator
    if _generator is None:
        _generator = CandidateGenerator()
    return _generator
