"""
Chargement des skills depuis le filesystem.

Chemins de recherche (dans l'ordre) :
1. ./skills/bundled/          → skills livrées avec Béa
2. ~/.bea/skills/             → skills installées par l'utilisateur
3. BEA_SKILLS_PATH env var    → chemins additionnels (séparés par :)
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

from skills.types import LoadedSkill, SkillMetadata, SkillStatus

logger = logging.getLogger(__name__)

_SKILL_FILE = "SKILL.md"
_IMPL_FILE = "skill.py"

_BUNDLED_DIR = Path(__file__).parent / "bundled"
_USER_DIR = Path.home() / ".bea" / "skills"


def _search_paths() -> list[Path]:
    """Retourne les répertoires de recherche de skills dans l'ordre de priorité."""
    paths = [_BUNDLED_DIR, _USER_DIR]

    extra = os.environ.get("BEA_SKILLS_PATH", "")
    if extra:
        for p in extra.split(":"):
            p = p.strip()
            if p:
                paths.append(Path(p))

    return [p for p in paths if p.exists()]


def _load_skill_from_dir(skill_dir: Path) -> LoadedSkill | None:
    """Charge une skill depuis son répertoire. Retourne None si invalide."""
    skill_md = skill_dir / _SKILL_FILE
    if not skill_md.exists():
        return None

    content = skill_md.read_text(encoding="utf-8")
    try:
        metadata = SkillMetadata.from_markdown(content, skill_name=skill_dir.name)
    except Exception as e:
        logger.warning("Skill '%s' : SKILL.md invalide → %s", skill_dir.name, e)
        return LoadedSkill(
            metadata=SkillMetadata(name=skill_dir.name, description=""),
            skill_dir=skill_dir,
            status=SkillStatus.ERROR,
            error=str(e),
        )

    skill = LoadedSkill(metadata=metadata, skill_dir=skill_dir)

    # Charger skill.py si présent
    impl_path = skill_dir / _IMPL_FILE
    if impl_path.exists():
        try:
            spec = importlib.util.spec_from_file_location(
                f"bea_skill_{skill_dir.name}", impl_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Chercher une fonction `execute` ou une classe `SkillTool`
            if hasattr(module, "execute"):
                skill.execute_fn = module.execute
            if hasattr(module, "SkillTool"):
                skill.tool_instance = module.SkillTool()

        except Exception as e:
            logger.warning("Skill '%s' : chargement skill.py échoué → %s", skill_dir.name, e)
            skill.status = SkillStatus.ERROR
            skill.error = str(e)

    logger.debug("Skill chargée: '%s' depuis %s", metadata.name, skill_dir)
    return skill


def discover_skills() -> list[LoadedSkill]:
    """
    Découvre et charge toutes les skills disponibles.
    Retourne la liste dans l'ordre de priorité (bundled en premier, user ensuite).
    """
    skills: dict[str, LoadedSkill] = {}

    for search_dir in _search_paths():
        for skill_dir in sorted(search_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name.startswith((".", "_")):
                continue

            skill = _load_skill_from_dir(skill_dir)
            if skill is None:
                continue

            # Les skills user écrasent les bundled si même nom
            existing = skills.get(skill.name)
            if existing:
                logger.debug(
                    "Skill '%s' : remplacement bundled par user version", skill.name
                )
            skills[skill.name] = skill

    active = sum(1 for s in skills.values() if s.status == SkillStatus.ACTIVE)
    logger.info(
        "Skills découvertes : %d total, %d actives, %d en erreur",
        len(skills),
        active,
        len(skills) - active,
    )
    return list(skills.values())
