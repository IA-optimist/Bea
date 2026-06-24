# Béa APK — Physical Device Validation

> **HUMAN_REQUIRED** — Cette checklist doit être complétée par un humain avec un device Android physique.
> Statut actuel : **NON VALIDÉ** (aucun device branché lors de la préparation de la bêta)

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

- [ ] APK installée sans erreur (`adb install -t app-release.apk`)
- [ ] App se lance sans crash
- [ ] Ancienne version désinstallée si APK précédente avec autre identité

### Configuration

- [ ] Configuration API URL correcte (host + port + scheme)
- [ ] Pas de credentials hardcodés visibles dans l'UI

### Authentification

- [ ] Login avec les credentials testeur réussit
- [ ] Écran principal s'affiche après login
- [ ] Session persiste après mise en veille

### Connectivité

- [ ] GET /health renvoie 200 (visible dans les logs ou l'UI)
- [ ] Token envoyé correctement dans les headers

### Mission simple

- [ ] Mission "Résume le README du projet." soumise
- [ ] Statut de mission visible (pending → running → completed ou failed)
- [ ] Résultat affiché dans l'UI

### Réseau

- [ ] Comportement correct si API inaccessible (timeout, message d'erreur clair)
- [ ] Pas de crash sur perte réseau

### Logs / traces

- [ ] Aucune fuite de token dans les logs adb (`adb logcat | grep -i "sk-or-v1"`)
- [ ] Aucune route `/api/v1` appelée (vérifier avec `adb logcat | grep "/api/v1"`)

---

## Résultats

| Validateur | Date | Device | Android version | APK sha256 | Résultat |
|------------|------|--------|-----------------|------------|----------|
| HUMAN_REQUIRED | — | — | — | — | NON VALIDÉ |

---

## Statut dans le gate

Tant que cette checklist n'est pas complétée et signée par un humain avec un device réel, le statut APK reste :

**Flutter APK : `supported experimental` — validation physique HUMAN_REQUIRED**

Ne jamais cocher "APK validated on physical device" sans preuve réelle dans ce tableau.
