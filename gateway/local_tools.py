"""Outils LOCAUX réellement exécutables pour Béa (bot Telegram, usage mono-utilisateur).

bea-v31 est entraînée à émettre `<tool_call>{"tool": "...", "arguments": {...}}</tool_call>`.
Ce module exécute POUR DE VRAI les outils génériques que le modèle connaît, sur la machine
de l'utilisateur (qui est l'opérateur du bot, allowlisté à lui-même).

Garde-fous : timeout, blocklist de commandes catastrophiques, troncature des sorties.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_TIMEOUT = 30          # s par exécution
_MAX_OUT = 4000        # chars de sortie renvoyés au modèle

# Commandes manifestement catastrophiques -> refus dur (le modèle n'est pas parfait).
_BLOCKLIST = re.compile(
    r"\b(rm\s+-rf\s+/|del\s+/[sq]|format\s+[a-z]:|mkfs|dd\s+if=|"
    r":\(\)\s*\{|shutdown|Remove-Item.*-Recurse.*-Force.*[A-Za-z]:\\)",
    re.IGNORECASE,
)

# Outils nécessitant une confirmation explicite avant exécution (action réelle/destructive).
RISKY = {"execute_shell", "execute_python", "write_file"}


def _truncate(s: str) -> str:
    s = s or ""
    return s if len(s) <= _MAX_OUT else s[:_MAX_OUT] + f"\n…(tronqué, {len(s)} chars)"


def execute_shell(args: dict) -> str:
    cmd = (args.get("command") or args.get("cmd") or "").strip()
    if not cmd:
        return "erreur: argument 'command' manquant"
    if _BLOCKLIST.search(cmd):
        return "REFUSÉ: commande bloquée (potentiellement destructive)."
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=_TIMEOUT, encoding="utf-8", errors="replace")
        out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
        return _truncate(out.strip() or f"(code {p.returncode}, aucune sortie)")
    except subprocess.TimeoutExpired:
        return f"erreur: timeout après {_TIMEOUT}s"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def execute_python(args: dict) -> str:
    code = (args.get("code") or args.get("script") or "").strip()
    if not code:
        return "erreur: argument 'code' manquant"
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=_TIMEOUT, encoding="utf-8", errors="replace")
        out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
        return _truncate(out.strip() or f"(code {p.returncode}, aucune sortie)")
    except subprocess.TimeoutExpired:
        return f"erreur: timeout après {_TIMEOUT}s"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def read_file(args: dict) -> str:
    path = (args.get("path") or args.get("file") or "").strip()
    if not path:
        return "erreur: argument 'path' manquant"
    try:
        return _truncate(Path(path).expanduser().read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def write_file(args: dict) -> str:
    path = (args.get("path") or args.get("file") or "").strip()
    content = args.get("content", "")
    if not path:
        return "erreur: argument 'path' manquant"
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(content), encoding="utf-8")
        return f"ok: {len(str(content))} chars écrits dans {p}"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def edit_file(args: dict) -> str:
    """Remplacement ciblé d'une chaîne dans un fichier (comme un éditeur)."""
    path = (args.get("path") or args.get("file") or "").strip()
    old = args.get("old", args.get("old_string"))
    new = args.get("new", args.get("new_string", ""))
    if not path or old is None:
        return "erreur: 'path' et 'old' requis"
    try:
        p = Path(path).expanduser()
        content = p.read_text(encoding="utf-8", errors="replace")
        n = content.count(old)
        if n == 0:
            return f"erreur: texte introuvable dans {p.name}"
        if n > 1 and not args.get("all"):
            return f"erreur: '{old[:40]}…' apparaît {n}× — ajoute du contexte ou all=true"
        p.write_text(content.replace(old, str(new)), encoding="utf-8")
        return f"ok: {n if args.get('all') else 1} remplacement(s) dans {p}"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def list_dir(args: dict) -> str:
    """Liste le contenu d'un dossier."""
    path = (args.get("path") or args.get("dir") or ".").strip()
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"erreur: introuvable: {p}"
        if p.is_file():
            return f"📄 {p} ({p.stat().st_size} o)"
        out = []
        for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:300]:
            out.append(f"📁 {c.name}/" if c.is_dir() else f"📄 {c.name}  ({c.stat().st_size} o)")
        return "\n".join(out) or "(dossier vide)"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def grep_search(args: dict) -> str:
    """Cherche un motif (regex) dans les fichiers d'un dossier."""
    pattern = (args.get("pattern") or args.get("query") or "").strip()
    path = (args.get("path") or ".").strip()
    if not pattern:
        return "erreur: 'pattern' requis"
    _skip = ("__pycache__", ".git", "node_modules", ".venv", ".mypy_cache", ".ruff_cache")
    try:
        rx = re.compile(pattern, re.IGNORECASE)
        root = Path(path).expanduser()
        files = [root] if root.is_file() else list(root.rglob("*"))
        out, scanned = [], 0
        for f in files:
            if not f.is_file() or any(s in str(f) for s in _skip):
                continue
            scanned += 1
            if scanned > 3000:
                break
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        out.append(f"{f}:{i}: {line.strip()[:150]}")
                        if len(out) >= 60:
                            return "\n".join(out) + "\n…(tronqué)"
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(out) if out else "AUCUN_RESULTAT"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def glob_search(args: dict) -> str:
    """Trouve des fichiers par motif glob (ex. **/*.py)."""
    pattern = (args.get("pattern") or args.get("glob") or "").strip()
    path = (args.get("path") or ".").strip()
    if not pattern:
        return "erreur: 'pattern' requis"
    try:
        root = Path(path).expanduser()
        hits = [str(p) for p in sorted(root.rglob(pattern))[:150]
                if not any(s in str(p) for s in ("__pycache__", ".git", ".venv"))]
        return "\n".join(hits) if hits else "AUCUN_FICHIER"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _ddg_unwrap(href: str) -> str:
    """Décode les liens de redirection DuckDuckGo //duckduckgo.com/l/?uddg=…"""
    if "duckduckgo.com/l/" in href and "uddg=" in href:
        from urllib.parse import parse_qs, unquote, urlparse
        q = parse_qs(urlparse(href).query).get("uddg")
        if q:
            return unquote(q[0])
    return href if href.startswith("http") else ("https:" + href if href.startswith("//") else href)


def web_search(args: dict) -> str:
    """Recherche web (DuckDuckGo HTML, sans clé). Renvoie titres + URL + extraits."""
    query = (args.get("query") or args.get("q") or "").strip()
    if not query:
        return "erreur: argument 'query' manquant"
    try:
        import httpx
        from bs4 import BeautifulSoup
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query},
                       headers={"User-Agent": _UA}, timeout=20, follow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for res in soup.select(".result")[:6]:
            a = res.select_one(".result__a")
            if not a:
                continue
            title = a.get_text(strip=True)
            url = _ddg_unwrap(a.get("href", ""))
            snip = res.select_one(".result__snippet")
            snippet = snip.get_text(" ", strip=True) if snip else ""
            out.append(f"- {title}\n  {url}\n  {snippet[:220]}")
        return "\n".join(out) if out else "AUCUN_RESULTAT_WEB"
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def web_fetch(args: dict) -> str:
    """Récupère et nettoie le texte d'une page web (lecture)."""
    url = (args.get("url") or args.get("u") or "").strip()
    if not url:
        return "erreur: argument 'url' manquant"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        import httpx
        from bs4 import BeautifulSoup
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=20, follow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        return _truncate(text or "(page vide)")
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


_KB = None  # cache de la KnowledgeBase (évite de recharger le store JSON à chaque appel)


def knowledge_search(args: dict) -> str:
    """RAG : cherche dans la base de connaissances locale de Béa (notes ingérées)."""
    global _KB
    query = (args.get("query") or args.get("q") or args.get("question") or "").strip()
    if not query:
        return "erreur: argument 'query' manquant"
    try:
        if _KB is None:
            from config.settings import get_settings
            from memory.knowledge_base import KnowledgeBase
            _KB = KnowledgeBase(get_settings())
        hits = _KB.search(query, top_k=4)
        if not hits:
            return ("AUCUN_RESULTAT: rien de pertinent dans la base de connaissances. "
                    "Ne devine pas — dis que l'information n'y est pas.")
        return "\n\n".join(f"[source: {h['source']} · pertinence {h['score']}]\n{h['text'][:700]}"
                           for h in hits)
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


TOOLS = {
    "execute_shell": execute_shell,
    "execute_python": execute_python,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "grep_search": grep_search,
    "glob_search": glob_search,
    "knowledge_search": knowledge_search,
    "web_search": web_search,
    "web_fetch": web_fetch,
}

# Description injectée dans le system prompt (ce que Béa PEUT vraiment faire).
TOOLS_DOC = (
    "execute_shell{command} : exécute une commande shell (ex. scan réseau via `arp -a`, "
    "`ipconfig`, `nslookup`). | execute_python{code} : exécute du Python. | "
    "read_file{path} : lit un fichier. | write_file{path,content} : écrit/crée un fichier. | "
    "edit_file{path,old,new} : remplace une chaîne précise dans un fichier (édition ciblée). | "
    "list_dir{path} : liste un dossier. | grep_search{pattern,path} : cherche un motif regex "
    "dans des fichiers. | glob_search{pattern,path} : trouve des fichiers (ex. **/*.py). | "
    "knowledge_search{query} : cherche dans la base de connaissances/notes de l'utilisateur "
    "(RAG) — renvoie des extraits sourcés ou AUCUN_RESULTAT. | "
    "web_search{query} : recherche sur INTERNET (actualités, infos récentes, faits externes) "
    "— renvoie titres+URL+extraits. | web_fetch{url} : lit le contenu texte d'une page web."
)

_TOOLCALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _balanced_json(s: str, start: int) -> str | None:
    """Renvoie la sous-chaîne JSON {…} équilibrée à partir de `start`, ou None."""
    if start < 0 or start >= len(s) or s[start] != "{":
        return None
    depth = 0
    in_str = esc = False
    for i in range(start, len(s)):
        c = s[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def parse_tool_call(text: str) -> dict | None:
    """Extrait un appel d'outil, tolérant aux variantes des modèles.

    Gère : <tool_call>{…}</tool_call> (strict), <tool_call>{…} sans fermeture,
    et un JSON nu {"tool":…,"arguments":…} (certains modèles omettent les balises).
    """
    text = text or ""
    candidates: list[str] = []
    m = _TOOLCALL_RE.search(text)
    if m:
        candidates.append(m.group(1))
    idx = text.find("<tool_call>")
    if idx != -1:
        b = _balanced_json(text, text.find("{", idx))
        if b:
            candidates.append(b)
    for mm in re.finditer(r"\{", text):       # JSON nu contenant "tool"
        b = _balanced_json(text, mm.start())
        if b and '"tool"' in b:
            candidates.append(b)
            break
    for raw in candidates:
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and d.get("tool"):
            return {"tool": d["tool"], "arguments": d.get("arguments", {}) or {}}

    # Raccourci inventé par certains modèles : <nom_outil{...}> (le JSON = les arguments).
    for mm in re.finditer(r"<([a-zA-Z_][a-zA-Z0-9_]*)\s*(\{)", text):
        name = mm.group(1)
        if name in TOOLS:
            b = _balanced_json(text, mm.start(2))
            if not b:
                continue
            try:
                args = json.loads(b)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(args, dict):
                return {"tool": name, "arguments": args}
    return None


def run_tool(tc: dict) -> str:
    fn = TOOLS.get(tc.get("tool"))
    if fn is None:
        return f"erreur: outil inconnu '{tc.get('tool')}'. Disponibles : {', '.join(TOOLS)}"
    return fn(tc.get("arguments", {}))
