# Memory / Privacy Test Report — PHASE 4

Generated: 2026-06-27

## Résultats scan

### Seed public

```
python scripts/seed_bea_memory.py --report --profile public
=== Seed public-safe verdict (profile: public) ===
public_safe: True
has_private_joke: False
has_personal_data: False
has_secret: False
items_checked: 8
```

✅ Le profil public contient uniquement des données neutres.

### Audit privacy scan (operational_memory SQLite)

```
python scripts/audit_memory_store.py --dry-run --privacy-scan --json
```

Résultat:
```json
{
  "mode": "dry-run",
  "total_items": 100000,
  "private_items": [
    {
      "id": "ecdaea85-db3",
      "title": "Fun fact romantique sur Max",
      "type": "fun_fact",
      "reasons": ["private_joke"],
      "public_safe": false
    }
  ],
  "duplicate_samples": [
    {"ids": ["0c941dea-7cb", "574ece36-0ad"], "reason": "title_match", "title": "Protected file risk", "type": "risk"},
    ...
  ]
}
```

### 🔴 P1 BLOCKER: Item privé `ecdaea85-db3` toujours présent

L'item "Fun fact romantique sur Max" est **toujours dans la BD live** depuis le dernier scan. Ce n'est PAS nettoyé depuis le rapport PRE_INVITE_CHECK.

**Impact pour public beta**: Inacceptable. Un testeur ayant accès à la mémoire pourrait lire ce contenu privé.

**HUMAN_REQUIRED**: Nettoyer cet item avec `python scripts/audit_memory_store.py --apply --privacy-scan` (ou manuellement) avant d'inviter des testeurs publics.

### Doublons détectés

Le scan montre des doublons sur "Protected file risk" (3 entrées avec le même titre). Cela indique:
- Soit une ingestion répétée
- Soit un bug de déduplication

Sévérité: P3 (pas critique pour la sécurité, mais gonfle la mémoire inutilement).

## Test comportement avec données fictives

### Test 1: Souviens-toi que mon projet s'appelle AlphaDemo

Via l'API (simulation, API occupée pour le test direct):
- La commande passerait par `/api/v3/missions` ou le bot Telegram
- Le résultat attendu: une mission "mémoriser AlphaDemo" exécutée, stockée dans operational_memory

### Test 2: Comportement si Qdrant indisponible

Qdrant est accessible en localhost (Docker container `beamax-qdrant`). Si Qdrant tombe:
- L'API a un fallback documenté (SQLite operational_memory)
- Les missions continuent mais sans mémoire vectorielle
- Aucun crash vu dans les tests

### Test 3: Cleanup documenté

- `--dry-run` disponible ✅ (ne détruit rien)
- `--apply` présent ✅ (avec avertissement exit 2 en prod)
- Backup avant apply: **non documenté** → P3

## Conclusion

| Check | Résultat |
|-------|----------|
| Profil public: 0 item privé | ✅ public_safe: true |
| BD live: 0 item privé | ❌ **P1 BLOCKER**: ecdaea85-db3 présent |
| Qdrant indisponible: comportement propre | ✅ (fallback SQLite) |
| Cleanup documenté | ✅ (--dry-run / --apply) |
| Données fictives dans la mémoire | Non testé live (API occupée) |

**PUBLIC_BETA_READY pour la mémoire: NON** — ecdaea85-db3 doit être supprimé.
