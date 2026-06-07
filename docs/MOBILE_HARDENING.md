# App mobile Béa — audit & plan de durcissement

_2026-06-01 · établi sans build Flutter (SDK Dart/Android absent de l'environnement
d'analyse) → les éléments « à faire » sont à exécuter et **valider dans un env Flutter**._

## État des lieux

Trois projets mobiles coexistent (fragmentation) :
- **`beamax_app/` (Flutter)** — **l'app de contrôle de Béa** (la bonne base). 15 écrans :
  missions, approbations (+ notifs locales), santé, décisions, self-improvement,
  capacités, modules, admin, dashboard AIOS, login, réglages. Services
  `api`/`websocket`/`notifications`/`session`, **JWT chiffré** (Keystore/Keychain).
- **`mobile/` (React Native/Expo)** — orienté **business** (Dashboard, Opportunités,
  Produits, Revenus). Objet différent.
- **`orchestrate-mobile/`** — doublon importé (Flutter + backend py). À retirer.

## Audit app ↔ API (548 routes backend)
**24 / 25 endpoints appelés par l'app existent côté backend** (y compris
`/api/v3/missions/{id}/approve|reject` — pas de dérive v2/v3). 
**1 corrigé** : `modules_screen.dart` appelait `/api/v2/session` (inexistant) →
remplacé par `/auth/me` (fail-safe : fallback admin déjà présent).

## Plan de durcissement (priorisé) — chemins chauds, à valider en env Flutter

### 1. Consolider sur une seule app (anti-sprawl)
Garder `beamax_app` comme app de contrôle. **Supprimer `orchestrate-mobile/`**
(doublon). Statuer sur `mobile/` (RN) : soit le fusionner en onglet « Business »
dans l'app Flutter, soit le garder comme app séparée assumée. Ne pas maintenir 3 apps.

### 2. Accès distant sécurisé (bloqueur n°1)
Aujourd'hui : `lib/config/hardcoded_config.dart` = `http://host:port` codé en dur
→ **réseau local uniquement, en clair**. À faire :
- endpoint configurable (réactiver un champ dans `settings_screen.dart` + persistance),
- **HTTPS/TLS** via le reverse proxy (`Caddyfile` déjà présent à la racine),
- ne jamais exposer le backend en clair hors LAN.
Fichiers : `lib/config/hardcoded_config.dart`, `lib/config/api_config.dart`, `lib/screens/settings_screen.dart`.

### 3. Notifications push (FCM/APNs)
Les notifs actuelles sont **locales** (`flutter_local_notifications`) → ne se
déclenchent que si l'app tourne. Pour être alerté **app fermée** (approbation
requise, mission finie, erreur) : ajouter `firebase_messaging` + un émetteur push
côté backend sur les événements clés.
Fichiers : `lib/services/notification_service.dart` (+ enregistrement token device),
backend : un notifier sur `api/routes/approval.py` / fin de mission.

### 4. Écran de monitoring temps réel
`lib/services/websocket_service.dart` existe → le brancher sur le flux d'événements
(`api/routes/metrics_websocket.py` / `observability`) **et** sur le nouveau
`core/observability/llm_tracer.py` (coût/erreurs/latence). Exposer un endpoint
`GET /api/v3/metrics/llm` qui renvoie `LLMTracer.stats()`, et un écran « Monitoring »
(activité agents, coût cumulé, taux d'erreur, progression mission live).

### 5. Contrôle de mission complet
L'app lance/approuve/rejette mais **n'expose pas l'arrêt**. Le backend a déjà :
- `POST /api/v2/missions/{id}/abort` (arrêt),
- `POST /api/v1/missions/{id}/pause` et `/resume` (`mission_control.py`).
À ajouter : méthodes `abortMission/pauseMission/resumeMission` dans
`lib/services/api_service.dart` (calquer `approveAction`) + boutons dans
`lib/screens/mission_detail_screen.dart` + un **kill-switch** global (réglages).

### 6. Build, signature & distribution
Scripts APK présents (`build_apk.sh/.bat`). Manque : keystore de **release signé**,
canal de distribution (APK direct / Play Store internal testing / TestFlight),
et idéalement une CI de build mobile.

### 7. Vérification d'intégration
Lancer le backend (venv 3.12 + services), pointer l'app dessus, et faire le tour
des écrans (smoke test manuel) : login → mission → approbation → abort → monitoring.
C'est la seule façon de confirmer « stable & robuste » côté app (impossible à
prouver sans build).

## Raccourci de pilotage distant (sans app à maintenir)
Le `gateway/` (squelette posé) + un adaptateur Telegram/WhatsApp permet de
**piloter et approuver Béa par messagerie** — MVP de supervision distant bien plus
rapide qu'une app native, en complément.
