"""Provider Codex pour Béa — branche gpt-5.3-codex (backend Codex/ChatGPT) comme cerveau.

Réplique le provider `openai-codex` d'Hermes : OAuth sur l'abonnement ChatGPT (PAS de clé
API facturée), endpoint Responses en streaming SSE. On NE passe PAS par la gateway Hermes
(elle n'expose que l'agent `hermes-agent` complet = harness 108k + boucle d'outils) : on tape
le backend Codex directement avec un system prompt minimal (celui de Béa).

Credentials : seedés depuis le pool Hermes (`auth.json`) mais stockés dans un store LOCAL à
Béa. Les refresh_token étant à usage unique, Béa et Hermes ne doivent pas refresher le même —
après le swap (Hermes -> gpt-oss-120b), Béa est seule propriétaire du credential openai-codex.

Expose `CodexChat` avec `async def ainvoke(msgs) -> obj.content`, compatible avec la boucle
agentique de `run_telegram_bea.py` (et utilisable ailleurs).
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path

import httpx

_RESP_URL = "https://chatgpt.com/backend-api/codex/responses"
_TOKEN_URL = "https://auth.openai.com/oauth/token"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"          # client_id officiel du CLI Codex
_MODEL = os.getenv("CODEX_MODEL", "gpt-5.5")   # slug réellement exposé au compte Plus (probe /models)
_REFRESH_SKEW = 120                                   # s d'avance avant expiration

_LOCALAPPDATA = Path(os.getenv("LOCALAPPDATA", str(Path.home())))
_HERMES_AUTH = _LOCALAPPDATA / "hermes" / "auth.json"
_BEA_STORE = Path(os.getenv("BEA_CODEX_AUTH", str(_LOCALAPPDATA / "bea" / "codex_auth.json")))


def _b64url(seg: str) -> bytes:
    seg += "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg)


def _jwt_claims(token: str) -> dict:
    try:
        return json.loads(_b64url(token.split(".")[1]))
    except Exception:  # noqa: BLE001
        return {}


def _account_id(token: str) -> str | None:
    c = _jwt_claims(token)
    auth = c.get("https://api.openai.com/auth") or {}
    return auth.get("chatgpt_account_id") or c.get("chatgpt_account_id")


def _exp(token: str) -> float:
    try:
        return float(_jwt_claims(token).get("exp", 0))
    except Exception:  # noqa: BLE001
        return 0.0


class CodexCredentials:
    """Charge / rafraîchit le couple access_token+refresh_token (store local à Béa)."""

    def __init__(self) -> None:
        self.store = _BEA_STORE
        self.data = self._load()

    def _load(self) -> dict:
        if self.store.exists():
            try:
                return json.loads(self.store.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
        return self._seed_from_hermes()

    def _seed_from_hermes(self) -> dict:
        try:
            h = json.loads(_HERMES_AUTH.read_text(encoding="utf-8"))
            entry = (h.get("credential_pool", {}).get("openai-codex") or [{}])[0]
            d = {"access_token": entry.get("access_token", ""),
                 "refresh_token": entry.get("refresh_token", "")}
            if not d["refresh_token"]:
                raise RuntimeError("aucun refresh_token openai-codex dans le pool Hermes")
            self._save(d)
            return d
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"seed credentials Codex depuis Hermes impossible: {e}") from e

    def _save(self, d: dict) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
        tmp.replace(self.store)

    async def access_token(self) -> str:
        tok = self.data.get("access_token", "")
        if tok and _exp(tok) - _REFRESH_SKEW > time.time():
            return tok
        return await self._refresh()

    async def _refresh(self) -> str:
        rt = self.data.get("refresh_token", "")
        if not rt:
            raise RuntimeError("refresh_token Codex manquant")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": _CLIENT_ID,
            })
        r.raise_for_status()
        j = r.json()
        self.data["access_token"] = j["access_token"]
        if j.get("refresh_token"):                    # refresh_token à usage unique -> rotation
            self.data["refresh_token"] = j["refresh_token"]
        self._save(self.data)
        return self.data["access_token"]


class _Resp:
    __slots__ = ("content",)

    def __init__(self, content: str) -> None:
        self.content = content


class CodexChat:
    """Cerveau Codex exposant `.ainvoke(msgs) -> obj.content` (compatible boucle Béa)."""

    def __init__(self, model: str = _MODEL, temperature: float = 0.3,
                 timeout: int = 120) -> None:
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.creds = CodexCredentials()

    @staticmethod
    def _split(msgs) -> tuple[str, list[dict]]:
        instr: list[str] = []
        inp: list[dict] = []
        for m in msgs:
            role = getattr(m, "type", None) or getattr(m, "role", "") or ""
            content = getattr(m, "content", None)
            if content is None:
                content = str(m)
            if role in ("system", "developer"):
                instr.append(content)
            elif role in ("ai", "assistant"):
                inp.append({"role": "assistant", "content": content})
            else:                                     # human / user / inconnu -> user
                inp.append({"role": "user", "content": content})
        return "\n\n".join(instr), inp

    async def ainvoke(self, msgs):
        token = await self.creds.access_token()
        instr, inp = self._split(msgs)
        body = {
            "model": self.model,
            "instructions": instr or "You are Béa, a helpful autonomous assistant.",
            "input": inp,
            "store": False,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "codex_cli_rs/0.0.0 (Bea Agent)",
            "originator": "codex_cli_rs",
            "session_id": str(uuid.uuid4()),
        }
        acc = _account_id(token)
        if acc:
            headers["ChatGPT-Account-ID"] = acc
        text: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            async with c.stream("POST", _RESP_URL, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    err = (await resp.aread()).decode("utf-8", "replace")[:400]
                    raise RuntimeError(f"codex HTTP {resp.status_code}: {err}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        ev = json.loads(payload)
                    except Exception:  # noqa: BLE001
                        continue
                    t = ev.get("type", "")
                    if t == "response.output_text.delta":
                        text.append(ev.get("delta", ""))
                    elif t in ("response.failed", "error"):
                        raise RuntimeError(f"codex event {t}: {str(ev)[:200]}")
                    elif t == "response.completed" and not text:
                        out = (ev.get("response", {}) or {}).get("output", []) or []
                        for item in out:
                            for ct in item.get("content", []) or []:
                                if ct.get("type") == "output_text":
                                    text.append(ct.get("text", ""))
        return _Resp("".join(text).strip())


async def _smoke() -> None:
    """Test manuel : `python -m gateway.codex_provider`."""
    class _M:
        def __init__(self, role, content):
            self.type = role
            self.content = content
    chat = CodexChat()
    r = await chat.ainvoke([
        _M("system", "Réponds en une phrase, en français."),
        _M("human", "Qui es-tu et quel modèle te propulse ?"),
    ])
    print("REPONSE:", r.content)


if __name__ == "__main__":
    import asyncio
    asyncio.run(_smoke())
