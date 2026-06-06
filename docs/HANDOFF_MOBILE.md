# Passation mobile — prompt + code prêt à coller (Claude Code, env Flutter)

> À exécuter **dans un environnement Flutter** (SDK Dart + Android SDK). Chaque tâche
> n'est « finie » qu'après `flutter analyze` propre + `flutter build apk` OK + smoke test.
> Plan complet & contexte : `docs/MOBILE_HARDENING.md`. App : `jarvismax_app/`.

## Prompt à coller dans Claude Code
Tu reprends l'app de contrôle Flutter de Béa (`jarvismax_app/`). Objectif : app propre,
stable, robuste pour piloter ET monitorer Béa. Respecte : modifications minimales,
diff montré + validation, et **valide chaque changement par `flutter analyze` +
`flutter build apk`** (impossible à prouver sans build). Audit déjà fait : 24/25
endpoints alignés ; `/api/v2/session` corrigé en `/auth/me`. Traite les tâches dans
l'ordre de `docs/MOBILE_HARDENING.md`. Demande-moi host/credentials si besoin.

---

## Code prêt à coller

### A. Contrôle de mission — `jarvismax_app/lib/services/api_service.dart`
Ajouter (calqué sur `approveAction`, routes backend déjà existantes) :
```dart
Future<ApiResult<void>> abortMission(String id) async {
  try {
    await _post('/api/v2/missions/$id/abort');     // backend: missions.py
    await _loadActions();
    return const ApiResult.success(null);
  } catch (e) {
    try { await _loadActions(); } catch (_) {}
    return ApiResult.failure(_friendly(e));
  }
}

Future<ApiResult<void>> pauseMission(String id) async {
  try {
    await _post('/api/v1/missions/$id/pause');      // backend: mission_control.py (auth)
    return const ApiResult.success(null);
  } catch (e) { return ApiResult.failure(_friendly(e)); }
}

Future<ApiResult<void>> resumeMission(String id) async {
  try {
    await _post('/api/v1/missions/$id/resume');     // backend: mission_control.py (auth)
    return const ApiResult.success(null);
  } catch (e) { return ApiResult.failure(_friendly(e)); }
}
```
Puis ajouter les boutons Abort/Pause/Resume dans `lib/screens/mission_detail_screen.dart`
(avec confirmation pour Abort) + un kill-switch global dans `settings_screen.dart`.

### B. Monitoring LLM — nouveau `api/routes/metrics_llm.py` (backend, additif)
Le singleton `core.observability.llm_tracer.get_tracer()` est déjà en place (testé).
```python
"""metrics_llm — stats du LLMTracer pour le monitoring mobile."""
from fastapi import APIRouter

from core.observability.llm_tracer import get_tracer

router = APIRouter(tags=["metrics"])


@router.get("/api/v3/metrics/llm")
def llm_metrics() -> dict:
    return get_tracer().stats()


@router.get("/api/v3/metrics/llm/mission/{mission_id}")
def llm_cost(mission_id: str) -> dict:
    return {"mission_id": mission_id, "cost_usd": get_tracer().cost_by_mission(mission_id)}
```
Enregistrer dans `api/main.py` (près des autres `include_router`) :
```python
from api.routes.metrics_llm import router as metrics_llm_router
app.include_router(metrics_llm_router)
```
Pour que les chiffres soient réels, brancher le tracer dans `core/llm_factory.py`
(`safe_invoke`, ~ligne 654), flag `JARVIS_LLM_TRACE` :
```python
from core.observability.llm_tracer import get_tracer
with get_tracer().span(model=<model>, mission_id=<mission_id>) as _s:
    result = ...  # appel LLM existant
    _s.set(prompt_tokens=..., completion_tokens=..., cost_usd=...)
```
Côté app : écran « Monitoring » consommant `/api/v3/metrics/llm` + le `websocket_service`
existant (flux `metrics_websocket`/`observability`) → coût cumulé, taux d'erreur, live.

### C. Accès distant sécurisé — `jarvismax_app/lib/config/hardcoded_config.dart`
Supporter HTTPS + endpoint configurable (aujourd'hui : `http://host:port` en dur) :
```dart
// scheme configurable; défaut https en prod
static String get scheme => 'https';
// baseUrl côté api_config.dart :
// String get baseUrl => '${HardcodedConfig.scheme}://${HardcodedConfig.apiHost}:${HardcodedConfig.apiPort}';
```
Exposer le backend derrière le reverse proxy TLS (`Caddyfile` racine), réactiver un
champ host/port dans `settings_screen.dart` (persisté via `shared_preferences`).

### D. Push notifications (FCM) — `jarvismax_app`
- `pubspec.yaml` : ajouter `firebase_messaging` (+ config Firebase Android).
- `lib/services/notification_service.dart` : enregistrer le token device au login,
  l'envoyer au backend ; afficher les push (approbation requise / mission finie / erreur).
- Backend : émettre un push sur ces événements (point d'accroche : `api/routes/approval.py`
  + fin de mission dans `core/meta_orchestrator.py`).

### E. Consolidation & build
- Supprimer `orchestrate-mobile/` (doublon). Statuer sur `mobile/` (RN business).
- Keystore de release signé + `flutter build apk --release` ; canal de distribution
  (APK direct / Play Store internal / TestFlight) ; idéalement CI de build.

## Critères de validation (par tâche)
1. `flutter analyze` sans erreur. 2. `flutter build apk` OK. 3. Smoke test contre un
backend lancé : login → mission → approbation → **abort** → écran monitoring.
