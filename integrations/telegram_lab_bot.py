"""
Telegram bridge for the JarvisMax AI lab.

This bot runs as a standalone polling worker. It can talk to:
1. OpenClaw lab agents for specialist "AI lab" interactions
2. JarvisMax local API as a fallback or direct mission backend
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("jarvismax.telegram_lab_bot")

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_BOT_STATE_FILE = "telegram_lab_bot_state.json"
TERMINAL_MISSION_STATUSES = {"DONE", "COMPLETED", "FAILED", "CANCELLED", "REJECTED"}
OPENCLAW_TEXT_KEYS = (
    "reply",
    "response",
    "output",
    "content",
    "text",
    "message",
    "final_output",
    "answer",
    "summary",
)
JARVIS_TEXT_KEYS = (
    "final_output",
    "result",
    "output",
    "summary",
    "response",
    "content",
    "message",
)
AGENT_ALIASES = {
    "director": "lab-director",
    "atlas": "lab-director",
    "architect": "lab-architect",
    "arch": "lab-architect",
    "ml": "lab-ml-engineer",
    "engineer": "lab-ml-engineer",
    "senior": "lab-senior-dev",
    "dev": "lab-senior-dev",
    "research": "lab-researcher",
    "researcher": "lab-researcher",
    "review": "lab-reviewer",
    "reviewer": "lab-reviewer",
    "qa": "lab-qa",
    "ops": "lab-devops",
    "devops": "lab-devops",
    "security": "lab-security",
    "sec": "lab-security",
    "data": "lab-data",
}
AGENT_LABELS = {
    "lab-director": "Atlas Director",
    "lab-architect": "System Architect",
    "lab-ml-engineer": "ML Engineer",
    "lab-senior-dev": "Senior Developer",
    "lab-researcher": "Researcher",
    "lab-reviewer": "Code Reviewer",
    "lab-qa": "QA Lead",
    "lab-devops": "DevOps Engineer",
    "lab-security": "Security Auditor",
    "lab-data": "Data Engineer",
}
SPECIALIST_COMMANDS = {
    "director": "lab-director",
    "architect": "lab-architect",
    "ml": "lab-ml-engineer",
    "dev": "lab-senior-dev",
    "research": "lab-researcher",
    "review": "lab-reviewer",
    "qa": "lab-qa",
    "ops": "lab-devops",
    "security": "lab-security",
    "data": "lab-data",
}


class BackendFailure(RuntimeError):
    """Raised when a bot backend cannot fulfill a request."""


def _parse_bool(raw: str, default: bool = False) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_float(raw: str, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_id_set(*values: str) -> set[str]:
    parsed: set[str] = set()
    for raw in values:
        if not raw:
            continue
        for item in raw.replace(";", ",").split(","):
            cleaned = item.strip()
            if cleaned:
                parsed.add(cleaned)
    return parsed


def _normalize_mode(raw: str) -> str:
    value = (raw or "lab").strip().lower()
    if value not in {"lab", "mission"}:
        raise ValueError("mode must be 'lab' or 'mission'")
    return value


def _normalize_backend(raw: str) -> str:
    value = (raw or "auto").strip().lower()
    if value not in {"auto", "openclaw", "jarvis"}:
        raise ValueError("backend must be auto, openclaw, or jarvis")
    return value


def normalize_agent(raw: str) -> str:
    value = (raw or "").strip().lower()
    if not value:
        return "lab-director"
    if value in AGENT_LABELS:
        return value
    if value in AGENT_ALIASES:
        return AGENT_ALIASES[value]
    if value.startswith("lab-") and value in AGENT_LABELS:
        return value
    raise ValueError(f"unknown agent alias: {raw}")


def agent_help_lines() -> list[str]:
    return [
        "director, architect, ml, dev, research, review, qa, ops, security, data",
        "Current roster:",
        *[f"- {agent_id}: {label}" for agent_id, label in AGENT_LABELS.items()],
    ]


def _extract_text_candidate(payload: Any, keys: tuple[str, ...]) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            text = _extract_text_candidate(value, keys)
            if text:
                return text
        for value in payload.values():
            text = _extract_text_candidate(value, keys)
            if text:
                return text
        return ""
    if isinstance(payload, list):
        for item in payload:
            text = _extract_text_candidate(item, keys)
            if text:
                return text
        return ""
    return str(payload).strip()


def _safe_json_loads(raw: str) -> Any:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def chunk_text(text: str, limit: int = 3500) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return ["No response returned."]
    chunks: list[str] = []
    remaining = raw
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def build_lab_goal(agent_id: str, message: str) -> str:
    label = AGENT_LABELS.get(agent_id, agent_id)
    return (
        "AI lab mode for JarvisMax.\n"
        f"Specialist requested: {label} ({agent_id}).\n"
        "Treat the repository as the active workspace.\n"
        "If the task spans multiple specialties, answer first and then say which specialist should review next.\n"
        "User request:\n"
        f"{message.strip()}"
    )


@dataclass
class TelegramLabConfig:
    telegram_bot_token: str
    repo_root: Path
    state_file: Path
    api_base_url: str = DEFAULT_API_BASE_URL
    api_token: str = ""
    admin_password: str = ""
    allowed_chat_ids: set[str] = field(default_factory=set)
    allowed_user_ids: set[str] = field(default_factory=set)
    default_mode: str = "lab"
    default_backend: str = "auto"
    default_agent: str = "lab-director"
    polling_timeout_s: int = 25
    request_timeout_s: int = 30
    mission_timeout_s: int = 600
    mission_poll_interval_s: float = 2.5
    openclaw_timeout_s: int = 600
    openclaw_binary: str = "openclaw"
    openclaw_thinking: str = "minimal"
    openclaw_local: bool = False

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "TelegramLabConfig":
        repo = (repo_root or Path(__file__).resolve().parent.parent).resolve()
        workspace_dir = Path(os.getenv("WORKSPACE_DIR", str(repo / "workspace")))
        state_file = Path(
            os.getenv(
                "TELEGRAM_LAB_STATE_FILE",
                str(workspace_dir / DEFAULT_BOT_STATE_FILE),
            )
        )
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        return cls(
            telegram_bot_token=token,
            repo_root=repo,
            state_file=state_file,
            api_base_url=os.getenv("JARVIS_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/"),
            api_token=os.getenv("JARVIS_API_TOKEN", "").strip(),
            admin_password=os.getenv("JARVIS_ADMIN_PASSWORD", "").strip(),
            allowed_chat_ids=_parse_id_set(
                os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", ""),
                os.getenv("TELEGRAM_CHAT_ID", ""),
                os.getenv("TELEGRAM_TARGET_CHAT_ID", ""),
            ),
            allowed_user_ids=_parse_id_set(
                os.getenv("TELEGRAM_ALLOWED_USER_IDS", ""),
                os.getenv("TELEGRAM_ALLOWED_USER_ID", ""),
            ),
            default_mode=_normalize_mode(os.getenv("TELEGRAM_LAB_MODE", "lab")),
            default_backend=_normalize_backend(os.getenv("TELEGRAM_LAB_BACKEND", "auto")),
            default_agent=normalize_agent(os.getenv("TELEGRAM_LAB_AGENT", "lab-director")),
            polling_timeout_s=_parse_int(os.getenv("TELEGRAM_POLL_TIMEOUT_S", "25"), 25),
            request_timeout_s=_parse_int(os.getenv("TELEGRAM_HTTP_TIMEOUT_S", "30"), 30),
            mission_timeout_s=_parse_int(os.getenv("TELEGRAM_LAB_MISSION_TIMEOUT_S", "600"), 600),
            mission_poll_interval_s=_parse_float(os.getenv("TELEGRAM_LAB_POLL_INTERVAL_S", "2.5"), 2.5),
            openclaw_timeout_s=_parse_int(os.getenv("TELEGRAM_LAB_OPENCLAW_TIMEOUT_S", "600"), 600),
            openclaw_binary=os.getenv("TELEGRAM_LAB_OPENCLAW_BIN", "openclaw").strip() or "openclaw",
            openclaw_thinking=os.getenv("TELEGRAM_LAB_OPENCLAW_THINKING", "minimal").strip() or "minimal",
            openclaw_local=_parse_bool(os.getenv("TELEGRAM_LAB_OPENCLAW_LOCAL", ""), False),
        )

    def default_state(self) -> "ChatState":
        return ChatState(
            mode=self.default_mode,
            backend=self.default_backend,
            agent=self.default_agent,
        )


@dataclass
class ChatState:
    mode: str = "lab"
    backend: str = "auto"
    agent: str = "lab-director"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None, defaults: "ChatState") -> "ChatState":
        payload = payload or {}
        return cls(
            mode=_normalize_mode(payload.get("mode", defaults.mode)),
            backend=_normalize_backend(payload.get("backend", defaults.backend)),
            agent=normalize_agent(payload.get("agent", defaults.agent)),
        )


class ChatStateStore:
    def __init__(self, path: Path, defaults: ChatState):
        self.path = path
        self.defaults = defaults
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"offset": 0, "chats": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("telegram_lab_state_load_failed path=%s", self.path)
            return {"offset": 0, "chats": {}}

    def save(self) -> None:
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.path)

    @property
    def offset(self) -> int:
        return int(self._data.get("offset", 0) or 0)

    @offset.setter
    def offset(self, value: int) -> None:
        self._data["offset"] = int(value)

    def get_chat_state(self, chat_id: str) -> ChatState:
        chats = self._data.setdefault("chats", {})
        if chat_id not in chats:
            chats[chat_id] = asdict(self.defaults)
        return ChatState.from_dict(chats.get(chat_id), self.defaults)

    def set_chat_state(self, chat_id: str, state: ChatState) -> None:
        chats = self._data.setdefault("chats", {})
        chats[chat_id] = asdict(state)

    def reset_chat_state(self, chat_id: str) -> ChatState:
        state = ChatState.from_dict(asdict(self.defaults), self.defaults)
        self.set_chat_state(chat_id, state)
        return state


@dataclass
class BackendResult:
    backend: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class TelegramApiClient:
    def __init__(self, token: str, request_timeout_s: int = 30):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout_s = request_timeout_s

    def get_updates(self, offset: int, timeout_s: int) -> list[dict[str, Any]]:
        response = httpx.post(
            f"{self.base_url}/getUpdates",
            data={"offset": offset, "timeout": timeout_s},
            timeout=timeout_s + 10,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {payload}")
        return payload.get("result", [])

    def send_message(self, chat_id: str, text: str, reply_to_message_id: int | None = None) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        response = httpx.post(
            f"{self.base_url}/sendMessage",
            data=payload,
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {body}")


class OpenClawLabBackend:
    def __init__(self, config: TelegramLabConfig):
        self.config = config

    def run(self, agent_id: str, message: str) -> BackendResult:
        cmd = [
            self.config.openclaw_binary,
            "agent",
            "--agent",
            agent_id,
            "--json",
            "--message",
            message,
            "--thinking",
            self.config.openclaw_thinking,
            "--timeout",
            str(self.config.openclaw_timeout_s),
        ]
        if self.config.openclaw_local:
            cmd.append("--local")
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.openclaw_timeout_s + 15,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BackendFailure(f"OpenClaw binary not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise BackendFailure("OpenClaw agent timed out") from exc

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if completed.returncode != 0:
            message = stderr or stdout or f"OpenClaw exited with code {completed.returncode}"
            raise BackendFailure(message)

        parsed = _safe_json_loads(stdout)
        text = _extract_text_candidate(parsed, OPENCLAW_TEXT_KEYS) if parsed is not None else stdout
        text = text or stdout
        if not text:
            raise BackendFailure("OpenClaw returned no usable response text")
        return BackendResult(backend="openclaw", text=text)


class JarvisApiBackend:
    def __init__(self, config: TelegramLabConfig):
        self.config = config
        self._jwt_token = ""

    def _auth_headers(self) -> dict[str, str]:
        token = self.config.api_token or self._jwt_token
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def _authenticate(self, client: httpx.Client) -> None:
        if self.config.api_token or self._jwt_token or not self.config.admin_password:
            return
        response = client.post(
            f"{self.config.api_base_url}/auth/token",
            data={"username": "admin", "password": self.config.admin_password},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token", "").strip()
        if not token:
            raise BackendFailure("Jarvis auth succeeded but returned no access token")
        self._jwt_token = token

    def _request_with_fallback_auth(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        response = client.request(
            method,
            f"{self.config.api_base_url}{path}",
            json=json_payload,
            headers=self._auth_headers(),
        )
        if response.status_code == 401 and self.config.admin_password:
            self._authenticate(client)
            response = client.request(
                method,
                f"{self.config.api_base_url}{path}",
                json=json_payload,
                headers=self._auth_headers(),
            )
        return response

    def _submit_mission(self, client: httpx.Client, goal: str) -> str:
        candidates = [
            ("/api/v3/missions", {"goal": goal, "mode": "AUTO"}),
            ("/api/v2/missions/submit", {"goal": goal, "mode": "auto"}),
        ]
        errors: list[str] = []
        for path, payload in candidates:
            response = self._request_with_fallback_auth(client, "POST", path, json_payload=payload)
            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                errors.append(f"{path}: {response.status_code} {response.text[:200]}")
                continue
            body = response.json()
            data = body.get("data", body)
            mission_id = (data.get("mission_id") or data.get("task_id") or "").strip()
            if mission_id:
                return mission_id
            errors.append(f"{path}: no mission_id in response")
        raise BackendFailure("Jarvis mission submit failed: " + "; ".join(errors))

    def _get_mission_state(self, client: httpx.Client, mission_id: str) -> dict[str, Any]:
        candidates = [f"/api/v3/missions/{mission_id}", f"/api/v2/missions/{mission_id}"]
        errors: list[str] = []
        for path in candidates:
            response = self._request_with_fallback_auth(client, "GET", path)
            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                errors.append(f"{path}: {response.status_code} {response.text[:200]}")
                continue
            body = response.json()
            return body.get("data", body)
        raise BackendFailure("Jarvis mission poll failed: " + "; ".join(errors))

    def run(self, goal: str) -> BackendResult:
        with httpx.Client(timeout=self.config.request_timeout_s) as client:
            mission_id = self._submit_mission(client, goal)
            deadline = time.time() + self.config.mission_timeout_s
            last_status = "CREATED"
            last_payload: dict[str, Any] = {}
            while time.time() < deadline:
                payload = self._get_mission_state(client, mission_id)
                last_payload = payload
                last_status = str(payload.get("status", "UNKNOWN")).upper()
                if last_status in TERMINAL_MISSION_STATUSES:
                    break
                time.sleep(self.config.mission_poll_interval_s)
            else:
                raise BackendFailure(
                    f"Jarvis mission timeout after {self.config.mission_timeout_s}s "
                    f"(mission_id={mission_id}, status={last_status})"
                )

        if last_status not in TERMINAL_MISSION_STATUSES:
            raise BackendFailure(f"Jarvis mission ended in non-terminal status: {last_status}")

        text = _extract_text_candidate(last_payload, JARVIS_TEXT_KEYS)
        if last_status in {"FAILED", "CANCELLED", "REJECTED"}:
            error_text = text or last_payload.get("failure_reason") or last_payload.get("error") or last_status
            raise BackendFailure(f"Jarvis mission {last_status.lower()}: {error_text}")

        if not text:
            raise BackendFailure(f"Jarvis mission completed without result text (mission_id={mission_id})")

        return BackendResult(
            backend="jarvis",
            text=text,
            metadata={"mission_id": mission_id, "status": last_status},
        )


class TelegramLabBot:
    def __init__(
        self,
        config: TelegramLabConfig,
        *,
        telegram_client: TelegramApiClient | None = None,
        state_store: ChatStateStore | None = None,
        openclaw_backend: OpenClawLabBackend | None = None,
        jarvis_backend: JarvisApiBackend | None = None,
    ):
        self.config = config
        self.telegram_client = telegram_client or TelegramApiClient(
            config.telegram_bot_token,
            request_timeout_s=config.request_timeout_s,
        )
        self.state_store = state_store or ChatStateStore(config.state_file, config.default_state())
        self.openclaw_backend = openclaw_backend or OpenClawLabBackend(config)
        self.jarvis_backend = jarvis_backend or JarvisApiBackend(config)

    def _is_authorized(self, chat_id: str, user_id: str) -> bool:
        if self.config.allowed_chat_ids and chat_id not in self.config.allowed_chat_ids:
            return False
        if self.config.allowed_user_ids and user_id not in self.config.allowed_user_ids:
            return False
        return True

    def _status_text(self, state: ChatState) -> str:
        return (
            "JarvisMax Telegram lab bot\n"
            f"- mode: {state.mode}\n"
            f"- backend: {state.backend}\n"
            f"- agent: {state.agent} ({AGENT_LABELS.get(state.agent, state.agent)})\n"
            f"- repo: {self.config.repo_root}\n"
            f"- state file: {self.config.state_file}"
        )

    def _help_text(self) -> str:
        return "\n".join(
            [
                "Commands:",
                "/start or /help - show this help",
                "/status - show current bot state",
                "/mode lab|mission - switch between lab routing and direct Jarvis missions",
                "/backend auto|openclaw|jarvis - select execution backend",
                "/agent <alias> - pick the specialist for lab mode",
                "/agents - list specialist aliases",
                "/reset - reset this chat to default state",
                "/ask <text> - run a request with the current state",
                "/mission <text> - one-off Jarvis mission request",
                "/director|/architect|/ml|/dev|/research|/review|/qa|/ops|/security|/data <text> - one-off specialist request",
                "",
                "Plain text in lab mode goes to the selected specialist. Default is lab-director.",
            ]
        )

    def _handle_command(self, chat_id: str, state: ChatState, command: str, argument: str) -> tuple[ChatState, str]:
        if command in {"start", "help"}:
            return state, self._help_text()
        if command == "status":
            return state, self._status_text(state)
        if command == "agents":
            return state, "\n".join(agent_help_lines())
        if command == "mode":
            if not argument:
                return state, "Usage: /mode lab|mission"
            state.mode = _normalize_mode(argument)
            self.state_store.set_chat_state(chat_id, state)
            self.state_store.save()
            return state, self._status_text(state)
        if command == "backend":
            if not argument:
                return state, "Usage: /backend auto|openclaw|jarvis"
            state.backend = _normalize_backend(argument)
            self.state_store.set_chat_state(chat_id, state)
            self.state_store.save()
            return state, self._status_text(state)
        if command == "agent":
            if not argument:
                return state, "Usage: /agent director|architect|ml|dev|research|review|qa|ops|security|data"
            state.agent = normalize_agent(argument)
            state.mode = "lab"
            self.state_store.set_chat_state(chat_id, state)
            self.state_store.save()
            return state, self._status_text(state)
        if command == "reset":
            state = self.state_store.reset_chat_state(chat_id)
            self.state_store.save()
            return state, self._status_text(state)
        if command == "ask":
            if not argument:
                return state, "Usage: /ask <text>"
            return state, self._run_request(state, argument)
        if command == "mission":
            if not argument:
                return state, "Usage: /mission <text>"
            mission_state = ChatState(mode="mission", backend="jarvis", agent=state.agent)
            return state, self._run_request(mission_state, argument)
        if command in SPECIALIST_COMMANDS:
            if not argument:
                return state, f"Usage: /{command} <text>"
            specialist_state = ChatState(mode="lab", backend=state.backend, agent=SPECIALIST_COMMANDS[command])
            return state, self._run_request(specialist_state, argument)
        return state, f"Unknown command: /{command}\n\n{self._help_text()}"

    def _run_request(self, state: ChatState, text: str) -> str:
        if state.mode == "mission":
            result = self.jarvis_backend.run(text)
            return result.text

        if state.backend in {"auto", "openclaw"}:
            try:
                result = self.openclaw_backend.run(state.agent, text)
                return result.text
            except BackendFailure as exc:
                if state.backend == "openclaw":
                    raise
                log.warning(
                    "telegram_lab_openclaw_fallback agent=%s err=%s",
                    state.agent,
                    str(exc)[:240],
                )
                fallback_prompt = build_lab_goal(state.agent, text)
                jarvis_result = self.jarvis_backend.run(fallback_prompt)
                return (
                    "OpenClaw was unavailable for this request. Falling back to JarvisMax API.\n\n"
                    f"{jarvis_result.text}"
                )

        fallback_prompt = build_lab_goal(state.agent, text)
        result = self.jarvis_backend.run(fallback_prompt)
        return result.text

    def handle_text(self, chat_id: str, user_id: str, text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return ["Empty messages are ignored."]
        log.info("telegram_lab_message_received", extra={"chat_id": chat_id, "user_id": user_id})
        if not self._is_authorized(chat_id, user_id):
            return ["Access denied for this chat."]

        state = self.state_store.get_chat_state(chat_id)
        try:
            if text.startswith("/"):
                command_line = text.split(None, 1)
                command = command_line[0][1:].split("@", 1)[0].strip().lower()
                argument = command_line[1].strip() if len(command_line) > 1 else ""
                _, response = self._handle_command(chat_id, state, command, argument)
            else:
                response = self._run_request(state, text)
        except ValueError as exc:
            response = str(exc)
        except BackendFailure as exc:
            response = f"Backend error: {exc}"
        except Exception as exc:
            log.exception("telegram_lab_message_failed")
            response = f"Unexpected error: {exc}"
        return chunk_text(response)

    def process_update(self, update: dict[str, Any]) -> tuple[str, list[str], int | None] | None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return None
        text = message.get("text")
        if not isinstance(text, str):
            return None
        chat_id = str((message.get("chat") or {}).get("id", "")).strip()
        user_id = str((message.get("from") or {}).get("id", "")).strip()
        if not chat_id:
            return None
        replies = self.handle_text(chat_id, user_id, text)
        return chat_id, replies, message.get("message_id")

    def run_forever(self) -> None:
        log.info(
            "telegram_lab_bot_started repo_root=%s api_base_url=%s default_mode=%s default_backend=%s default_agent=%s",
            self.config.repo_root,
            self.config.api_base_url,
            self.config.default_mode,
            self.config.default_backend,
            self.config.default_agent,
        )
        while True:
            try:
                updates = self.telegram_client.get_updates(
                    offset=self.state_store.offset,
                    timeout_s=self.config.polling_timeout_s,
                )
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    if update_id >= self.state_store.offset:
                        self.state_store.offset = update_id + 1
                        self.state_store.save()
                    processed = self.process_update(update)
                    if not processed:
                        continue
                    chat_id, replies, reply_to_message_id = processed
                    for reply in replies:
                        self.telegram_client.send_message(
                            chat_id,
                            reply,
                            reply_to_message_id=reply_to_message_id,
                        )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                log.exception("telegram_lab_polling_failed")
                time.sleep(min(self.config.polling_timeout_s, 5))
                if isinstance(exc, httpx.HTTPError):
                    continue
