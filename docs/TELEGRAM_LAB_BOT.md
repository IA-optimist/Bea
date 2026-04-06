# Telegram Lab Bot

This repository now includes a standalone Telegram bot bridge for the JarvisMax AI lab.

Files:

- `integrations/telegram_lab_bot.py`
- `scripts/start_telegram_lab_bot.py`
- `scripts/start_telegram_lab_bot.ps1`

## What It Does

- polls Telegram with your bot token
- keeps one local state per chat
- routes plain text to the selected lab specialist
- supports `openclaw` specialist execution when available
- falls back to the local JarvisMax API when `TELEGRAM_LAB_BACKEND=auto`

## Recommended First Start

Use `auto` first. That gives you the best chance of getting a working bot immediately:

- if OpenClaw lab agents are available, requests go there
- if OpenClaw is not ready, the bot falls back to the local JarvisMax API

## .env Setup

Start from `.env.example` and set at minimum:

```env
TELEGRAM_BOT_TOKEN=123456:your_bot_token
TELEGRAM_LAB_BACKEND=auto
TELEGRAM_LAB_MODE=lab
TELEGRAM_LAB_AGENT=lab-director
JARVIS_API_BASE_URL=http://127.0.0.1:8000
```

Optional but recommended after the first successful test:

```env
TELEGRAM_ALLOWED_CHAT_IDS=123456789
TELEGRAM_ALLOWED_USER_IDS=123456789
```

Notes:

- `TELEGRAM_CHAT_ID` is still supported for the existing notification-only flows.
- `TELEGRAM_TARGET_CHAT_ID` is accepted as a legacy alias by the new bot bridge.
- For the first bootstrap, you can leave `TELEGRAM_ALLOWED_*` empty, test the bot, then lock it down.

## Start JarvisMax API

The `jarvis` backend and `auto` fallback need the local API running.

```powershell
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:v1.9.7
py -3 main.py
```

Verify:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/v3/system/readiness
```

## Start The Telegram Bot

In a second terminal:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_telegram_lab_bot.ps1
```

Direct Python launch also works:

```powershell
py -3 scripts\start_telegram_lab_bot.py
```

## OpenClaw Specialist Path

If you want specialist execution through the OpenClaw AI lab instead of the Jarvis API fallback:

```powershell
openclaw gateway run
```

If the gateway reports a broken local setup:

```powershell
openclaw doctor --repair
```

If OpenClaw still says pairing or onboarding is missing:

```powershell
openclaw onboard
```

Then set:

```env
TELEGRAM_LAB_BACKEND=openclaw
```

## Telegram Commands

- `/start`
- `/help`
- `/status`
- `/mode lab`
- `/mode mission`
- `/backend auto`
- `/backend openclaw`
- `/backend jarvis`
- `/agent director`
- `/agent architect`
- `/agent ml`
- `/agent dev`
- `/agent research`
- `/agent review`
- `/agent qa`
- `/agent ops`
- `/agent security`
- `/agent data`
- `/mission <text>`
- `/ask <text>`

One-off specialist calls:

- `/director <text>`
- `/architect <text>`
- `/ml <text>`
- `/dev <text>`
- `/research <text>`
- `/review <text>`
- `/qa <text>`
- `/ops <text>`
- `/security <text>`
- `/data <text>`

## Example Session

```text
/start
/status
/agent architect
Map the canonical orchestration path for JarvisMax
/agent director
Split this feature into architecture, implementation, QA, and security streams
```

## Runtime Notes

- The bot is a separate worker. It does not modify FastAPI startup.
- The bot stores its offset and per-chat state in `workspace/telegram_lab_bot_state.json` by default.
- Plain text in `lab` mode goes to the selected specialist.
- In `mission` mode, plain text goes directly to JarvisMax as a mission request.
- When `backend=auto`, the bot tries OpenClaw first, then falls back to JarvisMax API.
