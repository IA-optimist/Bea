import ast
from pathlib import Path


def test_pytest_does_not_globally_ignore_deprecation_warnings():
    content = Path('pytest.ini').read_text(encoding='utf-8')

    assert 'ignore::DeprecationWarning' not in content


def test_causal_module_uses_logger_for_validation_output():
    path = Path('core/orchestration/causal_module.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    print_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'print'
    ]

    assert print_calls == []
    baseline = Path('quality/legacy_runtime_prints.txt').read_text(encoding='utf-8')
    assert 'core/orchestration/causal_module.py' not in baseline
    ruff = Path('ruff.toml').read_text(encoding='utf-8')
    assert '"core/orchestration/causal_module.py" = ["T201"]' not in ruff


def test_hyphenated_subprojects_are_documented_as_non_importable():
    content = Path('docs/architecture/MAJOR_DEBT_MAP.md').read_text(encoding='utf-8')

    assert 'orchestrate-cli/' in content
    assert 'orchestrate-mobile/' in content
    assert 'non-importable' in content
    assert 'sub-projects' in content


def test_requirements_lock_has_ci_drift_check():
    ci = Path('.github/workflows/ci.yml').read_text(encoding='utf-8')
    script = Path('scripts/check_requirements_lock.py')

    assert script.exists()
    assert 'scripts/check_requirements_lock.py' in ci
    assert 'requirements.lock' in ci


def test_detect_secrets_baseline_is_enforced_by_precommit_ci():
    precommit = Path('.pre-commit-config.yaml').read_text(encoding='utf-8')
    workflow = Path('.github/workflows/pre-commit.yml').read_text(encoding='utf-8')

    assert 'detect-secrets' in precommit
    assert '.secrets.baseline' in precommit
    assert 'pre-commit run --all-files' in workflow
