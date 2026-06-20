"""
BEA MAX — Training Data Collector
=====================================
Collects training examples from successful missions to build a fine-tuning dataset.

Goal: Collect 1000 high-quality examples to fine-tune Qwen 2.5 Coder 32B.

Each example captures:
- goal (instruction)
- result (completion)
- score (quality metric)
- dopamine signal (reward prediction error)
- metadata (model, duration, plan, lessons)

Examples are stored in workspace/training_data/<domain>.jsonl for easy access.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional
import structlog

log = structlog.get_logger(__name__)

# Domain classification keywords
DOMAIN_KEYWORDS = {
    "security": [
        "security", "vulnerability", "audit", "penetration", "exploit", "cve",
        "authentication", "authorization", "encryption", "firewall", "malware",
        "threat", "attack", "defense", "hardening", "compliance", "owasp"
    ],
    "code": [
        "code", "programming", "function", "class", "debug", "refactor", "test",
        "api", "endpoint", "bug", "error", "syntax", "algorithm", "implement",
        "build", "develop", "script", "module", "library", "package", "git"
    ],
    "business": [
        "business", "revenue", "profit", "roi", "market", "customer", "strategy",
        "sales", "marketing", "growth", "metrics", "kpi", "opportunity", "venture",
        "investment", "finance", "budget", "cost", "pricing", "competitor"
    ],
    "research": [
        "research", "analysis", "study", "investigate", "explore", "survey",
        "data", "statistics", "hypothesis", "experiment", "findings", "paper",
        "literature", "academic", "scientific", "methodology", "dataset"
    ],
    "ops": [
        "deploy", "infrastructure", "server", "database", "monitoring", "logging",
        "backup", "recovery", "scaling", "performance", "optimization", "devops",
        "ci/cd", "docker", "kubernetes", "cloud", "aws", "azure", "gcp"
    ],
}


def classify_domain(goal: str) -> str:
    """
    Classify mission domain based on keyword matching.
    
    Args:
        goal: Mission goal/instruction text
    
    Returns:
        Domain string: security, code, business, research, ops, or general
    """
    goal_lower = goal.lower()

    # Count keyword matches per domain
    domain_scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in goal_lower)
        if score > 0:
            domain_scores[domain] = score

    # Return domain with highest score, or 'general' if no matches
    if domain_scores:
        return max(domain_scores.items(), key=lambda x: x[1])[0]
    return "general"


def compute_dopamine_signal(
    actual_score: float,
    predicted_score: float = 0.5
) -> float:
    """
    Compute dopamine signal (reward prediction error).
    
    Dopamine signal = actual - predicted
    - Positive: better than expected (learning opportunity)
    - Negative: worse than expected (correction needed)
    - Zero: as expected (no surprise)
    
    Args:
        actual_score: Actual mission score/confidence (0.0-1.0)
        predicted_score: Predicted score (default 0.5 for baseline)
    
    Returns:
        Delta score (reward prediction error)
    """
    return actual_score - predicted_score


async def collect_training_example(
    mission_id: str,
    goal: str,
    result: str,
    score: float,
    model_used: Optional[str] = None,
    duration_s: Optional[float] = None,
    plan: Optional[Dict[str, Any]] = None,
    lessons: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    score_predicted: float = 0.5,
) -> bool:
    """
    Collect a training example from a successful mission.
    
    Only collects if score >= 0.6 (quality threshold).
    Saves to workspace/training_data/<domain>.jsonl in instruction-tuning format.
    
    Args:
        mission_id: Unique mission identifier
        goal: Mission instruction/goal
        result: Mission result/completion
        score: Quality score (0.0-1.0), typically confidence or verdict score
        model_used: Model that executed the mission (e.g., "gpt-4", "qwen-2.5-coder-32b")
        duration_s: Mission duration in seconds
        plan: Mission plan/strategy dict
        lessons: Learned lessons dict
        metadata: Additional metadata dict
        score_predicted: Predicted score for dopamine calculation (default 0.5)
    
    Returns:
        True if example was collected, False otherwise
    """
    try:
        # Quality threshold: only collect successful missions
        if score < 0.6:
            log.debug(
                "training_data.skip_low_score",
                mission_id=mission_id,
                score=score,
                threshold=0.6
            )
            return False

        # Classify domain
        domain = classify_domain(goal)

        # Compute dopamine signal (reward prediction error)
        delta_score = compute_dopamine_signal(score, score_predicted)

        # Prepare training example in instruction-tuning format
        example = {
            "mission_id": mission_id,
            "instruction": goal,
            "output": result,
            "score": round(score, 3),
            "dopamine": round(delta_score, 3),
            "domain": domain,
            "model_used": model_used or "unknown",
            "duration_s": round(duration_s, 2) if duration_s else None,
            "plan": plan or {},
            "lessons": lessons or {},
            "metadata": metadata or {},
            "collected_at": time.time(),
        }

        # Ensure workspace/training_data directory exists
        workspace_dir = Path("workspace/training_data")
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Append to domain-specific JSONL file
        output_file = workspace_dir / f"{domain}.jsonl"
        with output_file.open("a", encoding="utf-8") as f:
            json.dump(example, f, ensure_ascii=False)
            f.write("\n")

        log.info(
            "training_data.collected",
            mission_id=mission_id,
            domain=domain,
            score=score,
            dopamine=round(delta_score, 3),
            file=str(output_file)
        )
        return True

    except Exception as e:
        log.error(
            "training_data.collection_failed",
            mission_id=mission_id,
            err=str(e)[:200],
            exc_info=True
        )
        return False


def get_training_stats() -> Dict[str, Any]:
    """
    Get training data collection statistics.
    
    Returns:
        Dict with:
        - total: total examples collected
        - by_domain: dict of counts per domain
        - progress: percentage toward 1000 examples
        - next_milestone: next milestone (100, 250, 500, 750, 1000)
    """
    try:
        workspace_dir = Path("workspace/training_data")
        if not workspace_dir.exists():
            return {
                "total": 0,
                "by_domain": {},
                "progress": 0.0,
                "next_milestone": 100,
            }

        # Count examples per domain
        by_domain = {}
        total = 0

        for domain_file in workspace_dir.glob("*.jsonl"):
            domain = domain_file.stem
            count = sum(1 for _ in domain_file.open("r", encoding="utf-8"))
            by_domain[domain] = count
            total += count

        # Calculate progress
        goal = 1000
        progress = min(100.0, (total / goal) * 100)

        # Determine next milestone
        milestones = [100, 250, 500, 750, 1000]
        next_milestone = next((m for m in milestones if m > total), 1000)

        return {
            "total": total,
            "by_domain": by_domain,
            "progress": round(progress, 2),
            "next_milestone": next_milestone,
            "goal": goal,
        }

    except Exception as e:
        log.error("training_stats.failed", err=str(e)[:200])
        return {
            "total": 0,
            "by_domain": {},
            "progress": 0.0,
            "next_milestone": 100,
            "error": str(e)[:200],
        }


# Test function for manual validation
def _test_collector():
    """Test the training data collector."""
    import asyncio

    async def run_test():
        print("Testing training data collector...")

        # Test classification
        test_cases = [
            ("Fix SQL injection vulnerability in auth endpoint", "security"),
            ("Implement binary search algorithm in Python", "code"),
            ("Analyze market opportunity for SaaS product", "business"),
            ("Research transformer architecture papers", "research"),
            ("Deploy microservices to Kubernetes cluster", "ops"),
            ("Schedule a meeting for next week", "general"),
        ]

        for goal, expected_domain in test_cases:
            domain = classify_domain(goal)
            status = "✓" if domain == expected_domain else "✗"
            print(f"{status} '{goal[:50]}...' → {domain} (expected: {expected_domain})")

        # Test collection
        success = await collect_training_example(
            mission_id="test_001",
            goal="Create a REST API for user authentication",
            result="Implemented FastAPI endpoint with JWT tokens and bcrypt hashing",
            score=0.85,
            model_used="test-model",
            duration_s=45.2,
            plan={"steps": ["design", "implement", "test"]},
            lessons={"learned": "Always validate JWT expiry"},
        )
        print(f"{'✓' if success else '✗'} Collection test: {success}")

        # Test stats
        stats = get_training_stats()
        print(f"Stats: {json.dumps(stats, indent=2)}")

    asyncio.run(run_test())


if __name__ == "__main__":
    _test_collector()
