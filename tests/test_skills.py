"""Tests du système de skills."""
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.types import SkillMetadata, LoadedSkill, SkillStatus
from skills import registry, executor


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_registry():
    registry.reset()
    yield
    registry.reset()


def make_skill_dir(tmp_path: Path, name: str, md_content: str, py_content: str = "") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(md_content)
    if py_content:
        (d / "skill.py").write_text(py_content)
    return d


# ── Tests SkillMetadata ───────────────────────────────────────────────────────

def test_metadata_from_markdown_basic():
    md = "# My Skill\n\nThis skill does something useful.\n"
    meta = SkillMetadata.from_markdown(md, "my-skill")
    assert meta.name == "My Skill"
    assert "useful" in meta.description


def test_metadata_from_markdown_html_comments():
    md = """# Test Skill
<!-- version: 2.0.0 -->
<!-- author: Béa -->
<!-- requires_approval: true -->
<!-- tags: a, b, c -->

Description here.
"""
    meta = SkillMetadata.from_markdown(md, "test")
    assert meta.version == "2.0.0"
    assert meta.author == "Béa"
    assert meta.requires_approval is True
    assert meta.tags == ["a", "b", "c"]


# ── Tests Loader ──────────────────────────────────────────────────────────────

def test_loader_ignores_dirs_without_skill_md(tmp_path):
    (tmp_path / "no-skill").mkdir()
    from skills.loader import _load_skill_from_dir
    result = _load_skill_from_dir(tmp_path / "no-skill")
    assert result is None


def test_loader_loads_skill_md_only(tmp_path):
    skill_dir = make_skill_dir(tmp_path, "simple", "# Simple\n\nA simple skill.")
    from skills.loader import _load_skill_from_dir
    skill = _load_skill_from_dir(skill_dir)
    assert skill is not None
    assert skill.name == "Simple"
    assert skill.status == SkillStatus.ACTIVE
    assert skill.execute_fn is None


def test_loader_loads_skill_py(tmp_path):
    py = "async def execute(input, context=None):\n    return 'ok'\n"
    skill_dir = make_skill_dir(tmp_path, "with-impl", "# WithImpl\n\nHas implementation.", py)
    from skills.loader import _load_skill_from_dir
    skill = _load_skill_from_dir(skill_dir)
    assert skill is not None
    assert skill.execute_fn is not None


def test_loader_marks_error_on_bad_py(tmp_path):
    py = "this is not valid python!!!"
    skill_dir = make_skill_dir(tmp_path, "broken", "# Broken\n\nBroken skill.", py)
    from skills.loader import _load_skill_from_dir
    skill = _load_skill_from_dir(skill_dir)
    assert skill is not None
    assert skill.status == SkillStatus.ERROR


# ── Tests Registry ────────────────────────────────────────────────────────────

def test_registry_discover_bundled():
    """Vérifie que les skills bundled sont découvertes."""
    registry.initialize()
    skills = registry.list_skills()
    assert len(skills) >= 1  # Au moins 'Summarize' bundlée


def test_registry_list_for_llm():
    registry.initialize()
    schemas = registry.list_for_llm()
    assert all("name" in s and "description" in s for s in schemas)


def test_registry_reload():
    registry.initialize()
    count1 = len(registry.list_skills())
    registry.reload()
    count2 = len(registry.list_skills())
    assert count1 == count2  # stable après reload


# ── Tests Executor ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_run_unknown_skill():
    registry.initialize()
    result = await executor.run_skill("nonexistent", {})
    assert not result["success"]
    assert "introuvable" in result["error"]


@pytest.mark.asyncio
async def test_executor_run_summarize_bundled():
    registry.initialize()
    skill = registry.get("Summarize")
    if skill is None:
        pytest.skip("Skill 'Summarize' non disponible")

    result = await executor.run_skill("Summarize", {
        "text": "Sentence one. Sentence two. Sentence three. Sentence four.",
        "max_sentences": 2,
    })
    assert result["success"]
    assert result["output"]


@pytest.mark.asyncio
async def test_executor_run_doc_only_skill(tmp_path):
    """Une skill sans skill.py retourne sa description."""
    skill_dir = make_skill_dir(tmp_path, "doc-only", "# DocOnly\n\nPure documentation.")

    from skills.loader import _load_skill_from_dir
    skill = _load_skill_from_dir(skill_dir)

    with patch.dict("skills.registry._SKILLS", {"DocOnly": skill}):
        from skills import registry as r
        r._initialized = True
        result = await executor.run_skill("DocOnly", {})

    assert result["success"]
    assert "documentation-only" in result["output"]
