"""agentskill_format — interop avec le standard ouvert agentskills.io (Axe 1, Hermes).

Convertit un `Skill` Jarvis en `SKILL.md` portable (frontmatter + procédure
lisible) et inversement. Le round-trip est **lossless** : un bloc de données
JSON masqué (`<!-- jarvis-skill-data ... -->`) permet de reconstruire le Skill
exact, sans dépendance YAML. Si ce bloc est absent (SKILL.md externe), on
reconstruit au mieux depuis le frontmatter `name`/`description`.

Additif : aucun système de skills existant n'est modifié.
"""
from __future__ import annotations

import json
import re

from core.skills.skill_models import Skill, SkillStep

_DATA_RE = re.compile(r"<!--\s*jarvis-skill-data\s*(\{.*?\})\s*-->", re.DOTALL)


def _fm_value(line: str) -> str:
    return line.split(":", 1)[1].strip() if ":" in line else ""


def to_agentskill(skill: Skill) -> str:
    """Sérialise un `Skill` en document SKILL.md (agentskills.io)."""
    tags = ", ".join(skill.tags)
    lines: list[str] = []
    lines.append("---")
    lines.append(f"name: {skill.name}")
    lines.append(f"description: {skill.description}")
    if skill.problem_type:
        lines.append(f"problem_type: {skill.problem_type}")
    if skill.tags:
        lines.append(f"tags: [{tags}]")
    lines.append(f"risk_level: {skill.risk_level}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {skill.name or 'Skill'}")
    lines.append("")
    if skill.description:
        lines.append(skill.description)
        lines.append("")
    if skill.context:
        lines.append("## Quand l'utiliser")
        lines.append(skill.context)
        lines.append("")
    if skill.prerequisites:
        lines.append("## Prérequis")
        lines += [f"- {p}" for p in skill.prerequisites]
        lines.append("")
    if skill.steps:
        lines.append("## Procédure")
        for s in skill.steps:
            suffix = f" (tool: {s.tool})" if s.tool else ""
            lines.append(f"{s.order}. {s.description}{suffix}")
            if s.code_snippet:
                lines.append(f"   `{s.code_snippet}`")
        lines.append("")
    if skill.pitfalls:
        lines.append("## Pièges")
        lines += [f"- {p}" for p in skill.pitfalls]
        lines.append("")
    # Bloc de données lossless pour round-trip exact
    lines.append(f"<!-- jarvis-skill-data {json.dumps(skill.to_dict(), ensure_ascii=False)} -->")
    lines.append("")
    return "\n".join(lines)


def from_agentskill(text: str) -> Skill:
    """Reconstruit un `Skill` depuis un document SKILL.md."""
    if not isinstance(text, str) or not text.strip():
        return Skill()
    # 1) round-trip exact via le bloc de données JSON masqué
    m = _DATA_RE.search(text)
    if m:
        try:
            return Skill.from_dict(json.loads(m.group(1)))
        except (ValueError, TypeError):
            pass
    # 2) repli : parser le frontmatter minimal (interop SKILL.md externe)
    name, description, problem_type, risk = "", "", "", "low"
    tags: list[str] = []
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            low = line.strip().lower()
            if low.startswith("name:"):
                name = _fm_value(line)
            elif low.startswith("description:"):
                description = _fm_value(line)
            elif low.startswith("problem_type:"):
                problem_type = _fm_value(line)
            elif low.startswith("risk_level:"):
                risk = _fm_value(line) or "low"
            elif low.startswith("tags:"):
                raw = _fm_value(line).strip("[]")
                tags = [t.strip() for t in raw.split(",") if t.strip()]
    return Skill(
        name=name, description=description, problem_type=problem_type,
        risk_level=risk, tags=tags,
    )


def propose_skill_from_mission(
    mission_id: str,
    name: str,
    description: str,
    steps: list[dict] | None = None,
    tools_used: list[str] | None = None,
    problem_type: str = "",
    confidence: float = 0.5,
) -> Skill:
    """Construit (sans persister) un `Skill` candidat depuis une mission réussie.

    Fonction pure : l'orchestrateur pourra l'appeler en fin de mission puis
    décider de la persister via `skill_registry`/`skill_feedback` (étape opt-in).
    """
    skill_steps = []
    for i, s in enumerate(steps or [], start=1):
        if isinstance(s, dict):
            skill_steps.append(SkillStep(
                order=s.get("order", i),
                description=str(s.get("description", "")),
                tool=str(s.get("tool", "")),
                code_snippet=str(s.get("code_snippet", "")),
            ))
        else:
            skill_steps.append(SkillStep(order=i, description=str(s)))
    return Skill(
        name=name,
        description=description,
        problem_type=problem_type,
        tools_used=list(tools_used or []),
        steps=skill_steps,
        confidence=max(0.0, min(float(confidence), 1.0)),
        source_mission_id=mission_id,
    )
