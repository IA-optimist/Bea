# Béa — Developer Preview

> **Status: Developer Preview (limited)**
> Not yet stable for production use. APIs and behaviour may change between releases.

Béa is a self-improving multi-agent platform: mission orchestration, persistent
vector memory, provider routing, and a gated self-improvement loop.

## Ce que Béa sait faire aujourd'hui

| Capacité | Statut |
|----------|--------|
| Missions code (forge-builder) — génération Python + syntax check + test proof | ✅ Validé |
| Missions recherche (scout-research) — analyse de documents locaux | ✅ Validé |
| Missions conseil structuré (shadow-advisor) — JSON strict | ✅ Validé |
| Pipeline multi-agent avec mémoire vectorielle (Qdrant) | ✅ Validé |
| Provider routing advisory (non-prescriptif) : OpenRouter + Ollama | ✅ Validé |
| Bot Telegram : texte, photos, analyse YouTube | ✅ Validé |
| AutoContentFlow : génération SEO asynchrone (Railway) | ✅ En production |
| CVOptimIA : SaaS CV/ATS FR | ✅ En cours |

## Ce que Béa ne sait pas encore faire

- **Router automatique** basé sur benchmark : advisory seulement (`runtime_enforced=false`)
- **CI enforcement** du benchmark réel (pas encore sur PR)
- **APK mobile v3** : Flutter utilise /api/v3 partout, mais build non validé en CI
- **Multi-tenant** sans review manuelle
- **Self-improvement autonome** sans gate opérateur (opt-in uniquement)
- **Rate-limiting** intégré sur l'API (blocker avant production)

## Prérequis

- Python 3.11+
- Docker Desktop (Postgres, Redis, Qdrant)
- OpenRouter API key (compte gratuit suffisant pour dev) — `sk-or-v1-...`
- Ollama (optionnel, pour fallback local : `gemma4:12b`)

## Quick Start

Voir [GETTING_STARTED.md](GETTING_STARTED.md).

## Modèles / Providers

| Provider | Modèle | Forge-builder | Scout-research | Shadow-advisor |
|----------|--------|:---:|:---:|:---:|
| OpenRouter | gpt-oss-120b:free | ✅ 1.0 | ✅ 1.0 | ✅ 1.0 |
| Ollama | gemma4:12b | ❌ 0.0 | ✅ 1.0 | ❌ 0.33 |

Recommandation advisory : **OpenRouter pour les 3 rôles** (non enforced au runtime).

## Avertissement self-improvement

Le module d'auto-amélioration (`BEA_CONTINUOUS_IMPROVEMENT=1`) est désactivé par
défaut. Quand activé, chaque cycle passe par un gate kernel R4 (approbation opérateur).
`BEA_SKIP_IMPROVEMENT_GATE` bypass TOTAL — **ne jamais utiliser en production**.

## Sécurité

Voir [SECURITY_MODEL.md](SECURITY_MODEL.md).

## Limites connues

- Ollama `gemma4:12b` : `artifact_invalid` sur forge-builder, `json_invalid` sur shadow-advisor
- `model_used` reflète ce qu'on envoie à OpenRouter, pas ce qu'il exécute côté serveur
- Sessions chat fast-path ne trackent pas `model_used`
- Mémoire vectorielle Qdrant nécessite Docker actif
- Pas de rate-limiting intégré (à implémenter avant exposition publique)
- Endpoints `/api/v1` maintenus côté serveur jusqu'à validation APK v3 complète

## Contribuer

Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) et [docs/STATUS.md](docs/STATUS.md).
Issues et PRs bienvenues après avoir lu [SECURITY_MODEL.md](SECURITY_MODEL.md).
