# Dependency Security Audit — 2026-06-01

Source: `pip-audit -r requirements.txt`

## Findings (10 vulnérabilités / 6 packages)

- `python-dotenv==1.0.0` → `CVE-2026-28684` (fix: `1.2.2`)
- `lxml==5.1.0` → `PYSEC-2026-87` (fix: `6.1.0`)
- `cryptography==43.0.1` → `PYSEC-2026-35`, `CVE-2024-12797`, `CVE-2026-26007` (fixes: `44.0.1` à `46.0.6`)
- `pytest==7.4.4` → `CVE-2025-71176` (fix: `9.0.3`)
- `langchain-core==1.2.31` → `CVE-2026-44843` (fix: `0.3.85` ou `1.3.3` selon ligne majeure)
- `starlette==0.35.1` → `PYSEC-2026-161`, `CVE-2024-47874`, `CVE-2025-54121` (fixes: `0.40.0` à `1.0.1`)

## Priorisation proposée

## P0 (immédiat)
1. `cryptography`
2. `starlette` (et cohérence avec version `fastapi`)
3. `python-dotenv`

## P1 (court terme)
4. `lxml`
5. `pytest`

## P2 (à cadrer)
6. `langchain-core` (risque de breaking changes selon API utilisée)

## Stratégie de remédiation

1. Ouvrir des PRs de mise à niveau **par lot réduit**.
2. Exécuter après chaque lot:
   - `ruff check .`
   - `pytest -q tests/test_v1_invariants.py tests/test_tool_registry.py tests/test_policy_engine.py`
   - `pytest --collect-only -q`
3. Bloquer merge si régression fonctionnelle ou collecte cassée.
4. Mettre à jour `requirements.lock` en cohérence avec les versions validées.

## Commande exécutée

```bash
python -m pip install pip-audit -q
pip-audit -r requirements.txt
```
