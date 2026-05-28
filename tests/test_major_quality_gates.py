from pathlib import Path


def _ci_mypy_block() -> str:
    content = Path('.github/workflows/ci.yml').read_text(encoding='utf-8')
    return content.split('  mypy:', 1)[1].split('  build:', 1)[0]


def test_ci_coverage_tracks_core_api_and_kernel():
    content = Path('.github/workflows/ci.yml').read_text(encoding='utf-8')

    assert '--cov=core' in content
    assert '--cov=api' in content
    assert '--cov=kernel' in content
    assert 'COVERAGE_FAIL_UNDER' in content


def test_ci_mypy_uses_blocking_delta_gate():
    block = _ci_mypy_block()

    assert 'continue-on-error: true' not in block
    assert 'mypy core api kernel' in block
    assert 'scripts/check_mypy_baseline.py' in block
    assert 'quality/mypy-baseline.json' in block


def test_ruff_blocks_new_runtime_prints_with_legacy_baseline():
    ruff = Path('ruff.toml').read_text(encoding='utf-8')
    baseline = Path('quality/legacy_runtime_prints.txt')

    assert '"T201"' in ruff
    assert 'legacy_runtime_prints.txt' in ruff
    assert baseline.exists()
    baseline_content = baseline.read_text(encoding='utf-8')
    assert 'business/legal/compliance_checker.py' in baseline_content
    assert 'core/orchestration/causal_module.py' not in baseline_content


def test_agents_crew_has_no_pass_only_exception_handlers():
    content = Path('agents/crew.py').read_text(encoding='utf-8')

    assert 'except Exception: pass' not in content
    assert 'except Exception as e: pass' not in content


def test_architecture_debt_map_tracks_major_monoliths_and_canonical_modules():
    content = Path('docs/architecture/MAJOR_DEBT_MAP.md').read_text(encoding='utf-8')

    for path in (
        'core/meta_orchestrator.py',
        'core/connectors/_base.py',
        'core/mission_system.py',
        'api/routes/missions.py',
        'agents/crew.py',
    ):
        assert path in content

    for concept in ('Agent', 'Registry', 'Contracts', 'Main entrypoints'):
        assert concept in content
