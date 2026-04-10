"""Tests for core/static_analysis.py — lightweight code analysis."""
import tempfile
import os
import pytest

# Skip all tests - core/static_analysis.py not yet implemented
# TODO: Implement static analysis module or remove these tests
pytestmark = pytest.mark.skip(reason="core/static_analysis module not implemented")


def test_import():
    from core.static_analysis import (
        analyze_file, analyze_directory,
        FileAnalysis, DirectoryAnalysis,
    )


# ── FileAnalysis dataclass ────────────────────────────────────

def test_file_analysis_issue_count():
    from core.static_analysis import FileAnalysis
    fa = FileAnalysis(
        path="test.py",
        unused_imports=["os"],
        bare_excepts=[10],
        except_pass=[20, 30],
    )
    assert fa.issue_count() == 4


def test_file_analysis_to_dict():
    from core.static_analysis import FileAnalysis
    fa = FileAnalysis(path="test.py", lines=100, syntax_valid=True)
    d = fa.to_dict()
    assert d["path"] == "test.py"
    assert d["syntax_valid"] is True


# ── analyze_file ──────────────────────────────────────────────

def test_analyze_nonexistent_file():
    from core.static_analysis import analyze_file
    result = analyze_file("/nonexistent_12345.py")
    assert not result.syntax_valid
    assert "not found" in result.error.lower()


def test_analyze_valid_file():
    from core.static_analysis import analyze_file
    code = '''
"""Module docstring."""
import os
import json

def public_function(x: int) -> str:
    """Has docstring."""
    return str(x)

def no_typehint(x):
    return x

class MyClass:
    """Has docstring."""
    pass
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        result = analyze_file(path)
        assert result.syntax_valid
        assert result.functions >= 2
        assert result.classes >= 1
        # 'json' is imported but never used
        assert any("json" in u for u in result.unused_imports)
        # no_typehint missing return annotation
        assert any("no_typehint" in m for m in result.missing_typehints)
    finally:
        os.unlink(path)


def test_analyze_syntax_error():
    from core.static_analysis import analyze_file
    code = "def broken(\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        result = analyze_file(path)
        assert not result.syntax_valid
        assert "SyntaxError" in result.error
    finally:
        os.unlink(path)


def test_analyze_detect_bare_except():
    from core.static_analysis import analyze_file
    code = '''
try:
    x = 1
except:
    pass
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        result = analyze_file(path)
        assert len(result.bare_excepts) >= 1
        assert len(result.except_pass) >= 1
    finally:
        os.unlink(path)


def test_analyze_detect_complexity():
    from core.static_analysis import analyze_file
    # Create a function with high complexity
    code = '''
def complex_function(x):
    if x > 0:
        if x > 1:
            if x > 2:
                if x > 3:
                    for i in range(x):
                        while i > 0:
                            if i % 2:
                                if i % 3:
                                    if i % 5:
                                        if i % 7:
                                            pass
                                        else:
                                            pass
                            i -= 1
    return x
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        result = analyze_file(path)
        assert len(result.complexity_hotspots) >= 1
        assert result.complexity_hotspots[0]["name"] == "complex_function"
    finally:
        os.unlink(path)


def test_analyze_detect_missing_docstring():
    from core.static_analysis import analyze_file
    code = '''
def no_docs():
    return 1

def has_docs():
    """Has a docstring."""
    return 2
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        result = analyze_file(path)
        assert any("no_docs" in m for m in result.missing_docstrings)
        assert not any("has_docs" in m for m in result.missing_docstrings)
    finally:
        os.unlink(path)


# ── analyze_directory ─────────────────────────────────────────

def test_analyze_directory():
    from core.static_analysis import analyze_directory
    # Analyze the core/static_analysis.py file itself
    result = analyze_directory("core/", exclude={"tests/", "__pycache__/"})
    assert len(result.files) > 0
    assert result.total_lines > 0
    assert "core/" in result.summary


def test_directory_analysis_worst_files():
    from core.static_analysis import DirectoryAnalysis, FileAnalysis
    da = DirectoryAnalysis(
        path="test",
        files=[
            FileAnalysis(path="a.py", unused_imports=["x", "y", "z"]),
            FileAnalysis(path="b.py", unused_imports=["x"]),
            FileAnalysis(path="c.py"),
        ],
    )
    worst = da.worst_files(2)
    assert worst[0].path == "a.py"  # 3 issues
    assert len(worst) == 2
