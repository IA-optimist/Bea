# bea_team — Agent Definitions

Les 6 agents de l'équipe BeaMax en format Claude Code (Markdown + frontmatter YAML).

## Structure

```
bea_team/
├── architect.md   # Analyse + specs. Read-only, jamais de code.
├── coder.md       # Implémentation selon specs précises.
├── reviewer.md    # Code review adversarial (Anthropic VerificationAgent style).
├── qa.md          # Tests end-to-end + vérification live.
├── devops.md      # Déploiement, Docker, CI/CD, Caddy, systemd.
├── watcher.md     # Surveillance continue, détection de régressions.
└── README.md      # Ce fichier.
```

## Pipeline typique

```
architect → coder → reviewer → qa → devops
                                        ↑
                              watcher (surveillance continue)
```

1. **architect** analyse le codebase et produit une spec (fichier + ligne + changement exact)
2. **coder** implémente la spec à la lettre, commit, reporte le SHA
3. **reviewer** fait une review adversariale — APPROVE / REQUEST_CHANGES / BLOCK
4. **qa** exécute les tests, frappe les endpoints en live — ne passe pas sur "ça a l'air bon"
5. **devops** déploie avec checklist complète, vérifie l'état post-déploiement
6. **watcher** surveille en continu, escalade les anomalies

## Format des fichiers agents

Chaque agent est un fichier `.md` avec frontmatter YAML :

```yaml
---
name: <nom>
description: "Description + quand utiliser. Use when..."
tools: [list, of, tools]
model: inherit
effort: low | medium | high
maxTurns: <n>
memory: project
---

System prompt...
```

## Principes communs

- **Pas de faux "done"** — rien n'est PROVEN sans preuves (SHA, test output, HTTP response)
- **Adversarial by default** — reviewer et qa cherchent à trouver des bugs, pas à approuver
- **Fail-open** — tous les appels externes en try/except avec safe defaults
- **Chaîne de traçabilité** — chaque changement est lié à un SHA git
- **Escalade explicite** — chaque agent sait à qui escalader quand il est bloqué

## Utilisation avec Claude Code

```bash
# Analyser une feature avant implementation
claude --agent architect "Analyse l'impact d'ajouter un cache Redis pour les sessions"

# Implémenter selon une spec
claude --agent coder "Implémenter le cache Redis selon la spec de architect (voir workspace/specs/redis-cache.md)"

# Review du diff produit
claude --agent reviewer "Review du diff sur la branche bea/redis-cache"

# QA avant merge
claude --agent qa "Valider les tests pour bea/redis-cache"

# Déployer
claude --agent devops "Déployer bea/redis-cache en production"

# Check de santé
claude --agent watcher "Rapport de surveillance post-déploiement"
```

## Règles de merge

Un merge vers `master` nécessite :
- [ ] reviewer: **APPROVE**
- [ ] qa: **PASS** (exécuté, pas juste lu)
- [ ] devops: **READY**

Un seul **BLOCK** de reviewer ou **FAIL** de qa = merge refusé.

## Agents Python (legacy)

Les fichiers `.py` sont les implémentations originales utilisées par le MetaOrchestrator Python.  
Les fichiers `.md` sont le format Claude Code pour utilisation directe avec `claude --agent`.  
Les deux coexistent — les `.md` ne remplacent pas les `.py`.
