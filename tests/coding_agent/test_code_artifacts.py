from __future__ import annotations

from pathlib import Path

from agents.crew import extract_file_actions
from core.coding_agent.code_artifacts import (
    extract_python_source,
    materialize_python_artifact,
    validate_python_file,
    validate_python_source,
)


def test_extract_python_source_prefers_fenced_code():
    response = """Voici le fichier.

```python
from hashlib import sha256


def sha256_file(path: str) -> str:
    return sha256(path.encode()).hexdigest()
```

Texte explicatif après le code.
"""

    source = extract_python_source(response)

    assert "Texte explicatif" not in source
    assert "def sha256_file" in source
    assert source.strip().startswith("from hashlib import sha256")


def test_extract_python_source_accepts_plain_python():
    source_text = "from pathlib import Path\n\n\ndef ping() -> str:\n    return 'pong'\n"

    source = extract_python_source(source_text)

    assert source == source_text.strip()


def test_extract_python_source_rejects_markdown_only():
    response = """## Résumé

- Aucun code exploitable.
- Juste du texte.
"""

    assert extract_python_source(response) == ""


def test_materialize_python_artifact_creates_compilable_file(tmp_path):
    response = """```python
from __future__ import annotations


def sha256_file(path: str) -> str:
    return path[::-1]
```"""

    result = materialize_python_artifact(response, tmp_path / "sha256_file.py")

    assert result.ok is True
    assert result.status == "COMPLETED"
    assert Path(result.path).exists()
    assert validate_python_file(result.path)[0] is True


def test_materialize_python_artifact_rejects_syntax_error(tmp_path):
    response = """```python
def broken(
    return 1
```"""

    result = materialize_python_artifact(response, tmp_path / "broken.py")

    assert result.ok is False
    assert result.status == "FAILED"
    assert "syntax" in result.message.lower()


def test_extract_file_actions_strips_markdown_from_python_blocks():
    response = """### Fichier: workspace/sha256_file.py
```python
from hashlib import sha256


def sha256_file(path: str) -> str:
    return sha256(path.encode()).hexdigest()
```

## Utilisation
Ne pas inclure ce texte dans le .py.
"""

    actions = extract_file_actions(response)

    assert len(actions) == 1
    assert actions[0]["target"] == "workspace/sha256_file.py"
    assert "Utilisation" not in actions[0]["content"]
    assert actions[0]["content"].startswith("from hashlib import sha256")


def test_validate_python_source_detects_syntax_error():
    ok, error = validate_python_source("def broken(:\n    pass\n")

    assert ok is False
    assert error
