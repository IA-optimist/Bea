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


TOOLS = {
    "execute_shell": execute_shell,
    "execute_python": execute_python,
    "read_file": read_file,
    "write_file": write_file,
}

# Description injectée dans le system prompt (ce que Béa PEUT vraiment faire).
TOOLS_DOC = (
    "execute_shell{command} : exécute une commande shell (ex. scan réseau via `arp -a`, "
    "`ipconfig`, `nslookup`). | execute_python{code} : exécute du Python. | "
    "read_file{path} : lit un fichier. | write_file{path,content} : écrit un fichier."
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
    return None


def run_tool(tc: dict) -> str:
    fn = TOOLS.get(tc.get("tool"))
    if fn is None:
        return f"erreur: outil inconnu '{tc.get('tool')}'. Disponibles : {', '.join(TOOLS)}"
    return fn(tc.get("arguments", {}))
