"""
core/capability_routing/resolver.py — Capability extraction from goals.

Maps mission goals to capability requirements using:
1. Existing semantic_router (if available)
2. AIOSCapability registry
3. Keyword-based fallback

Always returns at least one CapabilityRequirement. Fail-open.
"""
from __future__ import annotations

import re
import structlog

from core.capability_routing.spec import CapabilityRequirement, ProviderType

log = structlog.get_logger("capability_routing.resolver")

# ── Keyword patterns → capability IDs ─────────────────────────
# Each pattern maps to (capability_id, preferred_type_or_None)

_KEYWORD_PATTERNS: list[tuple[str, str, ProviderType | None]] = [
    # Code
    (r"\b(write|create|implement|build|add)\b.*\b(code|function|class|module|file)\b",
     "code.write", ProviderType.AGENT),
    (r"\b(patch|fix|bug|repair|hotfix)\b",
     "code.patch", ProviderType.AGENT),
    (r"\b(review|audit|check|lint|static.analysis)\b.*\bcode\b",
     "code.review", ProviderType.AGENT),
    (r"\brefactor\b",
     "code.refactor", ProviderType.AGENT),
    (r"\btest(s|ing)?\b",
     "code.test", ProviderType.AGENT),

    # Research / analysis
    (r"\b(research|investigate|analyze|study|competitor)\b",
     "research.analysis", ProviderType.AGENT),
    (r"\b(market|business|industry)\b.*\b(research|analysis|study)\b",
     "research.market", ProviderType.AGENT),

    # Infrastructure / deployment
    (r"\b(deploy|ship|release|publish)\b",
     "infra.deploy", ProviderType.AGENT),
    (r"\b(docker|container|kubernetes|k8s)\b",
     "infra.container", ProviderType.TOOL),
    (r"\b(ci|cd|pipeline|github.actions)\b",
     "infra.ci", ProviderType.TOOL),

    # Security — Blue Team (defensive)
    (r"\b(siem|alert|detection|threat.detect|log.analysis)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(incident.response|ir\b|breach.contain|triage)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(forensic|evidence|artifact.analysis|disk.image)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(cloud.security|aws.security|azure.security|gcp.security|cspm)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(s[eé]curit[eé]|securite)\b.*\b(cloud|aws|azure|gcp|infra)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(cloud|aws|azure|gcp)\b.*\b(s[eé]curit[eé]|security|audit|review)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(endpoint|edr|xdr|antivirus|malware.analysis)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(network.defense|ids|ips|firewall|ndr)\b",
     "security.blue_team", ProviderType.AGENT),
    (r"\b(vulnerability|vuln.scan|cve|patch.management)\b",
     "security.blue_team", ProviderType.AGENT),

    # Security — Red Team (offensive, requires activation)
    (r"\b(pentest|penetration.test|ethical.hack|red.team)\b",
     "security.red_team", ProviderType.AGENT),
    (r"\b(web.app.security|owasp|xss|sqli|injection)\b",
     "security.red_team", ProviderType.AGENT),
    (r"\b(social.engineering|phishing.sim|pretexting)\b",
     "security.red_team", ProviderType.AGENT),
    (r"\b(exploit|payload|reverse.shell|privilege.escalat)\b",
     "security.red_team", ProviderType.AGENT),
    (r"\b(wireless.test|wifi.audit|bluetooth.security)\b",
     "security.red_team", ProviderType.AGENT),
    (r"\b(infrastructure.test|network.pentest|active.recon)\b",
     "security.red_team", ProviderType.AGENT),

    # Security — Compliance
    (r"\b(nis2|nis.2|directive.nis)\b",
     "security.compliance", ProviderType.AGENT),
    (r"\b(gdpr|rgpd|data.protection|privacy.impact)\b",
     "security.compliance", ProviderType.AGENT),
    (r"\b(compliance|regulatory|audit.prep|gap.analysis)\b",
     "security.compliance", ProviderType.AGENT),
    (r"\b(policy.writ|security.policy|governance)\b",
     "security.compliance", ProviderType.AGENT),
    (r"\b(risk.assess|risk.register|risk.matrix)\b",
     "security.compliance", ProviderType.AGENT),
    (r"\b(iso.27001|soc.2|pci.dss|hipaa)\b",
     "security.compliance", ProviderType.AGENT),

    # Security — OSINT
    (r"\b(osint|open.source.intelligence|reconnaissance)\b",
     "security.osint", ProviderType.AGENT),
    (r"\b(domain.recon|dns.enum|subdomain|whois)\b",
     "security.osint", ProviderType.AGENT),
    (r"\b(threat.intel|ioc|indicator.of.compromise|feed)\b",
     "security.osint", ProviderType.AGENT),
    (r"\b(breach.monitor|leak.detect|credential.leak|haveibeenpwned)\b",
     "security.osint", ProviderType.AGENT),
    (r"\b(dark.web|darknet|tor.monitor)\b",
     "security.osint", ProviderType.AGENT),
    (r"\b(social.media.osint|digital.footprint|persona.search)\b",
     "security.osint", ProviderType.AGENT),
    (r"\b(asset.discovery|attack.surface|external.exposure)\b",
     "security.osint", ProviderType.AGENT),

    # Security — General (legacy + FR support, kept for backward compat)
    (r"\b(security|vulnerability|pentest|audit|s[eé]curit[eé]|vuln[eé]rabilit[eé])\b",
     "security.audit", ProviderType.AGENT),
    (r"\b(secret|credential|token|api.key)\b",
     "security.secrets", ProviderType.TOOL),

    # Content
    (r"\b(write|draft|compose)\b.*\b(email|blog|article|content|marketing)\b",
     "content.write", ProviderType.AGENT),
    (r"\b(summarize|summary|tldr)\b",
     "content.summarize", ProviderType.AGENT),

    # GitHub
    (r"\b(github|pr|pull.request|issue|repo)\b",
     "github.operations", ProviderType.MCP),
    (r"\bgit\b.*\b(push|commit|branch|merge)\b",
     "github.git", ProviderType.TOOL),

    # Data / memory
    (r"\b(search|query|find|retrieve|remember)\b.*\b(memory|knowledge|data)\b",
     "memory.retrieve", ProviderType.TOOL),
    (r"\b(store|save|remember)\b",
     "memory.store", ProviderType.TOOL),

    # Browser / web
    (r"\b(browse|scrape|fetch|crawl|web)\b",
     "browser.fetch", ProviderType.MCP),
    (r"\b(playwright|selenium|browser.test)\b",
     "browser.test", ProviderType.MCP),

    # Finance
    (r"\b(stripe|payment|invoice|subscription|billing)\b",
     "finance.stripe", ProviderType.MODULE),
    (r"\b(revenue|mrr|arr)\b",
     "finance.analytics", ProviderType.MODULE),

    # Workflow / automation
    (r"\b(n8n|workflow|automat)\b",
     "workflow.automation", ProviderType.CONNECTOR),
    (r"\b(cron|schedule|timer)\b",
     "workflow.scheduling", ProviderType.TOOL),

    # File system
    (r"\b(file|directory|folder|read|write|list)\b.*\b(system|disk|path)\b",
     "filesystem.operations", ProviderType.MCP),

    # General
    (r"\b(explain|help|question|how)\b",
     "general.conversation", None),
]


def resolve_capabilities(
    goal: str,
    classification: dict | None = None,
) -> list[CapabilityRequirement]:
    """
    Extract capability requirements from a mission goal.

    Strategy:
    1. Try semantic router (embedding-based, if available)
    2. Try AIOSCapability matching
    3. Fall back to keyword patterns
    4. Always returns at least one requirement

    Args:
        goal: The mission goal text.
        classification: Optional classification metadata from MetaOrchestrator.

    Returns:
        List of CapabilityRequirement, best match first.
    """
    requirements: list[CapabilityRequirement] = []

    # 1. Semantic router (best quality, may not be available)
    try:
        requirements.extend(_from_semantic_router(goal))
    except Exception as e:
        log.debug("resolver.semantic_failed", err=str(e)[:60])

    # 2. AIOSCapability matching
    try:
        requirements.extend(_from_aios_capabilities(goal))
    except Exception as e:
        log.debug("resolver.aios_failed", err=str(e)[:60])

    # 3. Classification-based hint
    if classification:
        try:
            requirements.extend(_from_classification(classification))
        except Exception:
            _silent_log.debug("suppressed_exception", src='resolver.py')

    # 4. Keyword matching (always, complements semantic/AIOS)
    try:
        requirements.extend(_from_keywords(goal))
    except Exception:
        _silent_log.debug("suppressed_exception", src='resolver.py')

    # 5. Ultimate fallback
    if not requirements:
        requirements = [CapabilityRequirement(
            capability_id="general.execution",
            required=True,
        )]

    # Deduplicate by capability_id, keeping first occurrence (best match)
    seen: set[str] = set()
    unique: list[CapabilityRequirement] = []
    for r in requirements:
        if r.capability_id not in seen:
            seen.add(r.capability_id)
            unique.append(r)
    return unique


def _from_semantic_router(goal: str) -> list[CapabilityRequirement]:
    """Use semantic_router for high-quality capability matching."""
    from core.capabilities.semantic_router import semantic_match_capability
    matches = semantic_match_capability(goal)
    results = []
    for m in matches[:3]:  # Top 3
        cap_name = m.capability_name
        results.append(CapabilityRequirement(
            capability_id=f"aios.{cap_name}",
            required=True,
            min_reliability=0.3,
            context={"semantic_score": m.score, "source": "semantic_router"},
        ))
    return results


def _from_aios_capabilities(goal: str) -> list[CapabilityRequirement]:
    """Match against registered AIOSCapabilities."""
    from core.capabilities.ai_os_capabilities import AIOS_CAPABILITIES

    goal_lower = goal.lower()
    results = []
    for name, cap in AIOS_CAPABILITIES.items():
        if not cap.enabled:
            continue
        # Simple keyword match on name + description
        score = 0
        for word in name.split("_"):
            if word in goal_lower:
                score += 2
        desc_words = cap.description.lower().split()
        for word in desc_words:
            if len(word) > 3 and word in goal_lower:
                score += 1

        if score > 2:
            results.append(CapabilityRequirement(
                capability_id=f"aios.{name}",
                required=True,
                max_risk=cap.risk_level.lower(),
                context={"aios_score": score, "source": "aios_capabilities"},
            ))

    results.sort(key=lambda r: r.context.get("aios_score", 0), reverse=True)
    return results[:3]


def _from_classification(classification: dict) -> list[CapabilityRequirement]:
    """Extract from mission classification metadata."""
    task_type = classification.get("task_type", "")
    type_map = {
        "code_generation": "code.write",
        "code_review": "code.review",
        "analysis": "research.analysis",
        "research": "research.analysis",
        "planning": "general.planning",
        "writing": "content.write",
        "data_processing": "data.processing",
        "system_admin": "infra.admin",
    }
    cap_id = type_map.get(task_type)
    if cap_id:
        return [CapabilityRequirement(
            capability_id=cap_id,
            required=True,
            context={"source": "classification", "task_type": task_type},
        )]
    return []


def _from_keywords(goal: str) -> list[CapabilityRequirement]:
    """Pattern-based fallback."""
    goal_lower = goal.lower()
    results = []

    for pattern, cap_id, prefer_type in _KEYWORD_PATTERNS:
        if re.search(pattern, goal_lower):
            results.append(CapabilityRequirement(
                capability_id=cap_id,
                required=True,
                prefer_type=prefer_type,
                context={"source": "keyword", "pattern": pattern[:40]},
            ))

    return results[:5]  # Max 5 keyword matches
