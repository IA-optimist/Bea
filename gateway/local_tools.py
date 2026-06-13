"""Outils LOCAUX réellement exécutables pour Béa (bot Telegram, usage mono-utilisateur).

bea-v31 est entraînée à émettre `<tool_call>{"tool": "...", "arguments": {...}}</tool_call>`.
Ce module exécute POUR DE VRAI les outils génériques que le modèle connaît, sur la machine
de l'utilisateur (qui est l'opérateur du bot, allowlisté à lui-même).

Garde-fous : timeout, blocklist de commandes catastrophiques, troncature des sorties.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

_TIMEOUT = 30          # s par exécution
_MAX_OUT = 4000        # chars de sortie renvoyés au modèle

# Commandes manifestement catastrophiques -> refus dur (le modèle n'est pas parfait).
_BLOCKLIST = re.compile(
    r"(rm\s+-rf\s+/|"
    r"\bdel\b[^|&\n]*\s/[sq]\b|"          # del ... /s ou /q (flags dans n'importe quel ordre)
    r"\b(rd|rmdir)\b[^|&\n]*\s/s\b|"      # rd/rmdir /s (récursif)
    r"format\s+[a-z]:|mkfs|dd\s+if=|"
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
    _SHELL_META = set('|&;<>()$`')
    needs_shell = any(c in _SHELL_META for c in cmd)
    try:
        if needs_shell:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True,  # nosec S602
                               timeout=_TIMEOUT, encoding="utf-8", errors="replace")
        else:
            p = subprocess.run(shlex.split(cmd, posix=False), capture_output=True, text=True,
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


def _ssrf_block(url: str) -> str:
    """Anti-SSRF : refuse les URL résolvant vers une IP interne (loopback/privée/
    link-local/réservée — ex. 127.0.0.1, 10.x, 192.168.x, 169.254.x métadonnées cloud).
    Renvoie un motif de refus, ou '' si l'URL est publique et autorisée."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    if not host:
        return "URL invalide"
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return f"adresse interne ({host})"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001
        return ""        # ne résout pas -> l'appel échouera normalement (pas un bypass)
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return f"adresse interne ({addr})"
    return ""


def web_fetch(args: dict) -> str:
    """Récupère et nettoie le texte d'une page web (lecture)."""
    url = (args.get("url") or args.get("u") or "").strip()
    if not url:
        return "erreur: argument 'url' manquant"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _blk = _ssrf_block(url)
    if _blk:
        return f"REFUSÉ (SSRF): cible {_blk} — accès aux ressources internes interdit."
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


_TODOS: list[dict] = []  # liste de tâches en mémoire (mono-utilisateur)


def todo(args: dict) -> str:
    """Suivi de tâches multi-étapes : action=add|list|done|clear."""
    action = (args.get("action") or "list").strip().lower()
    if action == "add":
        text = (args.get("text") or args.get("task") or "").strip()
        if not text:
            return "erreur: 'text' requis"
        _TODOS.append({"text": text, "done": False})
        return f"ajouté #{len(_TODOS)} : {text}"
    if action in ("done", "complete", "check"):
        try:
            i = int(args.get("id", 0)) - 1
        except (TypeError, ValueError):
            return "erreur: 'id' numérique requis"
        if 0 <= i < len(_TODOS):
            _TODOS[i]["done"] = True
            return f"✅ tâche #{i + 1} faite"
        return "erreur: id invalide"
    if action == "clear":
        _TODOS.clear()
        return "liste vidée"
    if not _TODOS:
        return "(aucune tâche)"
    return "\n".join(f"{i + 1}. [{'x' if t['done'] else ' '}] {t['text']}"
                     for i, t in enumerate(_TODOS))


def image_generate(args: dict) -> str:
    """Génère une image à partir d'un prompt (Pollinations, sans clé) -> fichier."""
    prompt = (args.get("prompt") or args.get("description") or "").strip()
    if not prompt:
        return "erreur: 'prompt' requis"
    try:
        import hashlib
        import os
        import time
        from urllib.parse import quote
        import httpx
        # Pollinations : gratuit mais rate-limité (1 req/IP) -> souvent HTTP 402 "queue full".
        # Un token gratuit (https://enter.pollinations.ai) lève la limite : POLLINATIONS_TOKEN.
        token = os.getenv("POLLINATIONS_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        url = (f"https://image.pollinations.ai/prompt/{quote(prompt)}"
               "?width=1024&height=1024&nologo=true")
        for attempt in range(3):
            r = httpx.get(url, headers=headers, timeout=90, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                out = Path.home() / "Pictures" / "bea"
                out.mkdir(parents=True, exist_ok=True)
                fp = out / (hashlib.md5(prompt.encode()).hexdigest()[:10] + ".jpg")
                fp.write_bytes(r.content)
                return f"ok: image générée -> {fp} ({len(r.content) // 1024} Ko)"
            if r.status_code == 402 and attempt < 2:
                time.sleep(4)
                continue
            if r.status_code == 402:
                return ("service image saturé/rate-limité (Pollinations gratuit = 1 req/IP). "
                        "Pour un accès illimité : token gratuit sur https://enter.pollinations.ai "
                        "puis POLLINATIONS_TOKEN dans .env.")
            return f"erreur: génération image HTTP {r.status_code}"
        return "service image saturé (réessaie dans un instant)."
    except Exception as e:  # noqa: BLE001
        return f"erreur: {e}"


def delegate_task(args: dict) -> str:
    """Délègue une sous-tâche à l'agent COMPLET (cognition via l'API)."""
    task = (args.get("task") or args.get("goal") or args.get("query") or "").strip()
    if not task:
        return "erreur: 'task' requis"
    try:
        import os
        import httpx
        base = os.getenv("BEA_API_URL", "http://127.0.0.1:8000").rstrip("/")
        token = os.getenv("BEA_API_TOKEN", "localdev")
        r = httpx.post(f"{base}/api/v3/chat",
                       json={"message": task, "enable_self_correction": True},
                       headers={"X-Bea-Token": token}, timeout=90)
        if r.status_code == 200:
            return f"[sous-agent] {(r.json().get('response') or '')[:1500]}"
        return f"erreur: agent HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return f"erreur: agent indisponible ({e})"


import concurrent.futures

# Playwright (API sync) est thread-affine : toutes les ops navigateur passent par UN
# unique thread dédié, sinon "cannot switch thread". La page persiste entre les appels.
_BROWSER_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="bea-browser")
_PW: dict = {"pw": None, "browser": None, "page": None}


def _browser_page():
    if _PW["page"] is None:
        from playwright.sync_api import sync_playwright
        _PW["pw"] = sync_playwright().start()
        _PW["browser"] = _PW["pw"].chromium.launch(headless=True)
        _PW["page"] = _PW["browser"].new_page()
    return _PW["page"]


def _browser_sync(args: dict) -> str:
    action = (args.get("action") or "navigate").strip().lower()
    try:
        page = _browser_page()
        if action in ("navigate", "goto", "open"):
            url = (args.get("url") or "").strip()
            if not url:
                return "erreur: 'url' requis"
            if not url.startswith("http"):
                url = "https://" + url
            _blk = _ssrf_block(url)
            if _blk:
                return f"REFUSÉ (SSRF): cible {_blk} — navigation interne interdite."
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            return _truncate(f"[{page.title()}] {page.url}\n{page.inner_text('body')[:1500]}")
        if action == "click":
            if args.get("text") and not args.get("selector"):
                page.get_by_text(args["text"], exact=False).first.click(timeout=10000)
                return f"cliqué (texte): {args['text']}"
            page.click(args.get("selector", ""), timeout=10000)
            return f"cliqué: {args.get('selector')}"
        if action in ("type", "fill"):
            page.fill(args.get("selector", ""), args.get("text", ""), timeout=10000)
            return f"rempli {args.get('selector')} = {str(args.get('text'))[:50]}"
        if action == "get_text":
            return _truncate(page.inner_text("body"))
        if action == "screenshot":
            out = Path.home() / "Pictures" / "bea"
            out.mkdir(parents=True, exist_ok=True)
            fp = out / "screenshot.png"
            page.screenshot(path=str(fp))
            return f"ok: capture -> {fp}"
        if action == "snapshot":
            links = page.eval_on_selector_all(
                "a[href]", "els => els.slice(0,15).map(e => e.innerText.trim().slice(0,40)+' -> '+e.href)")
            inputs = page.eval_on_selector_all(
                "input,textarea,button", "els => els.slice(0,15).map(e => (e.tagName+' '+(e.name||e.id||e.type||e.innerText||'')).trim().slice(0,50))")
            return _truncate("Liens:\n" + "\n".join(links) + "\n\nChamps/boutons:\n" + "\n".join(inputs))
        return f"erreur: action inconnue '{action}' (navigate|click|type|get_text|screenshot|snapshot)"
    except Exception as e:  # noqa: BLE001
        return f"erreur browser: {str(e)[:200]}"


def browser(args: dict) -> str:
    """Navigateur réel (Playwright/Chromium headless), session persistante."""
    try:
        return _BROWSER_EXEC.submit(_browser_sync, args).result(timeout=70)
    except Exception as e:  # noqa: BLE001
        return f"erreur browser: {str(e)[:200]}"


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
    "todo": todo,
    "image_generate": image_generate,
    "delegate_task": delegate_task,
    "browser": browser,
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
    "— renvoie titres+URL+extraits. | web_fetch{url} : lit le contenu texte d'une page web. | "
    "todo{action,text,id} : liste de tâches (action=add|list|done|clear). | "
    "image_generate{prompt} : génère une image (-> fichier). | "
    "delegate_task{task} : délègue une sous-tâche à l'agent complet (cognition). | "
    "browser{action,url,selector,text} : navigateur réel (action=navigate|click|type|"
    "get_text|screenshot|snapshot) pour les sites interactifs/JS."
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

    # Raccourci texte : <nom_outil>valeur</nom_outil> (valeur = argument principal).
    _PRIMARY = {"web_search": "query", "knowledge_search": "query", "web_fetch": "url",
                "execute_shell": "command", "execute_python": "code", "read_file": "path",
                "list_dir": "path", "grep_search": "pattern", "glob_search": "pattern",
                "image_generate": "prompt", "delegate_task": "task"}
    for mm in re.finditer(r"<([a-zA-Z_][a-zA-Z0-9_]*)\s*>", text):
        name = mm.group(1)
        if name not in _PRIMARY:
            continue
        rest = text[mm.end():]
        end = rest.find(f"</{name}>")
        content = (rest[:end] if end != -1 else rest.split("<", 1)[0]).strip()
        if content and not content.startswith("{"):
            return {"tool": name, "arguments": {_PRIMARY[name]: content}}
    # Dernier recours (structured_output / PydanticAI) : un JSON {"tool":…} noyé dans la prose.
    try:
        from core.structured_output import extract_json
        d = extract_json(text)
        if isinstance(d, dict) and d.get("tool"):
            return {"tool": d["tool"], "arguments": d.get("arguments", {}) or {}}
    except Exception:  # noqa: BLE001
        pass
    return None


def run_tool(tc: dict) -> str:
    fn = TOOLS.get(tc.get("tool"))
    if fn is None:
        return f"erreur: outil inconnu '{tc.get('tool')}'. Disponibles : {', '.join(TOOLS)}"
    return fn(tc.get("arguments", {}))
