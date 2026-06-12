#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# clean_workspace.sh — hygiène du dossier local (audit 2026-06).
#
# Usage :
#   make clean-workspace                # exécute
#   DRY_RUN=1 make clean-workspace      # montre sans toucher
#   KEEP_DAYS=30 make clean-workspace   # garde les builds < 30 jours
#
# Politique : ARCHIVER, ne jamais supprimer définitivement.
#   - workspace/builds/* plus vieux que KEEP_DAYS jours
#       → déplacés vers workspace/.archive/<date>/
#   - caches Python (__pycache__, .pytest_cache, pytest-cache-files-*)
#       → supprimés (régénérables)
#   - .venv, .venv-c4-prep, beamax_app/build, node_modules
#       → JAMAIS touchés ici, seulement signalés (suppression manuelle
#         assumée : `rm -rf .venv-c4-prep` quand la prep C4 est finie).
# ──────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

KEEP_DAYS="${KEEP_DAYS:-14}"
DRY_RUN="${DRY_RUN:-0}"
ARCHIVE_DIR="workspace/.archive/$(date +%Y-%m-%d)"

run() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo "── 1/3 Caches Python (régénérables) ──"
find . -type d -name "__pycache__" \
    -not -path "./.venv*" -not -path "*/node_modules/*" -print | while read -r d; do
  run rm -rf "$d"
done
for d in .pytest_cache pytest-cache-files-*; do
  [ -e "$d" ] && run rm -rf "$d"
done

echo "── 2/3 Archivage workspace/builds (> ${KEEP_DAYS} jours) ──"
if [ -d workspace/builds ]; then
  found=0
  while read -r b; do
    found=1
    [ "$DRY_RUN" = "1" ] || mkdir -p "$ARCHIVE_DIR"
    run mv "$b" "$ARCHIVE_DIR/"
  done < <(find workspace/builds -mindepth 1 -maxdepth 1 -type d -mtime "+${KEEP_DAYS}")
  [ "$found" = "0" ] && echo "(rien à archiver)"
else
  echo "(workspace/builds absent)"
fi

echo "── 3/3 Signalements (suppression manuelle si voulu) ──"
for p in .venv-c4-prep sqlite_mcp_server.db _p3_codex.py _p3r2_codex.py \
         beamax_app/build workspace/business/autocontentflow/mvp/node_modules; do
  if [ -e "$p" ]; then
    sz=$(du -sh "$p" 2>/dev/null | cut -f1)
    echo "  présent : $p (${sz:-?})"
  fi
done

echo "✅ clean_workspace terminé (DRY_RUN=$DRY_RUN, KEEP_DAYS=$KEEP_DAYS)"
