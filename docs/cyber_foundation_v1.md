# Béa Cyber Foundation v1 — Architecture & Usage

## Overview

`agent_cyber` is a standalone defensive security analysis library for Béa. It provides:
- **CyberScopePolicy** — explicit scope + authorization before any action
- **CyberActionGuard** — central deny-by-default gate
- **EvidenceGate** — anti-hallucination: claims require attached evidence
- **SecurityFinding** — typed vulnerability model (16 classes, 5 severities)
- **CyberMissionGraph** — auditable fact/intent graph (VulnClaw-inspired)
- **CyberReportGenerator** — redacted Markdown + JSON output
- **11 Defensive Skills** — read-only analysis only
- **CyberEvalHarness** — L0-L3 benchmark with 5 educational fixtures

## Package Structure

```
agent_cyber/
  __init__.py
  actions.py        # CyberActionType (11 allowed), BlockedCyberActionType (10 blocked)
  scope.py          # CyberScopePolicy, AuthorizationStatus, RiskLevel
  policy.py         # CyberActionGuard, CyberPolicyDecision
  evidence.py       # Evidence, EvidenceType, EvidenceGate, Claim, ClaimType
  findings.py       # SecurityFinding, VulnClass, Severity, FindingStatus
  mission_graph.py  # CyberFact, CyberIntent, CyberMissionGraph
  reports.py        # CyberReport, CyberReportGenerator
  skills.py         # CyberSkill, DEFENSIVE_SKILLS_V1, SKILL_REGISTRY
  integration.py    # create_cyber_mission_context, finalize_cyber_mission
  evals/
    models.py       # CyberEvalTask, CyberEvalAgentOutput, CyberEvalScore
    scorer.py       # CyberEvalScorer (L0-L3 weighted scoring)
    runner.py       # CyberEvalRunner (fixture loader)
    fixtures/       # 5 educational YAML tasks
```

## Usage Example

```python
from agent_cyber.scope import CyberScopePolicy, AuthorizationStatus, RiskLevel
from agent_cyber.integration import create_cyber_mission_context, finalize_cyber_mission

# 1. Create scope (mandatory)
scope = CyberScopePolicy(
    mission_id="mission-001",
    requested_by="security-team",
    authorization_status=AuthorizationStatus.EXPLICIT,
    authorization_ref="pentest-contract-2026-001",
    targets=["localhost"],
    allowed_paths=["/app/"],
    allowed_actions=["code_review", "secret_scan"],
    risk_level=RiskLevel.MEDIUM,
)

# 2. Create mission context
ctx = create_cyber_mission_context("mission-001", scope)

# 3. Validate any action before executing
decision = ctx.guard.validate(action="code_review", scope=scope)
assert decision.allowed, decision.reason

# 4. Run analysis, collect findings
# ctx.findings.append(SecurityFinding(...))

# 5. Generate report
report = finalize_cyber_mission(ctx, actions_performed=["code_review"])
generator = CyberReportGenerator()
markdown, json_data = generator.generate(report)
```

## Running Tests

```bash
pytest tests/agent_cyber/ -v --tb=short
pytest tests/agent_cyber/ -q
```

## v1 Limitations

- Static analysis only — no live HTTP requests (unless scope.max_requests > 0)
- No autonomous agent — `agent_cyber` is a library, not a running agent
- No REST API endpoints — to be added in v2
- No CVE database — dependency audit delegates to pip-audit (external tool)
- Scoring is simulated in v1 (CyberEvalRunner.run_fixture returns mocked output)
- Rate limiting is stateless (log-only) — Redis enforcement in v2

## v2 Roadmap

- REST endpoints: `/api/v3/cyber/scope`, `/api/v3/cyber/findings`, `/api/v3/cyber/report`
- Autonomous `CyberReviewerAgent` in Béa's agent crew
- Real CVE lookup (grype/trivy integration)
- LLM-judge for automatic scoring
- Redis rate limiting
- CyberMissionLoop (GitHubMissionLoop-style)
