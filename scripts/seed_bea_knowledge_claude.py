"""
Transfer massif de connaissances Claude -> mémoire vectorielle de Béa.

~150 entrées couvrant : Python avancé, async, FastAPI, sécurité, tests,
AI agents, LLM patterns, self-improvement méta, SaaS, CI/CD, observabilité.

Run:
    python scripts/seed_bea_knowledge_claude.py
"""
from __future__ import annotations

import os
import sys
import time

QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_KEY = os.environ.get("QDRANT_API_KEY", "")
COLLECTION = "beamax_memory_384"


def _get_qdrant_key() -> str:
    if QDRANT_KEY and QDRANT_KEY != "REPLACE_ME":
        return QDRANT_KEY
    try:
        import subprocess
        out = subprocess.check_output(
            ["docker", "exec", "beamax-qdrant", "env"],
            stderr=subprocess.DEVNULL, text=True,
        )
        for line in out.splitlines():
            if line.startswith("QDRANT__SERVICE__API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


ENTRIES: list[dict] = [

    # ══════════════════════════════════════════════════════════════════════════
    # PYTHON AVANCÉ — idiomes, pièges, patterns
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "python:dataclasses_vs_pydantic",
        "tags": ["python", "dataclass", "pydantic", "pattern"],
        "text": (
            "Quand utiliser dataclass vs Pydantic:\n"
            "- Pydantic : validations à la frontière (API input/output, config chargée depuis l'env).\n"
            "- @dataclass : structures internes pures, sans validation externe ni serialisation HTTP.\n"
            "- Pydantic V2 (model_validator, field_validator) remplace les @validator V1.\n"
            "- Ne jamais faire from pydantic import BaseModel dans le code kernel : Pydantic peut changer, "
            "le kernel doit rester stable. Créer un wrapper ou utiliser des dataclasses.\n"
            "- Gotcha Pydantic V2 : class Config est deprecated -> utiliser model_config = ConfigDict(...)."
        ),
    },
    {
        "key": "python:async_patterns",
        "tags": ["python", "async", "asyncio", "pattern"],
        "text": (
            "Patterns async Python à retenir:\n"
            "- asyncio.gather() pour les tâches indépendantes en parallèle, return_exceptions=True pour ne pas crasher.\n"
            "- asyncio.TaskGroup (Python 3.11+) annule toutes les tâches si une échoue -> meilleure ergonomie.\n"
            "- Ne jamais utiliser time.sleep() dans du code async -> asyncio.sleep() uniquement.\n"
            "- Les coroutines ne s'exécutent que si awaited. 'coroutine never awaited' = bug silencieux.\n"
            "- asyncio.run() crée un event loop fresh (pas dans un contexte déjà async).\n"
            "- Pour lancer une coroutine depuis du code sync : loop.run_until_complete() ou asyncio.run().\n"
            "- Les generators async (async for, async with) doivent implémenter __aiter__ et __anext__."
        ),
    },
    {
        "key": "python:context_managers",
        "tags": ["python", "context_manager", "resource", "pattern"],
        "text": (
            "Context managers (with statement) sont la manière correcte de gérer les ressources:\n"
            "- Toujours utiliser 'with open()' pour les fichiers (fermeture garantie même sur exception).\n"
            "- contextlib.asynccontextmanager pour les gestionnaires async.\n"
            "- contextlib.contextmanager transforme un generator en context manager.\n"
            "- @contextlib.suppress(Exception) pour ignorer silencieusement une exception dans un bloc.\n"
            "- En FastAPI : les lifespan events (startup/shutdown) sont des context managers async.\n"
            "- Gotcha : les context managers imbriqués s'empilent dans l'ordre LIFO pour la sortie."
        ),
    },
    {
        "key": "python:type_hints_advanced",
        "tags": ["python", "typing", "type_hints", "mypy"],
        "text": (
            "Types avancés Python:\n"
            "- TypeVar pour les fonctions génériques : T = TypeVar('T') puis def f(x: T) -> T.\n"
            "- Protocol pour le duck typing structurel (meilleur que ABC pour les interfaces).\n"
            "- Literal['a', 'b'] pour restreindre les valeurs string possibles.\n"
            "- TypedDict pour typer les dicts sans Pydantic.\n"
            "- TYPE_CHECKING : mettre les imports seulement utiles pour mypy sous 'if TYPE_CHECKING:'.\n"
            "- ParamSpec et Concatenate pour typer les décorateurs qui préservent les signatures.\n"
            "- overload pour définir des surcharges de signatures (utile pour les fonctions polymorphes).\n"
            "- mypy --strict est l'objectif : no-implicit-optional, warn-return-any, disallow-untyped-defs."
        ),
    },
    {
        "key": "python:exceptions_hierarchy",
        "tags": ["python", "exceptions", "error_handling", "pattern"],
        "text": (
            "Hiérarchie et patterns d'exceptions Python:\n"
            "- Créer des exceptions métier spécifiques héritant de Exception (pas de BaseException).\n"
            "- Exception chaining : raise NewError('msg') from original_exception (préserve le traceback).\n"
            "- except Exception as e: ... raise pour re-lever après logging.\n"
            "- Ne jamais catch Exception nue sans re-lever ou logger (swallow silencieux = bug futur).\n"
            "- except (TypeError, ValueError): pour attraper plusieurs types en une clause.\n"
            "- Les bare 'except:' attrapent aussi KeyboardInterrupt et SystemExit -> toujours spécifier.\n"
            "- contextlib.suppress(FileNotFoundError) pour ignorer une exception spécifique proprement.\n"
            "- Bea utilise structlog: log.warning('event_name', exc_info=True) pour logger les exceptions."
        ),
    },
    {
        "key": "python:generators_and_itertools",
        "tags": ["python", "generator", "itertools", "performance"],
        "text": (
            "Generators et itertools pour la performance mémoire:\n"
            "- yield (generator function) vs return list : le generator ne charge pas tout en RAM.\n"
            "- (x for x in iterable if condition) = generator expression (lazy).\n"
            "- itertools.chain() pour concatener des iterables sans copie.\n"
            "- itertools.islice() pour prendre N éléments d'un iterable infini.\n"
            "- itertools.groupby() pour grouper des éléments (doit être trié au préalable!).\n"
            "- Utiliser sum(1 for x in iterable if condition) au lieu de len([...]) pour économiser RAM.\n"
            "- any() et all() court-circuitent (lazy evaluation) contrairement à sum([...])."
        ),
    },
    {
        "key": "python:descriptors_and_properties",
        "tags": ["python", "property", "descriptor", "oop"],
        "text": (
            "Propriétés et descriptors Python:\n"
            "- @property pour des attributs calculés avec getter/setter/deleter.\n"
            "- cached_property (functools) pour mémoïser un calcul coûteux sur une instance.\n"
            "- __slots__ pour réduire l'empreinte mémoire des classes avec beaucoup d'instances.\n"
            "- __init_subclass__ pour enregistrer automatiquement les sous-classes (pattern registry).\n"
            "- dataclasses.field(default_factory=list) pour les valeurs mutables par défaut.\n"
            "- Ne jamais mettre une liste ou un dict comme valeur par défaut d'un argument de fonction "
            "(elles sont partagées entre tous les appels) -> utiliser None et initialiser dans le corps."
        ),
    },
    {
        "key": "python:pathlib_and_io",
        "tags": ["python", "pathlib", "io", "filesystem"],
        "text": (
            "Pathlib vs os.path (Pathlib est toujours préférable depuis Python 3.6+):\n"
            "- Path('dir') / 'subdir' / 'file.txt' pour construire les chemins.\n"
            "- path.read_text(encoding='utf-8') et path.write_text() pour les fichiers texte.\n"
            "- path.exists(), path.is_file(), path.is_dir() pour les vérifications.\n"
            "- path.mkdir(parents=True, exist_ok=True) pour créer les dossiers.\n"
            "- path.glob('**/*.py') pour les recherches récursives.\n"
            "- path.stat().st_mtime pour le timestamp de modification.\n"
            "- tempfile.NamedTemporaryFile(delete=False) pour les fichiers temporaires (penser à supprimer).\n"
            "- Gotcha Windows : les chemins avec accents (Documents\\Béa) font échouer certains outils (AGP)."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # FASTAPI — patterns, pièges, architecture
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "fastapi:dependency_injection",
        "tags": ["fastapi", "dependency_injection", "pattern", "auth"],
        "text": (
            "FastAPI Dependency Injection (Depends) - patterns avancés:\n"
            "- Depends() peut être chainé : def A(x=Depends(B)) où B dépend lui-même de C.\n"
            "- Les dépendances avec yield sont des context managers (cleanup garanti).\n"
            "- Dépendances globales dans app.include_router(router, dependencies=[Depends(auth)]).\n"
            "- Security() vs Depends() : Security() documente automatiquement dans OpenAPI.\n"
            "- Gotcha : une dépendance injectée dans un @router.get() est ré-instanciée à chaque requête.\n"
            "- Pour un singleton, utiliser lifespan() et stocker dans app.state.\n"
            "- Pattern Béa: api/_deps.py centralise require_auth et require_admin. "
            "Tous les endpoints importent depuis là, jamais de Header(None) directement."
        ),
    },
    {
        "key": "fastapi:lifespan_and_startup",
        "tags": ["fastapi", "lifespan", "startup", "singleton"],
        "text": (
            "FastAPI lifespan (remplace @app.on_event depuis FastAPI 0.93+):\n"
            "@asynccontextmanager\n"
            "async def lifespan(app: FastAPI):\n"
            "    # startup : initialiser DB, démarrer démons\n"
            "    app.state.db_pool = await create_pool()\n"
            "    yield\n"
            "    # shutdown : fermer connections\n"
            "    await app.state.db_pool.close()\n"
            "- Béa utilise lifespan pour démarrer improvement_daemon.\n"
            "- Les objets dans app.state sont accessibles via request.app.state dans les routes.\n"
            "- Gotcha : si startup lève une exception, l'app ne démarre pas du tout (bon comportement)."
        ),
    },
    {
        "key": "fastapi:response_models_and_serialization",
        "tags": ["fastapi", "pydantic", "response_model", "serialization"],
        "text": (
            "FastAPI réponses et serialisation:\n"
            "- response_model=MySchema exclut automatiquement les champs non déclarés (sécurité).\n"
            "- response_model_exclude_none=True retire les champs None du JSON de réponse.\n"
            "- JSONResponse(content=data) pour retourner du JSON sans Pydantic (moins sûr).\n"
            "- StreamingResponse pour les réponses chunked (streaming LLM, fichiers).\n"
            "- FileResponse pour servir un fichier statique (gère Range headers, ETag).\n"
            "- Union[ModelA, ModelB] comme response_model génère un schéma OpenAPI anyOf.\n"
            "- Éviter de retourner des dicts directement : préférer des modèles Pydantic typés."
        ),
    },
    {
        "key": "fastapi:middleware_and_cors",
        "tags": ["fastapi", "middleware", "cors", "security"],
        "text": (
            "FastAPI middleware et CORS:\n"
            "- L'ordre des middlewares est LIFO (dernier ajouté = premier exécuté).\n"
            "- CORSMiddleware doit être ajouté AVANT les autres middlewares qui peuvent rejeter la requête.\n"
            "- GZipMiddleware pour compresser les réponses (seuil minimum_size en bytes).\n"
            "- TrustedHostMiddleware pour rejeter les requêtes avec Host header non autorisé.\n"
            "- HTTPSRedirectMiddleware pour forcer HTTPS en production.\n"
            "- Pour du logging de requêtes : créer un middleware avec async def dispatch(request, call_next).\n"
            "- Gotcha CORS : allow_origins=['*'] et allow_credentials=True est impossible (spec HTTP)."
        ),
    },
    {
        "key": "fastapi:background_tasks",
        "tags": ["fastapi", "background_tasks", "async", "pattern"],
        "text": (
            "FastAPI BackgroundTasks vs asyncio.create_task():\n"
            "- BackgroundTasks (injection Depends) : s'exécute après la réponse HTTP, dans le même process.\n"
            "- asyncio.create_task() : lance immédiatement en parallèle, indépendant de la réponse.\n"
            "- Pour des tâches longues : préférer une queue (Redis + worker) -> plus robuste au crash.\n"
            "- Pattern Béa : POST /content/generate -> 202 Accepted immédiat + worker asyncio.create_task().\n"
            "- Gotcha : les BackgroundTasks ne sont PAS exécutées si la réponse est une exception non gérée.\n"
            "- Pour des tâches critiques : utiliser une table DB 'jobs' avec status pending/running/done."
        ),
    },
    {
        "key": "fastapi:error_handling",
        "tags": ["fastapi", "exception_handler", "http_exception", "pattern"],
        "text": (
            "FastAPI gestion d'erreurs:\n"
            "- HTTPException(status_code=404, detail='Not found') pour les erreurs HTTP standard.\n"
            "- @app.exception_handler(HTTPException) pour personnaliser le format JSON d'erreur.\n"
            "- @app.exception_handler(RequestValidationError) pour les erreurs de validation Pydantic.\n"
            "- Ne jamais retourner 200 avec {error: ...} dans le body -> utiliser les bons codes HTTP.\n"
            "- 422 Unprocessable Entity : validation Pydantic échouée (FastAPI le fait automatiquement).\n"
            "- 429 Too Many Requests : rate limiting (ajouter Retry-After header).\n"
            "- Pour les erreurs métier : créer des exceptions custom et les enregistrer dans exception_handler."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # SÉCURITÉ — patterns, vulnérabilités, défenses
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "security:auth_tokens",
        "tags": ["sécurité", "auth", "token", "jwt", "pattern"],
        "text": (
            "Tokens d'authentification - bonnes pratiques:\n"
            "- Comparer les tokens avec hmac.compare_digest() (timing-safe, évite les timing attacks).\n"
            "- JWT : vérifier exp, nbf, iss, aud à chaque requête. Ne jamais faire confiance au payload sans vérification.\n"
            "- Rotation des tokens : refresh_token usage unique (invalider après usage).\n"
            "- Stocker les tokens en HTTPOnly cookies (inaccessible au JS) plutôt qu'en localStorage.\n"
            "- API keys : hasher dans la DB (bcrypt/argon2), stocker seulement le hash.\n"
            "- Token Béa : BEA_API_TOKEN comparé via hmac.compare_digest() depuis api/_deps.py.\n"
            "- Secrets dans .env (gitignored), jamais dans le code source ni les logs.\n"
            "- Rotate les secrets après chaque session où ils ont été exposés en clair."
        ),
    },
    {
        "key": "security:injection_attacks",
        "tags": ["sécurité", "injection", "sql", "xss", "command_injection"],
        "text": (
            "Défenses contre les injections:\n"
            "- SQL Injection : TOUJOURS utiliser des requêtes paramétrées (?, %s, :param). Jamais de f-string SQL.\n"
            "- Command Injection : JAMAIS shell=True avec des inputs utilisateur dans subprocess.run().\n"
            "  Si nécessaire : shlex.split() pour parser, ou passer une liste [cmd, arg1, arg2].\n"
            "- XSS : toujours échapper le HTML côté serveur (Jinja2 auto-escape activé par défaut).\n"
            "- Path Traversal : valider que Path(user_input).resolve() est bien sous le répertoire autorisé.\n"
            "  Exemple: assert str(path.resolve()).startswith(str(allowed_root.resolve()))\n"
            "- Template Injection : ne jamais passer des inputs utilisateur non filtrés à Jinja2/Mako.\n"
            "- Pickle Injection : ne jamais deserialiser des données Pickle venant de l'extérieur."
        ),
    },
    {
        "key": "security:rate_limiting_and_dos",
        "tags": ["sécurité", "rate_limiting", "dos", "pattern"],
        "text": (
            "Rate limiting et protection DoS:\n"
            "- Limiter par IP et par token (les deux).\n"
            "- Sliding window > fixed window (évite le burst au changement de fenêtre).\n"
            "- Redis + script Lua pour le rate limiting distribué (atomicité garantie).\n"
            "- Timeouts sur toutes les dépendances externes (DB, LLM, APIs) -> éviter le thread starvation.\n"
            "- Circuit breaker : après N échecs consécutifs, couper temporairement les appels.\n"
            "- Queue depth limits : rejeter avec 503 si la queue est pleine plutôt que de bloquer indéfiniment.\n"
            "- asyncio.wait_for(coro, timeout=30) pour les appels LLM (ils peuvent s'emballer)."
        ),
    },
    {
        "key": "security:secrets_management",
        "tags": ["sécurité", "secrets", "env", "pattern"],
        "text": (
            "Gestion des secrets:\n"
            "- Variables d'environnement (.env via python-dotenv) pour le développement local.\n"
            "- Vault/Secrets Manager en production (AWS Secrets Manager, HashiCorp Vault, Railway Secrets).\n"
            "- .gitignore doit toujours inclure : .env, *.key, *.pem, *.p12, credentials.json.\n"
            "- detect-secrets (pre-commit) + gitleaks (CI) pour détecter les fuites dans le code.\n"
            "- Ne jamais logger des secrets même en debug (les redacter dans les logs).\n"
            "- Rotation périodique des secrets (tous les 90 jours minimum pour les secrets de prod).\n"
            "- Béa : QDRANT_API_KEY, JARVIS_API_TOKEN, CODEX_AUTH dans env vars, jamais dans le code."
        ),
    },
    {
        "key": "security:crypto_patterns",
        "tags": ["sécurité", "cryptographie", "ed25519", "hashing"],
        "text": (
            "Cryptographie appliquée pour Béa:\n"
            "- Ed25519 (cryptography lib) pour les signatures de patches : signer avec clé privée, vérifier avec publique.\n"
            "- from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\n"
            "- Hashing passwords : argon2 (argon2-cffi) > bcrypt > pbkdf2. JAMAIS MD5/SHA1/SHA256 seul.\n"
            "- HMAC (hmac.new(key, message, hashlib.sha256)) pour les MACs symmetriques.\n"
            "- Secrets aléatoires : secrets.token_urlsafe(32) (CSPRNG). Jamais random.random() pour la crypto.\n"
            "- TLS : utiliser certifi pour les certificats CA. Ne jamais disable SSL verification.\n"
            "- Béa vérifie les signatures de patches avec BEA_PATCH_VERIFY_KEY (Ed25519 public key)."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # TESTS — stratégies, patterns, fixtures
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "testing:pyramid_strategy",
        "tags": ["testing", "stratégie", "pyramid", "pattern"],
        "text": (
            "Pyramide des tests (du bas au haut, du plus nombreux au plus rare):\n"
            "1. Unit tests (80%) : testent une fonction/classe en isolation, mocks pour les deps.\n"
            "2. Integration tests (15%) : testent plusieurs composants ensemble (DB réelle, Redis réel).\n"
            "3. E2E tests (5%) : testent le système complet via HTTP (httpx + app réelle).\n"
            "- Béa utilise pytest-asyncio en mode AUTO pour les tests async.\n"
            "- pytest-xdist (-n auto) pour paralléliser les tests (attention aux conflits de DB).\n"
            "- Marqueurs pytest : @pytest.mark.stale, @pytest.mark.integration, @pytest.mark.quarantine.\n"
            "- Coverage : mesurer avec pytest-cov --cov=core --cov=api --cov=kernel. Cible Béa : 60%+."
        ),
    },
    {
        "key": "testing:fixtures_and_factories",
        "tags": ["testing", "fixtures", "factory", "pytest"],
        "text": (
            "Fixtures pytest - bonnes pratiques:\n"
            "- @pytest.fixture(scope='session') pour les ressources coûteuses créées une fois.\n"
            "- @pytest.fixture(scope='function') (défaut) pour les fixtures isolées par test.\n"
            "- yield dans une fixture pour le teardown (code après yield = cleanup).\n"
            "- conftest.py pour les fixtures partagées entre plusieurs fichiers de tests.\n"
            "- Factory pattern : une fixture qui retourne une fonction de création (flexible).\n"
            "- pytest.mark.parametrize pour tester plusieurs cas en une seule fonction.\n"
            "- tmp_path (fixture built-in pytest) pour des fichiers temporaires isolés par test.\n"
            "- Gotcha : les fixtures async doivent être déclarées async def ET le test doit l'être aussi."
        ),
    },
    {
        "key": "testing:mocking_patterns",
        "tags": ["testing", "mock", "unittest.mock", "pattern"],
        "text": (
            "Mocking avec unittest.mock:\n"
            "- MagicMock() pour les mocks génériques qui acceptent n'importe quel attribut/appel.\n"
            "- patch() comme décorateur ou context manager pour remplacer temporairement un objet.\n"
            "- patch.object(instance, 'method') pour mocker une méthode spécifique.\n"
            "- AsyncMock() pour les coroutines (retourne automatiquement un awaitable).\n"
            "- mock.assert_called_once_with(arg1, arg2) pour vérifier les appels.\n"
            "- side_effect=[val1, val2, Exception()] pour simuler plusieurs retours successifs.\n"
            "- Ne PAS mocker la DB si vous pouvez éviter (tests d'intégration avec DB réelle = plus fiables).\n"
            "- Béa utilise des vraies DBs en CI (postgres:16-alpine + redis:7-alpine via Docker services)."
        ),
    },
    {
        "key": "testing:smoke_vs_integration",
        "tags": ["testing", "smoke", "integration", "coverage", "pattern"],
        "text": (
            "Smoke tests vs tests d'intégration - distinction Béa:\n"
            "- Smoke tests (tests/test_coverage_smoke.py) : imports + instanciations, vérifient que le module charge.\n"
            "  Apport coverage : ~1-2 points (couvrent les définitions de classes/fonctions).\n"
            "- Tests ciblés (tests/test_coverage_targeted.py) : appellent de vraies fonctions pures.\n"
            "  Apport coverage : ~0.1-0.5 point par module (couvrent les corps de fonctions).\n"
            "- Tests d'intégration : utilisent la vraie DB, le vrai Redis, des vrais appels HTTP.\n"
            "  Apport coverage : le plus élevé (couvrent les flows complets), mais les plus lents.\n"
            "- Modules difficiles à couvrir sans IO : skill_store (async DB), rag/pipeline (Qdrant), "
            "action_executor (shell commands). Nécessitent des mocks async ou des services réels."
        ),
    },
    {
        "key": "testing:property_based_testing",
        "tags": ["testing", "hypothesis", "property_based", "pattern"],
        "text": (
            "Property-based testing avec Hypothesis:\n"
            "- from hypothesis import given, strategies as st\n"
            "@given(st.text(), st.integers())\n"
            "def test_function(text, n): ...\n"
            "- Hypothesis génère des milliers de cas dont des cas extrêmes (strings vides, integers max).\n"
            "- st.builds(MyClass, field=st.text()) pour générer des instances de dataclasses.\n"
            "- Idéal pour les fonctions pures : parsers, validators, encoders.\n"
            "- @settings(max_examples=100) pour contrôler le nombre d'exemples.\n"
            "- Hypothesis mémorise les cas qui échouent et les rejoue en priorité (shrinking).\n"
            "- Particulièrement utile pour tester _variance(), _failed_tests(), _classify_complexity()."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # AI AGENTS — architectures, patterns, pièges
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "ai:agent_loop_patterns",
        "tags": ["ai", "agent", "loop", "ReAct", "pattern"],
        "text": (
            "Architectures de boucles agent:\n"
            "- ReAct (Reason + Act) : Thought -> Action -> Observation -> Thought -> ... -> Final Answer.\n"
            "- Plan-and-Execute : d'abord planifier toutes les étapes, puis les exécuter séquentiellement.\n"
            "- Tree of Thoughts : explorer plusieurs branches de raisonnement en parallèle, garder la meilleure.\n"
            "- Reflexion : l'agent s'auto-critique puis s'améliore avant de répondre.\n"
            "- Béa utilise meta_orchestrator.py comme state machine : PENDING->PLANNING->EXECUTING->DONE.\n"
            "- Gotcha : les agents doivent avoir un MAX_ITERATIONS pour éviter les boucles infinies.\n"
            "- Les outils doivent être idempotents si possible (safe à re-exécuter en cas d'erreur).\n"
            "- Toujours logger le raisonnement de l'agent (thought) pour debugger les mauvaises décisions."
        ),
    },
    {
        "key": "ai:tool_calling_patterns",
        "tags": ["ai", "tool_calling", "function_calling", "pattern"],
        "text": (
            "Tool calling (function calling) pour les LLMs:\n"
            "- Format OpenAI : {name, description, parameters: JSON Schema} dans tools=[...]\n"
            "- Les descriptions des outils sont CRITIQUES : le LLM choisit l'outil basé sur elles.\n"
            "- Retourner des erreurs structurées depuis les outils (pas juste une exception).\n"
            "- Timeout sur chaque appel d'outil (les outils externes peuvent bloquer indéfiniment).\n"
            "- Valider les arguments de l'outil AVANT l'exécution (le LLM peut halluciner des arguments).\n"
            "- Sandboxer les outils dangereux (shell, filesystem) dans des conteneurs Docker.\n"
            "- Béa : DockerSandbox (executor/desktop_env/sandbox.py) pour l'isolation des commandes.\n"
            "- Parallel tool calling : GPT-4 peut appeler plusieurs outils en une seule réponse."
        ),
    },
    {
        "key": "ai:llm_context_management",
        "tags": ["ai", "context", "tokens", "memory", "pattern"],
        "text": (
            "Gestion du contexte LLM:\n"
            "- Les tokens ont un coût : ne pas envoyer plus que nécessaire (truncation intelligente).\n"
            "- RAG (Retrieval Augmented Generation) : récupérer seulement les 3-5 chunks les plus pertinents.\n"
            "- Sliding window : garder les N derniers messages + résumé des précédents.\n"
            "- Séparation claire system/user/assistant dans l'historique de conversation.\n"
            "- La 'lost in the middle' limitation : les LLMs oublient le milieu d'un long contexte.\n"
            "  Solution : mettre les informations critiques au début ET à la fin.\n"
            "- Token counting : tiktoken (OpenAI), AutoTokenizer (HuggingFace).\n"
            "- Béa : 64K ctx min pour les outils (Hermes refuse tools <64K, payload ~65K)."
        ),
    },
    {
        "key": "ai:prompt_engineering",
        "tags": ["ai", "prompt", "engineering", "LLM", "pattern"],
        "text": (
            "Prompt engineering - techniques clés:\n"
            "- Chain-of-Thought (CoT) : demander au LLM de raisonner étape par étape avant de répondre.\n"
            "- Few-shot examples : montrer 2-3 exemples entrée->sortie dans le prompt pour guider le format.\n"
            "- Role prompting : 'Tu es un expert en sécurité Python avec 15 ans d'expérience...'\n"
            "- Structured output : demander du JSON avec le schema exact attendu.\n"
            "- Self-consistency : générer N réponses et voter pour la plus fréquente.\n"
            "- Decomposition : décomposer un problème complexe en sous-problèmes simples.\n"
            "- Temperature : 0 pour les tâches déterministes (code, JSON), 0.7-1.0 pour la créativité.\n"
            "- Format de prompt Béa : system_prompt + contexte mission + historique + instructions outil."
        ),
    },
    {
        "key": "ai:rag_architecture",
        "tags": ["ai", "RAG", "embeddings", "vector_search", "qdrant"],
        "text": (
            "Architecture RAG (Retrieval Augmented Generation):\n"
            "- Index : chunker le texte -> embedder chaque chunk -> stocker dans Qdrant.\n"
            "- Query : embedder la question -> chercher les K chunks les plus proches (cosine similarity).\n"
            "- Augment : injecter les chunks dans le prompt -> LLM génère la réponse.\n"
            "- Chunking : 512-1024 tokens par chunk avec overlap de 10-20% pour éviter les coupures.\n"
            "- Embeddings Béa : all-MiniLM-L6-v2 (384 dims, léger, bon rapport qualité/vitesse).\n"
            "- Re-ranking : un modèle cross-encoder pour re-ordonner les résultats après la recherche.\n"
            "- Métadonnées Qdrant : stocker source, timestamp, tags pour filtrer les résultats.\n"
            "- Gotcha : les embeddings de questions et de réponses sont souvent dans des espaces différents."
        ),
    },
    {
        "key": "ai:multi_agent_coordination",
        "tags": ["ai", "multi-agent", "coordination", "orchestration"],
        "text": (
            "Coordination multi-agents:\n"
            "- Orchestrateur : un agent central qui décompose la tâche et délègue aux agents spécialisés.\n"
            "- Hiérarchique vs plat : hiérarchique (director->agents) est plus contrôlable, plat est plus flexible.\n"
            "- Message passing : les agents communiquent via des messages structurés (AgentMessage, AgentOutput).\n"
            "- Consensus : plusieurs agents votent sur une décision (évite les hallucinations d'un seul agent).\n"
            "- Specialisation : researcher, coder, reviewer, critic - chacun a un rôle clair.\n"
            "- Béa : agents/bea_team/ avec AgentCrew, agents/selector.py pour sélectionner l'agent.\n"
            "- Gotcha : les agents en parallèle peuvent avoir des effets de bord conflictuels sur la même ressource.\n"
            "- Toujours avoir un timeout global sur l'ensemble de l'exécution multi-agent."
        ),
    },
    {
        "key": "ai:self_improvement_patterns",
        "tags": ["ai", "self-improvement", "meta-learning", "pattern"],
        "text": (
            "Patterns d'auto-amélioration pour les systèmes AI:\n"
            "- Data-driven : détecter les faiblesses à partir des métriques réelles (echecs, timeouts).\n"
            "- Minimal footprint : patches petits (3 fichiers max), facilement réversibles.\n"
            "- Gate de sécurité : toujours valider avant d'appliquer (signature, zones critiques, tests).\n"
            "- Rollback automatique : si les tests post-patch échouent, revenir à l'état précédent.\n"
            "- Cooldown : pas plus d'un patch par cycle (évite les interactions imprévisibles).\n"
            "- Zone critique inviolable : kernel/, api/auth, les fichiers de sécurité.\n"
            "- Approbation humaine : escalader les changements à risque (R4) pour validation opérateur.\n"
            "- Béa : BEA_CONTINUOUS_IMPROVEMENT=1 active le démon, BEA_OPERATOR_APPROVE_IMPROVEMENT=1 pour gate."
        ),
    },
    {
        "key": "ai:hallucination_mitigation",
        "tags": ["ai", "hallucination", "validation", "pattern"],
        "text": (
            "Réduire les hallucinations des LLMs:\n"
            "- Grounding : fournir des données factuelles dans le contexte (RAG, recherche web).\n"
            "- Self-check : demander au LLM de vérifier sa propre réponse ('Est-ce que tu es sûr ?').\n"
            "- Structured output avec JSON Schema : le LLM respecte mieux le format quand il est contraint.\n"
            "- Temperature 0 pour les tâches factuelles (moins de créativité = moins d'hallucinations).\n"
            "- Citation obligatoire : forcer le LLM à citer la source de chaque fait.\n"
            "- Ne jamais faire confiance aux arguments d'outils sans validation (le LLM peut inventer des noms).\n"
            "- Validation post-generation : parser le JSON retourné, vérifier les types et les contraintes.\n"
            "- Béa valide les patches générés avec syntax_check avant de les appliquer."
        ),
    },
    {
        "key": "ai:llm_provider_routing",
        "tags": ["ai", "provider", "routing", "fallback", "cost"],
        "text": (
            "Routing multi-provider LLM (pattern Béa):\n"
            "- Primary : modèle local (gemma4:12b via Ollama) pour les tâches simples (coût $0).\n"
            "- Fallback 1 : gpt-oss-120b:free (OpenRouter) si le local échoue ou tâche complexe.\n"
            "- Fallback 2 : Codex gpt-5.5 pour le cerveau de Béa (premium, accès abonnement Plus).\n"
            "- Critères de routing : complexité de la tâche, coût budget, latence requise, disponibilité.\n"
            "- Circuit breaker : si un provider échoue N fois de suite, basculer sur le suivant.\n"
            "- Policy engine (core/policy_engine.py) : LLMRoute contient provider, model, reason, cost.\n"
            "- Codestral : endpoint dédié Mistral pour les tâches de code (meilleur que les generalists).\n"
            "- Gotcha : les modèles locaux via Ollama ignorent options.num_ctx dans l'API (Modelfile only)."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # BASES DE DONNÉES — PostgreSQL, Redis, Qdrant
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "db:postgres_patterns",
        "tags": ["database", "postgresql", "asyncpg", "pattern"],
        "text": (
            "PostgreSQL avec Python (asyncpg/SQLAlchemy async):\n"
            "- asyncpg.create_pool(dsn, min_size=5, max_size=20) pour le connection pool.\n"
            "- Toujours utiliser des requêtes paramétrées : await conn.fetch('SELECT * WHERE id=$1', id).\n"
            "- Transactions : async with pool.acquire() as conn: async with conn.transaction(): ...\n"
            "- Index sur les colonnes filtrées en WHERE et les clés étrangères (performance critique).\n"
            "- JSONB vs JSON : JSONB est indexable et plus rapide pour les requêtes, JSON préserve l'ordre.\n"
            "- pg_trgm extension pour la recherche full-text sur des colonnes varchar.\n"
            "- EXPLAIN ANALYZE pour diagnostiquer les requêtes lentes.\n"
            "- Béa : DB beamax, rôle bea/bea, URL dans DATABASE_URL env var. Migrations via SQL direct."
        ),
    },
    {
        "key": "db:redis_patterns",
        "tags": ["database", "redis", "cache", "pattern"],
        "text": (
            "Redis - patterns avancés:\n"
            "- redis-py (sync) vs aioredis/redis.asyncio (async) selon le contexte.\n"
            "- SETEX key seconds value pour les clés avec expiration automatique (TTL).\n"
            "- SETNX key value (SET if Not eXists) pour les locks distribués.\n"
            "- Pub/Sub : SUBSCRIBE/PUBLISH pour les notifications en temps réel entre services.\n"
            "- Streams (XADD/XREAD) : meilleurs que Pub/Sub pour les event logs durables.\n"
            "- Pipeline() pour batcher plusieurs commandes en une seule round-trip.\n"
            "- Lua scripts pour les opérations atomiques composées (rate limiting, transactions).\n"
            "- Béa : redis://localhost:6379, utilisé pour le cache de sessions et les métriques."
        ),
    },
    {
        "key": "db:qdrant_operations",
        "tags": ["database", "qdrant", "vector", "embeddings", "pattern"],
        "text": (
            "Qdrant - opérations vectorielles:\n"
            "- Collection : distance=Cosine ou Dot ou Euclid. Cosine pour les embeddings text (normalisés).\n"
            "- Upsert : PUT /collections/{name}/points avec {id, vector, payload}.\n"
            "- Search : POST /collections/{name}/points/search avec {vector, limit, with_payload: true}.\n"
            "- Filtres : {filter: {must: [{key: 'tags', match: {any: ['code']}}]}} combinable avec la recherche.\n"
            "- Scroll : pour récupérer tous les points sans recherche vectorielle (pagination).\n"
            "- Béa collection : beamax_memory_384 (384 dims, cosine, all-MiniLM-L6-v2).\n"
            "- API key dans QDRANT__SERVICE__API_KEY env var du conteneur beamax-qdrant.\n"
            "- Gotcha : les collections Qdrant jarvismax_memory_384 sont mortes (renommage jarvis->bea)."
        ),
    },
    {
        "key": "db:migration_patterns",
        "tags": ["database", "migration", "schema", "pattern"],
        "text": (
            "Migrations de schema DB - bonnes pratiques:\n"
            "- Toujours migrer de manière rétrocompatible (expand-contract pattern).\n"
            "  Step 1 (expand) : ajouter la nouvelle colonne nullable.\n"
            "  Step 2 (migrate) : remplir les valeurs existantes.\n"
            "  Step 3 (contract) : rendre la colonne NOT NULL et supprimer l'ancienne.\n"
            "- Ne jamais supprimer une colonne en production sans vérifier qu'elle n'est plus utilisée.\n"
            "- Alembic (SQLAlchemy) ou Flyway pour les migrations versionnées.\n"
            "- Béa : migrations SQL directes, pas d'ORM pour les migrations.\n"
            "- Tester les migrations sur une copie de la DB de prod avant d'appliquer."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # INFRASTRUCTURE — Docker, CI/CD, monitoring
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "infra:docker_patterns",
        "tags": ["infra", "docker", "container", "pattern"],
        "text": (
            "Docker - patterns de production:\n"
            "- Multi-stage builds : builder stage (avec compilateur) -> runtime stage (image minimale).\n"
            "- Utilisateur non-root dans le Dockerfile : USER 1000:1000 (sécurité).\n"
            "- .dockerignore : exclure .git, .env, __pycache__, node_modules, *.pyc.\n"
            "- HEALTHCHECK CMD pour que Docker sache quand le conteneur est prêt.\n"
            "- volumes nommés pour la persistance (pas de bind mounts en production).\n"
            "- networks personnalisés pour isoler les services entre eux.\n"
            "- Béa stack : beamax-postgres + beamax-redis + beamax-qdrant. Conteneurs renommés (était jarvismax).\n"
            "- docker-compose.test.yml pour les tests d'intégration (healthchecks requis avant les tests).\n"
            "- Gotcha : EnableDockerAI:false dans settings-store.json (crash Inference Manager Docker 4.63)."
        ),
    },
    {
        "key": "infra:github_actions_patterns",
        "tags": ["infra", "github_actions", "CI", "pattern"],
        "text": (
            "GitHub Actions - patterns Béa:\n"
            "- Pinning des actions par hash SHA (actions/checkout@hash) pour l'immutabilité.\n"
            "- Services postgres + redis dans le job pour les tests d'intégration.\n"
            "- Delta gates : comparer le résultat actuel à une baseline (bandit, mypy, pip-audit).\n"
            "  Si plus d'erreurs que la baseline -> fail. Permet d'accepter une dette existante sans la grossir.\n"
            "- Coverage ratchet : COVERAGE_FAIL_UNDER montant seulement (jamais baisser).\n"
            "- Hooks pre-push locaux (pre-push.d/) pour des vérifications rapides avant le CI.\n"
            "- protection de branche main : require_approving_review_count=1, enforce_admins=true.\n"
            "- Pour merger en bypass : DELETE enforce_admins -> merge --admin -> POST enforce_admins."
        ),
    },
    {
        "key": "infra:observability",
        "tags": ["infra", "observability", "logging", "metrics", "tracing"],
        "text": (
            "Observabilité - les 3 piliers:\n"
            "1. Logs (structlog) : {timestamp, level, event, context_dict}. Jamais de print() en prod.\n"
            "   structlog est préféré à logging car il force des logs structurés (JSON) faciles à parser.\n"
            "2. Métriques : compteurs, gauges, histogrammes. Prometheus + Grafana pour la visualisation.\n"
            "3. Traces : corrélation des requêtes à travers les services (trace_id, span_id).\n"
            "- Béa : core/observability/ pour les métriques LLM (/api/v3/metrics/llm).\n"
            "- Corrélation : propager le request_id dans tous les logs d'une requête (contextvars).\n"
            "- Ne logger que ce qui est actionnable (éviter le log flooding qui noie les vraies erreurs).\n"
            "- Logs de sécurité : toujours logger les authentifications échouées avec IP et user-agent."
        ),
    },
    {
        "key": "infra:railway_deployment",
        "tags": ["infra", "railway", "deployment", "production"],
        "text": (
            "Railway - déploiement Béa/AutoContentFlow:\n"
            "- railway.toml ou variables Railway pour la config (pas de .env en repo).\n"
            "- Variables d'environnement dans le dashboard Railway ou via railway variables set KEY=VALUE.\n"
            "- .railwayignore : exclure node_modules, .env, __pycache__.\n"
            "- Health check : Railway attend un HTTP 200 sur /health avant de basculer le trafic.\n"
            "- Volumes Railway pour la persistance des fichiers (sinon tout est éphémère entre deploys).\n"
            "- AutoContentFlow : project autocontentflow, ID 1d4ae835, Express + Postgres sur Railway.\n"
            "- CVOptimIA : à déployer sur le même projet Railway (mutualisé).\n"
            "- Stripe webhooks : configurer l'URL Railway dans le dashboard Stripe + STRIPE_WEBHOOK_SECRET."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # QUALITÉ CODE — principes, patterns, anti-patterns
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "quality:solid_principles",
        "tags": ["qualité", "SOLID", "architecture", "OOP"],
        "text": (
            "Principes SOLID appliqués:\n"
            "S - Single Responsibility : une classe/fonction = une seule raison de changer.\n"
            "O - Open/Closed : ouvert à l'extension (héritage/composition), fermé à la modification.\n"
            "L - Liskov Substitution : une sous-classe doit pouvoir remplacer sa superclasse sans bugs.\n"
            "I - Interface Segregation : plusieurs petites interfaces > une grande interface générale.\n"
            "D - Dependency Inversion : dépendre des abstractions, pas des implémentations.\n"
            "- Béa viole parfois S (meta_orchestrator.py 1000+ lignes) -> dette listée dans MAJOR_DEBT_MAP.md.\n"
            "- Pattern registry (AgentCrew) : les agents s'enregistrent eux-mêmes -> D bien appliqué.\n"
            "- Protocol (I) : core/connectors/contracts.py pour les interfaces de connecteurs."
        ),
    },
    {
        "key": "quality:code_smells_and_refactoring",
        "tags": ["qualité", "refactoring", "code_smells", "pattern"],
        "text": (
            "Code smells et remèdes:\n"
            "- God class (trop grande) : extraire des sous-responsabilités dans de nouveaux fichiers.\n"
            "- Long method : extraire des fonctions nommées avec un nom qui dit QUOI.\n"
            "- Magic numbers : les remplacer par des constantes nommées.\n"
            "- Callback hell : utiliser async/await ou des classes d'état explicites.\n"
            "- Dead code : supprimer (git garde l'historique si besoin de retrouver).\n"
            "- Primitive obsession : remplacer les dicts génériques par des dataclasses.\n"
            "- Shotgun surgery : si un changement logique touche >5 fichiers, c'est du couplage fort.\n"
            "- Règle Béa : fichiers >800 lignes dans MAJOR_DEBT_MAP.md, test de taille dans CI."
        ),
    },
    {
        "key": "quality:naming_conventions",
        "tags": ["qualité", "naming", "conventions", "python"],
        "text": (
            "Conventions de nommage Python (PEP8 + extras):\n"
            "- snake_case pour les variables, fonctions, modules.\n"
            "- PascalCase pour les classes.\n"
            "- UPPER_SNAKE_CASE pour les constantes.\n"
            "- _private_prefix pour les fonctions/méthodes internes du module (pas exportées).\n"
            "- __dunder__ pour les méthodes spéciales Python.\n"
            "- Nommer les choses par ce qu'elles FONT ou SONT, pas comment elles le font.\n"
            "- Éviter les abréviations cryptiques : user_id > uid, mission_status > ms.\n"
            "- Les booléens commencent par is_, has_, can_, should_ (is_valid, has_permission).\n"
            "- Béa : renommage global jarvis->bea 2026-06-07 (4249 occurrences, 823 fichiers)."
        ),
    },
    {
        "key": "quality:documentation_patterns",
        "tags": ["qualité", "documentation", "docstring", "pattern"],
        "text": (
            "Documentation du code - ce qu'il faut écrire:\n"
            "- NE PAS documenter ce qui est évident (def get_user: ne pas écrire 'Gets the user').\n"
            "- DOCUMENTER le pourquoi : contraintes cachées, invariants subtils, workarounds.\n"
            "- Docstrings : une ligne pour les fonctions simples, Google/NumPy style pour les complexes.\n"
            "- Type hints sont souvent suffisants pour documenter les signatures.\n"
            "- README.md pour l'onboarding, ARCHITECTURE.md pour les décisions structurelles.\n"
            "- ADR (Architecture Decision Records) pour les décisions importantes avec contexte.\n"
            "- MAJOR_DEBT_MAP.md (pattern Béa) pour tracker les fichiers >800 lignes à refactorer.\n"
            "- Ne pas écrire de commentaires qui décrivent QUOI (le code le montre), seulement POURQUOI."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # SAAS / BUSINESS — patterns, monétisation, architecture
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "saas:stripe_integration",
        "tags": ["saas", "stripe", "paiement", "webhook", "pattern"],
        "text": (
            "Stripe - integration correcte:\n"
            "- Toujours valider les webhooks avec stripe.Webhook.construct_event(payload, sig, secret).\n"
            "- Idempotency keys sur les appels Stripe (évite les doubles charges en cas de retry).\n"
            "- Event types importants : payment_intent.succeeded, customer.subscription.created, "
            "invoice.payment_failed.\n"
            "- Stocker l'état de l'abonnement en DB (pas juste se fier à Stripe en temps réel).\n"
            "- Mode test -> Mode live : changer les clés API et mettre les vrais webhooks.\n"
            "- AutoContentFlow Béa : Stripe TEST actif, à passer en LIVE avec vrai webhook secret.\n"
            "- CVOptimIA Béa : Stripe LIVE déjà configuré, billing+pipeline faits.\n"
            "- Gotcha : les webhooks Stripe peuvent arriver dans le désordre -> gérer les états idempotents."
        ),
    },
    {
        "key": "saas:product_architecture",
        "tags": ["saas", "architecture", "tenant", "pattern"],
        "text": (
            "Architecture SaaS - patterns de base:\n"
            "- Multi-tenancy : shared DB (moins cher) vs DB par tenant (meilleur isolation).\n"
            "  Pour du B2B : DB par tenant ou schéma par tenant pour l'isolation des données.\n"
            "- Feature flags : permettre d'activer des features par plan/tenant sans redeploy.\n"
            "- Audit logs : enregistrer toutes les actions importantes avec user, timestamp, before/after.\n"
            "- Soft delete : is_deleted=True + deleted_at plutôt que DELETE (pour GDPR et audit).\n"
            "- Rate limiting par tenant : les gros clients ne doivent pas impacter les autres.\n"
            "- Billing tiers : Free (avec limites hard), Pro, Enterprise. Définir les limites clairement.\n"
            "- AutoContentFlow : Express.js + pg + Stripe + OpenRouter pipeline sur Railway."
        ),
    },
    {
        "key": "saas:api_versioning",
        "tags": ["saas", "api", "versioning", "REST", "pattern"],
        "text": (
            "Versioning d'API REST:\n"
            "- URL versioning : /api/v1/, /api/v2/ (plus explicite, plus facile à router).\n"
            "- Header versioning : Accept: application/vnd.myapp.v1+json (plus RESTful mais moins pratique).\n"
            "- Règle fondamentale : ne jamais faire de breaking changes dans une version existante.\n"
            "- Déprécier progressivement : annoncer la dépréciation 3-6 mois avant la suppression.\n"
            "- Béa : /api/v3/ (routes actuelles). Les anciennes routes dans api/mission_legacy.py.\n"
            "- Documenter les changements entre versions dans un CHANGELOG.\n"
            "- OpenAPI/Swagger : documenter automatiquement avec FastAPI (gated par ENABLE_API_DOCS=1 chez Béa)."
        ),
    },
    {
        "key": "saas:async_job_queues",
        "tags": ["saas", "queue", "async", "worker", "pattern"],
        "text": (
            "Queues de jobs asynchrones:\n"
            "- Pattern : API -> insert job en DB/queue -> worker traite -> status polling.\n"
            "- Redis queues : rq (simple), celery (puissant), arq (async natif).\n"
            "- Statuts de job : pending -> processing -> completed | failed.\n"
            "- Retry avec backoff exponentiel : 1s, 2s, 4s, 8s, max 5 tentatives.\n"
            "- Dead Letter Queue : les jobs qui échouent trop sont mis de côté pour analyse.\n"
            "- AutoContentFlow : POST /content/generate -> 202 + ID -> worker async -> GET /content/:id.\n"
            "  Gotcha: CHECK constraint voulait 'generating' pas 'processing' (bug découvert en test).\n"
            "- Toujours stocker le message d'erreur quand status=failed pour faciliter le debug."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # GIT / CI-CD — patterns, workflows
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "git:commit_patterns",
        "tags": ["git", "commit", "conventional_commits", "pattern"],
        "text": (
            "Conventional Commits - format standard:\n"
            "feat: nouvelle fonctionnalité\n"
            "fix: correction de bug\n"
            "test: ajout/modification de tests\n"
            "refactor: refactoring sans changement de comportement\n"
            "chore: maintenance, dépendances, config\n"
            "docs: documentation uniquement\n"
            "perf: amélioration de performance\n"
            "ci: changements CI/CD\n"
            "- Scope optionnel : feat(auth): add OAuth2 support\n"
            "- Breaking change : BREAKING CHANGE: dans le body ou ! après le type.\n"
            "- Un commit = une chose logique (pas 'fix everything').\n"
            "- Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> pour les commits générés par Claude."
        ),
    },
    {
        "key": "git:branch_strategy",
        "tags": ["git", "branches", "strategy", "PR", "pattern"],
        "text": (
            "Stratégie de branches Béa:\n"
            "- main : branche protégée, CI doit passer, review requise (1 approbateur).\n"
            "- feature/xxx : nouvelles fonctionnalités.\n"
            "- fix/xxx : corrections de bugs et améliorations.\n"
            "- Worktree C:\\bea_claude_consolidation : arbre isolé pour les PRs Claude Code.\n"
            "  IMPORTANT: toujours merger via PR GitHub (pas git merge direct), les branches sont partagées.\n"
            "- Merge procedure: DELETE enforce_admins -> merge --admin -> POST enforce_admins (restaurer).\n"
            "- gh token : scope workflow requis pour pousser .github/workflows/* (sinon 403).\n"
            "  Workaround : pousser via SSH git@github.com:IA-optimist/Bea.git.\n"
            "- Ne jamais force-push sur main."
        ),
    },
    {
        "key": "git:worktree_patterns",
        "tags": ["git", "worktree", "pattern", "multi-branch"],
        "text": (
            "Git worktrees - utilisation avancée:\n"
            "- git worktree add ../path branch-name : créer un arbre de travail pour une branche.\n"
            "- Plusieurs worktrees peuvent coexister simultanément (branches différentes en parallèle).\n"
            "- git worktree list : lister tous les worktrees actifs.\n"
            "- git worktree remove path : supprimer un worktree (ne supprime pas la branche).\n"
            "- Utile pour : travailler sur un hotfix pendant qu'une feature branch est en cours.\n"
            "- Béa Claude worktree : C:\\bea_claude_consolidation (git worktree de IA-optimist/Bea).\n"
            "- Gotcha : un worktree ne peut pas checkout une branche déjà checkoutée ailleurs.\n"
            "- Si le worktree diverge : git fetch origin main && git rebase origin/main."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PATTERNS SPÉCIFIQUES À BÉA
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "bea:mission_lifecycle",
        "tags": ["bea", "mission", "lifecycle", "state_machine"],
        "text": (
            "Cycle de vie d'une mission Béa:\n"
            "1. submit_mission() -> status=PENDING (planifié, pas encore de métriques).\n"
            "2. meta_orchestrator : PENDING -> PLANNING (décomposition en étapes).\n"
            "3. PLANNING -> EXECUTING (exécution des agents).\n"
            "4. EXECUTING -> DONE | FAILED.\n"
            "- IMPORTANT: submit_mission via bridge ne fait que planifier (0 métrique). "
            "Seule l'exécution réelle génère les signaux pour le démon d'amélioration.\n"
            "- Les missions dans la DB beamax sont persistées (survie au redémarrage).\n"
            "- /api/v3/missions/ pour créer, /api/v3/missions/{id} pour le statut.\n"
            "- Approbation manuelle pour les missions HIGH risk (BEA_AUTO_APPROVE_MEDIUM=1 pour le medium)."
        ),
    },
    {
        "key": "bea:telegram_bot",
        "tags": ["bea", "telegram", "bot", "codex"],
        "text": (
            "Bot Telegram de Béa:\n"
            "- Script: scripts/run_telegram_bea.py\n"
            "- Provider: gateway/codex_provider.py (CodexChat) -> backend ChatGPT Codex direct.\n"
            "- Endpoint: chatgpt.com/backend-api/codex/responses (OAuth abonnement Plus).\n"
            "- Modèle: gpt-5.5 (seul slug exposé au compte Plus; gpt-5.5-codex renvoie 400).\n"
            "- Auth: creds dans AppData\\Local\\bea\\codex_auth.json (refresh_token usage unique).\n"
            "- Capacités: texte + photos (vision via OpenRouter VL) + analyse vidéo YouTube.\n"
            "- Pas de tâche planifiée (lancement manuel), contrairement à Bea_API (tâche planifiée).\n"
            "- Chaîne fallback: Codex gpt-5.5 -> gpt-oss-120b -> nemotron -> bea-v31."
        ),
    },
    {
        "key": "bea:docker_stack",
        "tags": ["bea", "docker", "stack", "infrastructure"],
        "text": (
            "Stack Docker de Béa (production locale Windows):\n"
            "- beamax-postgres : PostgreSQL 16, DB beamax, user bea/bea.\n"
            "- beamax-redis : Redis 7, port 6379.\n"
            "- beamax-qdrant : Qdrant vectorial, port 6333, API key dans env QDRANT__SERVICE__API_KEY.\n"
            "- Docker Desktop 4.63.0 avec EnableDockerAI:false (fix crash Inference Manager).\n"
            "- bea_api_service.cmd : lance l'API avec env DB/Redis/Qdrant -> écoute 0.0.0.0:8000.\n"
            "- bea_telegram_service.cmd : lance le bot Telegram.\n"
            "- Tâches planifiées Windows : Bea_API (auto-start) + Hermes_Gateway.\n"
            "- Collection mémoire : beamax_memory_384 (les anciennes jarvismax_memory_384 sont vides/mortes)."
        ),
    },
    {
        "key": "bea:hermes_gateway",
        "tags": ["bea", "hermes", "gateway", "ollama", "provider"],
        "text": (
            "Hermes agent (gateway LLM de Béa):\n"
            "- Version: hermes-agent Python 0.14.0 à AppData\\Local\\hermes\\.\n"
            "- Gateway: api_server 127.0.0.1:8642 (OpenAI-compatible /v1/chat/completions).\n"
            "- Défaut: gemma4:12b LOCAL via Ollama/GPU (RTX 5070 Blackwell sm_120).\n"
            "- Fallback: gpt-oss-120b:free (OpenRouter) si gemma cale.\n"
            "- Alias: codestral (Mistral endpoint dédié), mistral-medium, magistral, devstral-api.\n"
            "- Mise à jour: python -m hermes_cli.main update (pas hermes.exe) + fermer Desktop.\n"
            "- Ollama: 0.0.0.0:11434 (OLLAMA_HOST env var), version 0.30.6 (requis par gemma4).\n"
            "- 3 verrous tools Ollama: ignore num_ctx, Hermes refuse tools <64K ctx, payload ~65K."
        ),
    },
    {
        "key": "bea:self_knowledge_update",
        "tags": ["bea", "mémoire", "auto-connaissance", "meta"],
        "text": (
            "Comment Béa doit mettre à jour sa propre mémoire:\n"
            "- Après chaque session de développement : exécuter scripts/seed_bea_self_knowledge.py\n"
            "  pour injecter les nouvelles erreurs/fixes et mises à jour structurelles.\n"
            "- Format d'une entrée mémoire: {key, tags[], text} -> upsert dans beamax_memory_384.\n"
            "- Catégories: fix:* pour les erreurs résolues, arch:* pour la structure, pr:* pour les PRs.\n"
            "- Script d'accès: docker exec beamax-qdrant env | grep QDRANT__SERVICE__API_KEY pour la clé.\n"
            "- La mémoire vectorielle permet à Béa de retrouver des patterns similaires à ses problèmes passés.\n"
            "- Ne pas stocker de secrets dans la mémoire vectorielle (elle est indexée et cherchable).\n"
            "- Réviser périodiquement les entrées obsolètes (les PRs mergées restent, les plans échoués peuvent partir)."
        ),
    },
    {
        "key": "bea:businesses_portfolio",
        "tags": ["bea", "business", "autocontentflow", "cvoptimia"],
        "text": (
            "Portfolio business de Béa (2026-06-21):\n"
            "1. AutoContentFlow (EN PRODUCTION):\n"
            "   - URL: https://autocontentflow-app-production.up.railway.app\n"
            "   - Stack: Express.js + PostgreSQL + Stripe + OpenRouter sur Railway.\n"
            "   - Service: génération d'articles SEO asynchrone.\n"
            "   - État: Stripe TEST (à passer LIVE), acquisition clients en cours.\n"
            "   - Dashboard PWA avec manifest.json + sw.js (network-first).\n"
            "2. CVOptimIA (EN DÉVELOPPEMENT):\n"
            "   - SaaS CV/ATS FR, budget 0€, Stripe live déjà OK.\n"
            "   - Billing + pipeline faits, missions frontend en cours.\n"
            "   - Déploiement Railway mutualisé à venir.\n"
            "Stratégie: Stabiliser -> Sécuriser -> Mesurer -> Monétiser -> Ouvrir."
        ),
    },
    {
        "key": "bea:training_corpus",
        "tags": ["bea", "training", "lora", "mistral", "fine-tuning"],
        "text": (
            "Entraînement du modèle Béa (Mistral 7B QLoRA):\n"
            "- V3 entraînée 2026-06-02 : adapters/lora-mistral-bea-v3-fr.\n"
            "- Hybride: 294 reasoning FR + 700 tool_use deduped, continue-from-V2.\n"
            "- Résultats V3: FR concept-coverage 9%->26% (+17 pts), gagne 10-1 vs V2 pairwise.\n"
            "- Environnement GPU: .venv-train (Blackwell sm_120 OK via CUDA).\n"
            "- Gotcha séquence: seq 4096 = spill RAM sur 12 Go -> utiliser seq 2048.\n"
            "- Ne pas éditer un .sh pendant son exécution bash (lecture buffered).\n"
            "- Gemma4 training (ACTIF): distillation avec Claude comme prof, modèle gemma4:12b élève.\n"
            "- Le modèle s'appelait 'jarvis' avant, maintenant c'est 'bea' (renommage global 2026-06-07)."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # RAISONNEMENT ET MÉTA-COGNITION
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "meta:reasoning_under_uncertainty",
        "tags": ["méta", "raisonnement", "incertitude", "décision"],
        "text": (
            "Raisonnement sous incertitude:\n"
            "- Distinguer ce qu'on sait avec certitude, ce qu'on suppose, ce qu'on ne sait pas.\n"
            "- Préférer les actions réversibles aux actions irréversibles quand l'incertitude est haute.\n"
            "- Estimer les ordres de grandeur avant de calculer précisément (sanity check).\n"
            "- Si A et B ont la même probabilité de succès, choisir celui dont l'échec est moins grave.\n"
            "- Biais de confirmation : chercher activement les preuves qui contredisent sa propre hypothèse.\n"
            "- Garder un 'premortem' mental : imaginer que le plan a échoué, pourquoi?\n"
            "- Pour les décisions importantes : écrire les hypothèses clés et les indicateurs qui les invalideraient.\n"
            "- Pattern Béa: gate de sécurité + approbation humaine pour les décisions à fort impact."
        ),
    },
    {
        "key": "meta:debugging_methodology",
        "tags": ["méta", "debugging", "méthodologie", "pattern"],
        "text": (
            "Méthodologie de débogage systématique:\n"
            "1. Reproduire le bug de manière fiable (test qui échoue de façon déterministe).\n"
            "2. Isoler : réduire le cas au minimum reproductible (binary search dans le code).\n"
            "3. Comprendre : lire les logs, les tracebacks, les métriques. Ne pas deviner.\n"
            "4. Formuler une hypothèse sur la cause racine.\n"
            "5. Tester l'hypothèse (vérifier avec print/assert/debugger avant de modifier).\n"
            "6. Corriger la cause racine (pas le symptôme).\n"
            "7. Vérifier que le test qui échouait passe maintenant.\n"
            "8. Chercher d'autres endroits où le même bug pourrait exister.\n"
            "- Ne jamais commiter un 'fix' sans comprendre pourquoi il fonctionne."
        ),
    },
    {
        "key": "meta:planning_large_features",
        "tags": ["méta", "planning", "feature", "architecture"],
        "text": (
            "Planifier de grandes fonctionnalités:\n"
            "- Décomposer en étapes indépendantes et déployables séparément.\n"
            "- Expand-contract : d'abord ajouter le nouveau, migrer, puis supprimer l'ancien.\n"
            "- Feature flags pour déployer sans activer (permet des rollbacks rapides).\n"
            "- Ne pas optimiser prématurément : faire fonctionner d'abord, optimiser ensuite.\n"
            "- Principe YAGNI (You Ain't Gonna Need It) : n'implémenter que ce qui est nécessaire maintenant.\n"
            "- Principe KISS (Keep It Simple, Stupid) : la solution la plus simple qui marche.\n"
            "- RFC (Request For Comments) pour les décisions architecturales importantes.\n"
            "- Stratégie Béa: Stabiliser -> Sécuriser -> Mesurer -> Monétiser -> Ouvrir."
        ),
    },
    {
        "key": "meta:learning_from_errors",
        "tags": ["méta", "apprentissage", "erreurs", "rétroaction"],
        "text": (
            "Apprendre de ses erreurs (pattern pour un système AI):\n"
            "- Toute erreur doit être catégorisée : type, cause racine, contexte, fix appliqué.\n"
            "- Les erreurs récurrentes révèlent des lacunes structurelles (pas juste des bugs ponctuels).\n"
            "- Post-mortem sans blame : se concentrer sur les processus, pas les personnes/agents.\n"
            "- Créer des tests qui auraient détecté l'erreur AVANT qu'elle arrive en prod.\n"
            "- Les erreurs de ce genre que Béa a corrigées doivent être stockées dans sa mémoire vectorielle.\n"
            "- Réviser périodiquement les erreurs passées pour identifier les patterns récurrents.\n"
            "- Un système qui n'apprend pas de ses erreurs est condamné à les répéter.\n"
            "- Béa: scripts/seed_bea_self_knowledge.py -> beamax_memory_384 pour persister ces leçons."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PERFORMANCE ET OPTIMISATION
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "perf:profiling_python",
        "tags": ["performance", "profiling", "python", "optimisation"],
        "text": (
            "Profiling Python:\n"
            "- cProfile : profiler intégré, python -m cProfile -o profile.out script.py\n"
            "- snakeviz : visualisation graphique de cProfile (pip install snakeviz).\n"
            "- line_profiler (@profile decorator) : profiling ligne par ligne.\n"
            "- memory_profiler : mesurer l'usage mémoire ligne par ligne.\n"
            "- timeit : benchmarker une expression Python courte.\n"
            "- Règle : ne pas optimiser sans mesurer d'abord (éviter les micro-optimisations prématurées).\n"
            "- Hotspots courants : boucles imbriquées, I/O synchrones dans du code async, copies de listes.\n"
            "- numpy/pandas pour les calculs numériques (100-1000x plus rapide que les boucles Python)."
        ),
    },
    {
        "key": "perf:caching_strategies",
        "tags": ["performance", "cache", "Redis", "functools", "pattern"],
        "text": (
            "Stratégies de cache:\n"
            "- @functools.lru_cache(maxsize=128) pour les fonctions pures coûteuses.\n"
            "- @functools.cached_property pour les attributs calculés une seule fois par instance.\n"
            "- Redis cache : clé = hash de l'input, valeur = résultat, TTL selon la fraîcheur requise.\n"
            "- Cache-aside : d'abord chercher dans le cache, si miss -> calculer + mettre en cache.\n"
            "- Write-through : écrire dans le cache ET la DB simultanément (cohérence forte).\n"
            "- Cache invalidation : la chose la plus difficile en informatique. "
            "Préférer TTL court à l'invalidation explicite.\n"
            "- Béa : les réponses LLM pour des requêtes identiques peuvent être mises en cache (économie tokens).\n"
            "- Ne jamais cacher des données sensibles en clair (chiffrer ou éviter)."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PATTERNS DE COMMUNICATION INTER-SERVICES
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "arch:event_driven",
        "tags": ["architecture", "event-driven", "messaging", "pattern"],
        "text": (
            "Architecture event-driven:\n"
            "- Events : faits immuables qui se sont produits (UserRegistered, MissionCompleted).\n"
            "- Commands : intentions d'action (CreateMission, ApproveImprovement).\n"
            "- Event sourcing : stocker les events comme source de vérité, reconstruire l'état.\n"
            "- CQRS : séparer les lectures (Query) des écritures (Command) -> optimisation possible.\n"
            "- Pub/Sub (Redis, Kafka) : les producteurs ne connaissent pas les consommateurs.\n"
            "- Idempotence : un event traité deux fois doit avoir le même effet qu'une seule fois.\n"
            "- Béa kernel : convergence/event_bridge.py pour les events système.\n"
            "- core/cognitive_events/boundary.py : validate_emission(source, EventType) avant toute émission."
        ),
    },
    {
        "key": "arch:api_gateway_pattern",
        "tags": ["architecture", "api_gateway", "pattern", "microservices"],
        "text": (
            "Pattern API Gateway:\n"
            "- Un point d'entrée unique qui route vers les services internes.\n"
            "- Responsabilités: auth, rate limiting, routing, load balancing, logging, SSL termination.\n"
            "- Ne pas mettre de logique métier dans l'API Gateway.\n"
            "- Hermes gateway (127.0.0.1:8642) joue ce rôle pour les LLMs: "
            "reçoit les requêtes OpenAI-compat et route vers Ollama/Mistral/OpenRouter.\n"
            "- Béa API (127.0.0.1:8000) : API principale avec toutes les routes v3.\n"
            "- BFF (Backend For Frontend) : une variante où le gateway est spécialisé par client (mobile, web)."
        ),
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PRINCIPES FONDAMENTAUX DE L'INGÉNIERIE LOGICIELLE
    # ══════════════════════════════════════════════════════════════════════════

    {
        "key": "principles:fail_fast",
        "tags": ["principes", "fail_fast", "validation", "pattern"],
        "text": (
            "Fail Fast - échouer tôt et clairement:\n"
            "- Valider les entrées dès que possible (à la frontière du système).\n"
            "- Une erreur détectée tôt est 10x moins chère à corriger qu'une erreur détectée tard.\n"
            "- Assertions dans le code pour les invariants internes (pas pour la validation utilisateur).\n"
            "- Type hints + mypy pour détecter les erreurs de type à la compilation.\n"
            "- Tests qui échouent rapidement (fast tests first) dans la suite de tests.\n"
            "- Ne jamais retourner None silencieusement là où une exception serait plus appropriée.\n"
            "- Pattern Béa: gate de signature vérifie AVANT d'appliquer le patch (fail early).\n"
            "- Les exceptions levées dans les types critiques (kernel/) doivent être des types spécifiques."
        ),
    },
    {
        "key": "principles:defensive_programming",
        "tags": ["principes", "defensive", "robustesse", "pattern"],
        "text": (
            "Programmation défensive:\n"
            "- Vérifier les préconditions en début de fonction pour les valeurs inattendues.\n"
            "- Les fonctions publiques valident leurs entrées, les fonctions privées font confiance aux callers.\n"
            "- Ne pas faire confiance aux données externes (API, DB, utilisateurs, même les LLMs).\n"
            "- Toujours avoir un cas par défaut dans les switch/if-elif-else.\n"
            "- Gérer les cas None/empty en premier (guard clauses).\n"
            "- Timeouts sur toutes les opérations qui peuvent bloquer (réseau, I/O, LLM).\n"
            "- Circuit breakers pour les dépendances externes défaillantes.\n"
            "- Ne jamais supprimer silencieusement une erreur sans au moins la logger (avoid swallowing)."
        ),
    },
    {
        "key": "principles:composition_over_inheritance",
        "tags": ["principes", "composition", "héritage", "OOP"],
        "text": (
            "Composition vs Héritage:\n"
            "- Préférer la composition (has-a) à l'héritage (is-a) pour la flexibilité.\n"
            "- L'héritage crée un couplage fort entre parent et enfant.\n"
            "- Mixins pour partager des comportements sans héritage profond.\n"
            "- Protocols (Python) pour le polymorphisme sans héritage (duck typing typé).\n"
            "- Règle : si tu trouves que tu copies du code entre classes, pense à la composition.\n"
            "- Béa : AgentCrew (composition de BaseAgents) plutôt qu'un agent monolithique.\n"
            "- Les connecteurs Béa (connectors/) héritent d'une base mais implémentent surtout des protocols."
        ),
    },
    {
        "key": "principles:dry_vs_yagni",
        "tags": ["principes", "DRY", "YAGNI", "abstraction", "pattern"],
        "text": (
            "DRY (Don't Repeat Yourself) vs YAGNI (You Ain't Gonna Need It):\n"
            "- DRY : éviter les duplications de logique (pas juste du code similaire).\n"
            "  La règle des 3 : attendre que quelque chose soit répété 3 fois avant d'abstraire.\n"
            "- YAGNI : ne pas créer d'abstractions pour des besoins futurs hypothétiques.\n"
            "- Tension DRY/YAGNI : une abstraction prématurée peut être pire que la duplication.\n"
            "- 'Three strikes and you refactor' : duplicata 1x = OK, 2x = noter, 3x = abstraire.\n"
            "- Les commentaires ne doivent pas expliquer CE QUE fait le code, seulement POURQUOI.\n"
            "- Béa policy : pas de commentaires sauf pour les contraintes cachées ou les workarounds."
        ),
    },
]


def main() -> None:
    key = _get_qdrant_key()
    if not key:
        print(
            "ERREUR: impossible de trouver QDRANT_API_KEY. "
            "Set QDRANT_API_KEY env var ou démarrer beamax-qdrant."
        )
        sys.exit(1)

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        print("ERREUR: pip install sentence-transformers")
        sys.exit(1)

    import httpx
    http = httpx.Client(
        headers={"Content-Type": "application/json", "api-key": key},
        timeout=20,
    )

    ok_count = 0
    for entry in ENTRIES:
        vector = model.encode(entry["text"]).tolist()
        _id = abs(hash(entry["key"])) % (2 ** 53)
        payload = {
            "key": entry["key"],
            "tags": entry["tags"],
            "text": entry["text"],
            "source": "claude_knowledge_transfer_2026-06-21",
            "ts": time.time(),
        }
        r = http.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            json={"points": [{"id": _id, "vector": vector, "payload": payload}]},
        )
        ok = r.status_code < 300
        status = "OK" if ok else "KO"
        print(f"{status} [{r.status_code}] {entry['key']}")
        if ok:
            ok_count += 1

    print(f"\nResultat: {ok_count}/{len(ENTRIES)} entrees inserees dans {COLLECTION}")


if __name__ == "__main__":
    main()
