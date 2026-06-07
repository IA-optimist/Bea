"""
core/security/startup_guard.py — Production startup hardening.

Validates critical security invariants before the API starts.
In production mode, missing auth token = hard failure.
"""
from __future__ import annotations

import os
import logging

log = logging.getLogger("bea.security")


class StartupGuardError(RuntimeError):
    """Raised when a startup security check fails in production."""
    pass


def _is_production() -> bool:
    """Check if running in production mode. Reads live from env."""
    env = os.getenv("BEA_ENV", os.getenv("ENV", "development")).lower()
    return env in ("production", "prod")


def get_environment() -> str:
    return os.getenv("BEA_ENV", os.getenv("ENV", "development")).lower()


def is_production() -> bool:
    return _is_production()


def check_required_dependencies() -> bool:
    """Vérifie que PyJWT et bcrypt sont installés (dépendances obligatoires)."""
    missing = []
    try:
        import jwt  # noqa: F401
    except ImportError:
        missing.append("PyJWT>=2.0 (pip install PyJWT)")
    try:
        import bcrypt  # noqa: F401
    except ImportError:
        missing.append("bcrypt>=4.0 (pip install bcrypt)")
    if missing:
        raise StartupGuardError(
            "FATAL: Dépendances de sécurité manquantes : " + ", ".join(missing) + ". "
            "Exécutez : pip install -r requirements.txt"
        )
    return True


def check_auth_token() -> bool:
    """Verify BEA_API_TOKEN is set. Fatal in production."""
    token = os.getenv("BEA_API_TOKEN", "").strip()
    if not token:
        if _is_production():
            raise StartupGuardError(
                "FATAL: BEA_API_TOKEN is not set. "
                "Production mode requires authentication. "
                "Set BEA_API_TOKEN in .env or environment."
            )
        log.warning("startup_guard: BEA_API_TOKEN not set — auth disabled (dev mode)")
        return False
    if len(token) < 16:
        if _is_production():
            raise StartupGuardError(
                "FATAL: BEA_API_TOKEN is too short (min 16 chars). "
                "Use a strong random token for production."
            )
        log.warning("startup_guard: BEA_API_TOKEN is short — consider a stronger token")
    return True


def check_secret_key() -> bool:
    """Verify BEA_SECRET_KEY is set. Warning in dev, fatal in prod."""
    key = os.getenv("BEA_SECRET_KEY", "").strip()
    if not key:
        if _is_production():
            raise StartupGuardError(
                "FATAL: BEA_SECRET_KEY is not set. "
                "Required for JWT signing in production."
            )
        log.warning("startup_guard: BEA_SECRET_KEY not set (dev mode)")
        return False
    return True


def check_no_hardcoded_credentials() -> bool:
    """Verify no test/default credentials are used in production."""
    if not _is_production():
        return True
    token = os.getenv("BEA_API_TOKEN", "")
    banned = {"test", "password", "admin", "123456", "secret", "token", "default"}
    if token.lower() in banned:
        raise StartupGuardError(
            "FATAL: BEA_API_TOKEN appears to be a default/test value. "
            "Use a strong random token for production."
        )
    return True


def check_qdrant_api_key() -> bool:
    """Vérifie que QDRANT_API_KEY est défini en production."""
    key = os.getenv("QDRANT_API_KEY", "").strip()
    if not key:
        if _is_production():
            raise StartupGuardError(
                "FATAL: QDRANT_API_KEY is not set. "
                "Qdrant vector store requires authentication in production. "
                "Set QDRANT_API_KEY in .env (must match QDRANT__SERVICE__API_KEY in docker-compose)."
            )
        log.warning("startup_guard: QDRANT_API_KEY not set — Qdrant has no auth (dev mode)")
        return False
    return True


def check_default_langfuse_secrets() -> bool:
    """Vérifie que les secrets Langfuse ne sont pas les valeurs par défaut."""
    if not _is_production():
        return True
    nextauth = os.getenv("LANGFUSE_NEXTAUTH_SECRET", "")
    salt = os.getenv("LANGFUSE_SALT", "")
    defaults = {"changeme-langfuse-secret-32chars0", "changeme-langfuse-salt-32chars000", ""}
    if nextauth in defaults or salt in defaults:
        raise StartupGuardError(
            "FATAL: LANGFUSE_NEXTAUTH_SECRET or LANGFUSE_SALT is set to a default/empty value. "
            "Override both in .env for production."
        )
    return True


def run_all_checks() -> dict:
    """
    Run all startup security checks.

    Returns dict of check results.
    Raises StartupGuardError in production if any critical check fails.
    """
    results = {}
    errors = []

    for name, check in [
        ("required_dependencies", check_required_dependencies),
        ("auth_token", check_auth_token),
        ("secret_key", check_secret_key),
        ("no_hardcoded_creds", check_no_hardcoded_credentials),
        ("qdrant_api_key", check_qdrant_api_key),
        ("langfuse_secrets", check_default_langfuse_secrets),
    ]:
        try:
            results[name] = check()
        except StartupGuardError as e:
            results[name] = False
            errors.append(str(e))
        except Exception as e:
            results[name] = False
            log.error(f"startup_guard: check '{name}' raised: {e}")

    results["environment"] = get_environment()
    results["is_production"] = _is_production()

    if errors:
        msg = "\n".join(errors)
        log.error(f"startup_guard: FAILED\n{msg}")
        if _is_production():
            raise StartupGuardError(f"Startup security checks failed:\n{msg}")

    log.info("startup_guard: all checks passed", extra={"results": results})
    return results
