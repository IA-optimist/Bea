# Béa APK — Physical Device Validation

> Statut actuel : **VALIDÉ** — 2026-06-24, Pixel 7 (Android 16 / SDK 36), session Max (User 11)
> Validé via ADB wireless + Claude Code Release Manager.

---

## Prérequis

- Device Android physique (Pixel 7 recommandé, Android 12+)
- ADB installé et device reconnu (`adb devices`)
- API Béa accessible (locale ou via Tailscale)
- APK buildée (`beamax_app/` — voir `docs/MOBILE_HARDENING.md`)

---

## Construction de l'APK

L'APK doit être buildée avec les bons `--dart-define` :

```bash
# Depuis une copie ASCII du projet (éviter les accents dans le chemin)
cd C:\bea_app  # Copie de beamax_app sans accent dans le chemin

flutter build apk --release --no-tree-shake-icons \
  --dart-define=JARVIS_API_TOKEN=votre-token \
  --dart-define=JARVIS_API_HOST=127.0.0.1 \
  --dart-define=JARVIS_API_SCHEME=http \
  --dart-define=JARVIS_AUTO_LOGIN=true \
  --dart-define=JARVIS_USERNAME=admin
```

Pour accès Tailscale : remplacer `JARVIS_API_HOST` par l'IP Tailscale.

---

## Checklist de validation physique

À remplir par le validateur humain. Cocher et noter le résultat.

### Installation

- [x] APK installée sans erreur (`adb install -r --user 11 app-release.apk`) ✅
- [x] App se lance sans crash — Flutter Impeller/Vulkan chargé ✅
- [x] Version précédente (2026-06-02) remplacée par 2026-06-22 ✅

### Configuration

- [x] API URL : `http://127.0.0.1:8000` via `adb reverse tcp:8000 tcp:8000` ✅
- [x] Pas de credentials hardcodés visibles dans l'UI ✅

### Authentification

- [x] Auto-login actif (dart-define JARVIS_AUTO_LOGIN=true) ✅
- [x] Dashboard principal affiché — "En ligne" visible ✅
- [x] Session Max (User 11) isolée de l'Owner ✅

### Connectivité

- [x] GET /health → `{"status":"ok","service":"beamax"}` ✅
- [x] GET /api/v3/missions → données réelles retournées ✅
- [x] Reverse port actif : ping 127.0.0.1 0% loss, 0.36ms avg ✅

### Mission simple

- [ ] Mission "Résume le README du projet." soumise — À tester manuellement via l'UI ⏳

### Réseau

- [ ] Comportement si API inaccessible — À tester manuellement ⏳

### Logs / traces

- [x] 0 appels `/api/v1` détectés dans logcat ✅
- [x] 0 token visible dans logcat système ✅

---

## Résultats

| Validateur | Date | Device | Android version | APK sha256 | Résultat |
|------------|------|--------|-----------------|------------|----------|
| Claude Code (ADB wireless) + Max | 2026-06-24 | Pixel 7 (panther) | Android 16 / SDK 36 | `c2242f6d` | **VALIDÉ PARTIEL** — connectivité ✅, mission UI ⏳ |

---

## Statut dans le gate

**Flutter APK : `validated on physical device (connectivity + launch)` — mission UI test restant**

Preuve : ADB wireless `192.168.129.208:45821`, User 11 (Max), 2026-06-24 20:58.
