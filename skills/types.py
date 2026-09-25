"""Types du système de skills Béa."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Awaitable, Any


class SkillStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class SkillMetadata:
    """Métadonnées extraites du SKILL.md d'une skill."""
    name: str
    description: str
    version: str = "0.1.0"
    author: str = "unknown"
    requires_approval: bool = False
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_markdown(cls, content: str, skill_name: str) -> "SkillMetadata":
        """Parse les métadonnées depuis un fichier SKILL.md."""
        lines = content.splitlines()
        meta: dict = {"name": skill_name, "description": "", "tags": []}

        # Titre H1 → name
        for line in lines:
            if line.startswith("# "):
                meta["name"] = line[2:].strip()
                break

        # Premier paragraphe non-titre → description
        in_desc = False
        desc_lines: list[str] = []
        for line in lines:
            if line.startswith("#"):
                if desc_lines:
                    break
                in_desc = True
                continue
            if in_desc and line.strip():
                desc_lines.append(line.strip())
            elif in_desc and not line.strip() and desc_lines:
                break
        meta["description"] = " ".join(desc_lines)

        # Métadonnées YAML-like dans les commentaires HTML <!-- key: value -->
        import re
        for m in re.finditer(r"<!--\s*(\w+):\s*(.+?)\s*-->", content):
            key, val = m.group(1), m.group(2)
            if key == "version":
                meta["version"] = val
            elif key == "author":
                meta["author"] = val
            elif key == "requires_approval":
                meta["requires_approval"] = val.lower() in ("true", "yes", "1")
            elif key == "tags":
                meta["tags"] = [t.strip() for t in val.split(",")]

        return cls(**meta)


@dataclass
class LoadedSkill:
    """Une skill chargée et prête à l'emploi."""
    metadata: SkillMetadata
    skill_dir: Path
    status: SkillStatus = SkillStatus.ACTIVE
    execute_fn: Callable[..., Awaitable[Any]] | None = None
    tool_instance: Any | None = None  # BEATool si la skill expose un outil
    error: str | None = None

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description
