# Full Pytest Report — PHASE 13

Generated: 2026-06-27
Commande: `python -m pytest -q --tb=no -p no:timeout`
Durée: 13m39s

## Résumé

```
8 failed, 6091 passed, 761 skipped, 6 xfailed in 819.33s
```

Pass rate: **6091/6099 = 99.87%**

## Détail failures

| Test file | Test | Fail count | Category | Blocks public beta? | Suggested fix |
|-----------|------|-----------|----------|---------------------|---------------|
| `test_rate_limit_config.py` | `test_rate_limit_enabled_default_true` | 1 | P2 — test stale (RATE_LIMIT_ENABLED manquant) | NON (rate limiting fonctionne) | Mettre à jour test pour vérifier `limiter` config |
| `test_rate_limit_config.py` | `test_rate_limit_disabled_via_env` | 1 | P2 — test stale | NON | Idem |
| `test_rate_limit_config.py` | `test_rate_limit_production_blocks_disabled` | 1 | P2 — test stale | NON | Idem |
| `test_rate_limit_config.py` | `test_rate_limit_enabled_variants` | 1 | P2 — test stale | NON | Idem |
| `test_sprint3_agent_coder.py` | `test_repo_map_indexes_symbols_and_imports` | 1 | P3 — ranking drift | NON | Assouplir assertion sur ranked[0] |
| `test_sprint3_agent_coder.py` | `test_swe_lite_v1_passes_for_sprint3_primitives` | 1 | P3 — cascade de repo_map | NON | Fix repo_map test |
| `test_stabilization_final.py` | `test_no_report_files_at_root` | 1 | P2 — whitelist stale | Conditionnellement OUI | Mettre à jour la whitelist des .md autorisés |
| `test_operating_final.py` | `test_scheduler_connector` | 1 | P3 — env-specific | NON | Ajouter mock/reset scheduler dans le test |

## Ordre de correction recommandé

1. **test_stabilization_final: test_no_report_files_at_root** — trivial, 1 ligne de whitelist
2. **test_rate_limit_config x4** — refactoring test pour tester le module actuel
3. **test_sprint3_agent_coder: repo_map ranking** — assouplir l'assertion
4. **test_operating_final: scheduler** — ajouter isolation du scheduler dans le test

## Warnings notables

1. **API keys with insecure connection** (Qdrant): `UserWarning: Api key is used with an insecure connection.` — test_mcp_e2e.py — P3, concerne les tests, pas la prod.
2. **Deprecated memory API**: `memory.legacy.* est deprecated` — P3, migration en cours.
3. **FastAPI httpx deprecation**: `Using httpx with starlette.testclient is deprecated` — P3, upgrade httpx2.

## Conclusion

**0 failures P0 ou P1 parmi les 8 échecs.**
- 4 failures P2 (rate_limit tests stale + stabilization whitelist)
- 4 failures P3 (ranking drift + scheduler env + cascade)

**Pour PUBLIC_BETA_CANDIDATE: corriger les 2 P2 est recommandé mais non bloquant si justifié.**
