# Cybersecurity Skills — Execution Logic

## Routing Flow

```
Goal → Resolver (27 patterns) → SecuritySkillRouter → Domain Skills → Execution
```

## Domain Selection

1. **Blue Team** (`security.blue_team`): Defensive operations, monitoring, incident response
2. **Red Team** (`security.red_team`): Offensive testing — REQUIRES pack activation
3. **Compliance** (`security.compliance`): Regulatory, policy, audit, risk assessment
4. **OSINT** (`security.osint`): Open source intelligence, reconnaissance, monitoring

## Skill Selection Logic

For each domain, skills are scored based on:
- **Name match** (+3 per matching word in skill name vs goal)
- **Description match** (+1 per matching keyword in description vs goal)
- **Confidence weight** (inherent skill reliability 0.0-1.0)
- **Risk level** (low → critical, affects approval requirements)

## Safety Gates

### Red Team Activation Guard
- Red team skills require `red_team_ethical` pack to be explicitly activated
- Default state: BLOCKED
- Activation requires Safety Guardian approval
- All red team operations logged with full audit trail

### Tool Requirements
- Each skill declares required tools (e.g., nmap, burpsuite, splunk)
- Missing tools degrade confidence score
- Critical tools missing → skill unavailable

## Output Types

- **Assessment**: Structured finding with severity, evidence, remediation (blue/red team)
- **Report**: Document with sections, recommendations, compliance mapping (compliance/osint)

## Integration Points

- Resolver patterns → `core/capability_routing/resolver.py`
- Skill catalog → `business/skills/cybersecurity/skill.json`
- Domain router → `core/skills/security_skill_router.py`
- Pack management → `core/agents/canonical_agents.py`
