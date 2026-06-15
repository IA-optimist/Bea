"""web_research_tool — fetch HTTP + recherche PyPI/GitHub."""
from __future__ import annotations
import re

_BLOCKED_HOSTS = (  # nosec B104 — SSRF blocklist, not a bind
    "localhost", "127.0.0.1", "0.0.0.0",
    "10.0.", "10.1.", "10.2.", "10.3.", "10.4.", "10.5.", "10.6.", "10.7.",
    "10.8.", "10.9.", "10.10.", "10.11.", "10.12.", "10.13.", "10.14.", "10.15.",
    "10.16.", "10.17.", "10.18.", "10.19.", "10.20.", "10.21.", "10.22.", "10.23.",
    "10.24.", "10.25.", "10.26.", "10.27.", "10.28.", "10.29.", "10.30.", "10.31.",
    "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.",
    "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
    "172.30.", "172.31.", "192.168.",
)
_MAX_BYTES = 50 * 1024  # 50KB


def _ok(output: str, logs: list = None, risk_level: str = "low") -> dict:
    return {
        "ok": True, "status": "ok",
        "output": output, "result": output,
        "error": None, "logs": logs or [], "risk_level": risk_level,
    }


def _err(error: str, logs: list = None, risk_level: str = "low") -> dict:
    return {
        "ok": False, "status": "error",
        "output": "", "result": "",
        "error": error, "logs": logs or [], "risk_level": risk_level,
    }


def _check_url(url: str) -> str | None:
    for blocked in _BLOCKED_HOSTS:
        if blocked in url:
            return f"blocked_url: {blocked}"
    return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_url(url: str, timeout: int = 10) -> dict:
    try:
        blocked = _check_url(url)
        if blocked:
            return _err(blocked)
        import httpx as _req
        resp = _req.get(url, timeout=timeout)
        raw = resp.content[:_MAX_BYTES].decode("utf-8", errors="replace")
        ct = resp.headers.get("content-type", "")
        if "html" in ct:
            text = _strip_html(raw)
        else:
            text = raw
        output = f"status={resp.status_code} url={url}\n{text[:3000]}"
        return _ok(output, logs=[f"GET {url} → {resp.status_code}"])
    except Exception as e:
        return _err(str(e))


def doc_fetch(url: str, timeout: int = 10) -> dict:
    """Alias fetch_url — retourne texte propre (HTML strippé)."""
    try:
        blocked = _check_url(url)
        if blocked:
            return _err(blocked)
        import httpx as _req
        resp = _req.get(url, timeout=timeout)
        raw = resp.content[:_MAX_BYTES].decode("utf-8", errors="replace")
        text = _strip_html(raw)
        return _ok(text[:3000], logs=[f"doc_fetch GET {url} → {resp.status_code}"])
    except Exception as e:
        return _err(str(e))


def http_post_json(url: str, payload: dict, timeout: int = 10) -> dict:
    """HTTP POST avec corps JSON. Bloqué sur adresses privées."""
    try:
        blocked = _check_url(url)
        if blocked:
            return _err(blocked)
        import httpx as _req
        resp = _req.post(url, json=payload, timeout=timeout)
        try:
            body = resp.json()
            body_str = str(body)[:2000]
        except Exception:
            body_str = resp.text[:2000]
        output = f"status={resp.status_code} url={url}\n{body_str}"
        return _ok(output, logs=[f"POST {url} → {resp.status_code}"])
    except Exception as e:
        return _err(str(e))


def search_pypi(package: str) -> dict:
    try:
        import httpx as _req
        url = f"https://pypi.org/pypi/{package}/json"
        resp = _req.get(url, timeout=10)
        if resp.status_code == 404:
            return _err(f"package_not_found: {package}")
        if resp.status_code != 200:
            return _err(f"pypi_error: status={resp.status_code}")
        data = resp.json()
        info = data.get("info", {})
        result = (
            f"name={info.get('name')} version={info.get('version')}\n"
            f"summary={info.get('summary')}\n"
            f"author={info.get('author')}\n"
            f"license={info.get('license')}\n"
            f"home_page={info.get('home_page')}"
        )
        return _ok(result, logs=[f"pypi {package} → {resp.status_code}"])
    except Exception as e:
        return _err(str(e))


def fetch_github_readme(owner: str, repo: str) -> dict:
    try:
        import httpx as _req
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
        resp = _req.get(url, timeout=10)
        if resp.status_code == 404:
            return _err(f"readme_not_found: {owner}/{repo}")
        if resp.status_code != 200:
            return _err(f"github_error: status={resp.status_code}")
        text = resp.content[:_MAX_BYTES].decode("utf-8", errors="replace")
        return _ok(text[:3000], logs=[f"github_readme {owner}/{repo} → {resp.status_code}"])
    except Exception as e:
        return _err(str(e))


def check_url_status(url: str) -> dict:
    try:
        blocked = _check_url(url)
        if blocked:
            return _err(blocked)
        import httpx as _req
        resp = _req.head(url, timeout=10, follow_redirects=True)
        return _ok(f"status_code={resp.status_code} url={resp.url}",
                   logs=[f"HEAD {url} → {resp.status_code}"])
    except Exception as e:
        return _err(str(e))
