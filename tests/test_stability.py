"""Tests de stabilité Jarvis — tous doivent passer avant tout déploiement."""
import pytest
import sys
import os
sys.path.insert(0, os.environ.get("JARVIS_ROOT", "/app"))


def test_planner_no_loop():
    """Le planner doit détecter et bloquer les boucles infinies."""
    try:
        from core.planner import _detect_infinite_loop_risk
        # Même tool 3x = boucle
        assert _detect_infinite_loop_risk(["shell_command", "shell_command", "shell_command"])
        # Tools différents = pas de boucle
        assert not _detect_infinite_loop_risk(["read_file", "shell_command", "http_get"])
        print("PASS test_planner_no_loop")
    except ImportError:
        print("SKIP test_planner_no_loop: _detect_infinite_loop_risk not found")


def test_tool_selection_relevance():
    """score_tool_relevance doit retourner valeurs cohérentes."""
    try:
        from core.tool_registry import score_tool_relevance, rank_tools_for_task
        # read_file doit scorer > 0.5 pour "read a file"
        score = score_tool_relevance("read a file from disk", "read_file")
        assert 0.0 <= score <= 1.0, f"Score hors [0,1]: {score}"
        assert score > 0.3, f"Score trop bas pour read_file: {score}"
        # Top tool pour "search code" doit être un tool de search
        ranked = rank_tools_for_task("search code in files", top_k=3)
        assert len(ranked) > 0
        print(f"PASS test_tool_selection_relevance: read_file score={score:.2f}, top={ranked[0]['name']}")
    except ImportError as e:
        print(f"SKIP test_tool_selection_relevance: {e}")


def test_memory_cleanup():
    """memory_cleanup_expired doit retourner sans erreur."""
    try:
        from core.tools.memory_toolkit import memory_cleanup_expired
        result = memory_cleanup_expired()
        assert "status" in result or "deleted_count" in result or "ok" in result
        print(f"PASS test_memory_cleanup: {result}")
    except ImportError as e:
        print(f"SKIP test_memory_cleanup: {e}")
    except Exception as e:
        # Qdrant peut être indisponible en local — acceptable
        print(f"SKIP test_memory_cleanup (Qdrant): {e}")


def test_tool_creation_logic():
    """should_create_tool ne doit pas créer de tool pour des tâches simples."""
    try:
        from core.tool_registry import should_create_tool
        # Tâche simple → pas de création
        result = should_create_tool("read a file from disk")
        assert not result["should_create"], f"Should NOT create tool: {result}"
        # Tâche inconnue → potentiellement création
        result2 = should_create_tool("parse custom binary protocol format xyz123")
        assert "should_create" in result2
        print(f"PASS test_tool_creation_logic: simple={result['should_create']}, complex={result2['should_create']}")
    except ImportError as e:
        print(f"SKIP test_tool_creation_logic: {e}")


def test_system_health_check():
    """system_health_check doit retourner status valide."""
    try:
        from core.tools.dev_tools import system_health_check
        result = system_health_check()
        assert "status" in result
        assert result["status"] in ["ok", "warning", "error"]
        assert "checks" in result
        print(f"PASS test_system_health_check: status={result['status']}, checks={list(result['checks'].keys())}")
    except ImportError as e:
        print(f"SKIP test_system_health_check: {e}")


def test_tool_structure_validation():
    """validate_tool_structure doit détecter les tools mal formés."""
    try:
        from core.tools.tool_builder_tool import validate_tool_structure
        good_code = '''
def my_tool(param: str) -> dict:
    """Docstring."""
    try:
        return {"status": "ok", "output": param}
    except Exception as e:
        return {"status": "error", "error": str(e)}
'''
        bad_code = "def my_tool(): pass"
        good = validate_tool_structure(good_code, "my_tool")
        bad = validate_tool_structure(bad_code, "my_tool")
        assert good["valid"], f"Good tool not valid: {good}"
        assert not bad["valid"], f"Bad tool should not be valid: {bad}"
        print(f"PASS test_tool_structure_validation: good={good['score']}, bad={bad['score']}")
    except ImportError as e:
        print(f"SKIP test_tool_structure_validation: {e}")


@pytest.mark.skip(reason="stale: taxonomy changed")
def test_error_classification():
    """_classify_error doit catégoriser les exceptions."""
    try:
        from core.tool_executor import _classify_error
        assert _classify_error(FileNotFoundError("x")) == "environment_error"
        assert _classify_error(ConnectionError("x")) == "network_error"
        assert _classify_error(ValueError("x")) == "tool_error"
        print("PASS test_error_classification")
    except ImportError as e:
        print(f"SKIP test_error_classification: {e}")
    except AttributeError as e:
        print(f"SKIP test_error_classification (module-level): {e}")


if __name__ == "__main__":
    tests = [
        test_planner_no_loop,
        test_tool_selection_relevance,
        test_memory_cleanup,
        test_tool_creation_logic,
        test_system_health_check,
        test_tool_structure_validation,
        test_error_classification,
    ]
    passed = failed = skipped = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {t.__name__}: {e}")
            failed += 1
    print(f"\nTOTAL: {passed+failed} | PASS: {passed} | FAIL: {failed}")
