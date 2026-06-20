"""
Active Learning for BeaMax
Continuous improvement through skill discovery and performance tracking.
"""
from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime, timezone
import structlog

log = structlog.get_logger(__name__)


class SkillDiscoverer:
    """
    Discovers reusable skills from successful missions.
    
    Extracts patterns that can be saved as capabilities.
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    def analyze_mission(self, mission: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze completed mission for skill extraction.
        
        Returns:
            - is_skill_worthy: bool
            - skill_name: suggested name
            - skill_description: what it does
            - skill_pattern: reusable steps
            - complexity_score: 0-10
        """

        if mission.get("status") != "COMPLETED":
            return {"is_skill_worthy": False, "reason": "Mission not completed"}

        # Check if complex enough to be a skill
        complexity = self._estimate_complexity(mission)

        if complexity < 3:
            return {
                "is_skill_worthy": False,
                "reason": "Too simple (complexity < 3)",
                "complexity_score": complexity
            }

        log.info("analyzing_mission_for_skill", mission_id=mission.get("mission_id"), complexity=complexity)

        # Extract skill pattern via LLM
        prompt = self._build_skill_extraction_prompt(mission)

        try:
            response = self.llm.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.4
            )

            content = response.choices[0].message.content
            result = self._parse_skill_extraction(content)
            result["complexity_score"] = complexity

            return result

        except Exception as e:
            log.error("skill_extraction_failed", err=str(e))
            return {"is_skill_worthy": False, "reason": f"Extraction failed: {str(e)}"}

    def _estimate_complexity(self, mission: Dict[str, Any]) -> int:
        """Estimate mission complexity (0-10)."""

        score = 0

        # Goal length
        goal = mission.get("goal", "")
        if len(goal) > 100:
            score += 2
        elif len(goal) > 50:
            score += 1

        # Number of steps (if available)
        steps = mission.get("plan_summary", "").count("\n") + 1
        score += min(steps, 4)

        # Agents used
        agents = mission.get("agents", [])
        score += min(len(agents), 3)

        # Duration
        duration = mission.get("duration_seconds", 0)
        if duration > 300:  # > 5 min
            score += 2
        elif duration > 60:
            score += 1

        return min(score, 10)

    def _build_skill_extraction_prompt(self, mission: Dict[str, Any]) -> str:
        """Build prompt for skill extraction."""

        return f"""Analyze this completed AI mission and determine if it represents a reusable skill.

Mission Goal: {mission.get('goal', '')}

Agents Used: {', '.join(mission.get('agents', []))}

Result: {mission.get('result', '')[:500]}

If this is a reusable pattern (not just a one-off task), extract a skill definition.

Respond in this format:
IS_SKILL: [YES or NO]
SKILL_NAME: [short-kebab-case-name]
DESCRIPTION: [One-line description]
PATTERN: [Reusable steps, numbered list]
TRIGGERS: [When to use this skill, comma-separated]

Example:
IS_SKILL: YES
SKILL_NAME: analyze-codebase-dependencies
DESCRIPTION: Map dependencies and identify outdated packages
PATTERN: 1. Search for package files (requirements.txt, package.json), 2. Parse versions, 3. Check for updates, 4. Generate report
TRIGGERS: codebase audit, dependency analysis, security scan"""

    def _parse_skill_extraction(self, response: str) -> Dict[str, Any]:
        """Parse skill extraction response."""

        lines = [l.strip() for l in response.split("\n") if l.strip()]
        result = {"is_skill_worthy": False}

        for line in lines:
            if line.startswith("IS_SKILL:"):
                value = line.split(":", 1)[1].strip().upper()
                result["is_skill_worthy"] = (value == "YES")

            elif line.startswith("SKILL_NAME:"):
                result["skill_name"] = line.split(":", 1)[1].strip()

            elif line.startswith("DESCRIPTION:"):
                result["skill_description"] = line.split(":", 1)[1].strip()

            elif line.startswith("PATTERN:"):
                result["skill_pattern"] = line.split(":", 1)[1].strip()

            elif line.startswith("TRIGGERS:"):
                triggers_str = line.split(":", 1)[1].strip()
                result["triggers"] = [t.strip() for t in triggers_str.split(",")]

        return result


class PerformanceTracker:
    """
    Tracks agent performance over time.
    
    Identifies strengths/weaknesses for continuous improvement.
    """

    def __init__(self):
        self.metrics = {
            "total_missions": 0,
            "successes": 0,
            "failures": 0,
            "avg_duration": 0.0,
            "avg_confidence": 0.0,
            "domains": {}  # Track performance per domain
        }

    def record_mission(self, mission: Dict[str, Any]):
        """Record mission outcome for analytics."""

        self.metrics["total_missions"] += 1

        status = mission.get("status", "UNKNOWN")
        if status == "COMPLETED":
            self.metrics["successes"] += 1
        else:
            self.metrics["failures"] += 1

        # Update averages
        duration = mission.get("duration_seconds", 0)
        confidence = mission.get("confidence", 0.0)

        n = self.metrics["total_missions"]
        self.metrics["avg_duration"] = (
            (self.metrics["avg_duration"] * (n - 1) + duration) / n
        )
        self.metrics["avg_confidence"] = (
            (self.metrics["avg_confidence"] * (n - 1) + confidence) / n
        )

        # Track per-domain
        domain = mission.get("domain", "unknown")
        if domain not in self.metrics["domains"]:
            self.metrics["domains"][domain] = {"count": 0, "successes": 0}

        self.metrics["domains"][domain]["count"] += 1
        if status == "COMPLETED":
            self.metrics["domains"][domain]["successes"] += 1

        log.debug(
            "performance_tracked",
            total=self.metrics["total_missions"],
            success_rate=self.get_success_rate()
        )

    def get_success_rate(self) -> float:
        """Calculate overall success rate."""
        if self.metrics["total_missions"] == 0:
            return 0.0
        return self.metrics["successes"] / self.metrics["total_missions"]

    def get_weak_domains(self, threshold: float = 0.5) -> List[str]:
        """Identify domains with low success rates."""
        weak = []

        for domain, stats in self.metrics["domains"].items():
            if stats["count"] >= 3:  # Min 3 samples
                rate = stats["successes"] / stats["count"]
                if rate < threshold:
                    weak.append(domain)

        return weak

    def get_report(self) -> Dict[str, Any]:
        """Generate performance report."""
        return {
            "summary": {
                "total_missions": self.metrics["total_missions"],
                "success_rate": round(self.get_success_rate(), 3),
                "avg_duration_seconds": round(self.metrics["avg_duration"], 1),
                "avg_confidence": round(self.metrics["avg_confidence"], 3)
            },
            "domains": self.metrics["domains"],
            "weak_domains": self.get_weak_domains(),
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
