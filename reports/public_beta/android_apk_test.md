# Android APK Test Report — PHASE 12

Generated: 2026-06-27

## Statut

**HUMAN_REQUIRED — Device physique non disponible pour ce test automatisé.**

## Ce qui a été vérifié (sans device)

### Flutter check_client_v1_usage

```
python scripts/check_client_v1_usage.py
[OK] beamax_app\lib — 0 active /api/v1 calls (Flutter uses /api/v3)
```
✅ Aucun appel /api/v1 actif dans le code Flutter.

### CI workflow APK

`flutter_apk.yml` présent dans `.github/workflows/` ✅

### Conclusion sans device

| Check | Résultat |
|-------|----------|
| 0 active /api/v1 calls | ✅ |
| CI workflow APK présent | ✅ |
| Build APK | Non testé ici (Flutter hors PATH bash) |
| Mission UI physique | ❌ HUMAN_REQUIRED |
| Comportement offline | ❌ HUMAN_REQUIRED |
| logcat sans token visible | ❌ HUMAN_REQUIRED |
| Token dans URL Android | ❌ HUMAN_REQUIRED |

## HUMAN_REQUIRED items

1. Installer APK sur device physique (Pixel 7 ou autre Android)
2. Ouvrir l'app, configurer l'API (Tailscale ou local)
3. Soumettre une mission : "Résume le README du projet"
4. Couper l'API et vérifier l'erreur
5. Vérifier logcat : aucun token visible, aucun /api/v1 call
6. Vérifier l'erreur offline est propre (pas de crash)

## Recommandation

**Android reste PARTIALLY VALIDATED** pour la private beta. **BLOQUANT pour la public beta**.

Ne pas déclarer PUBLIC_BETA_CANDIDATE=true tant que ces items ne sont pas prouvés.
