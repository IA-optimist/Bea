# Notifications System - Quick Start

## Installation

No extra dependencies required. Uses standard library `smtplib` and `aiohttp` (already in requirements).

## Configuration

Add to `.env`:

```bash
# Telegram (prioritaire)
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Email (optionnel)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=noreply@beamax.ai
```

## Quick Test

```bash
# 1. Subscribe
curl -X POST http://localhost:8000/api/v2/notifications/subscribe \
  -H "Content-Type: application/json" \
  -H "X-Bea-Token: test-token" \
  -d '{
    "channel": "telegram",
    "destination": "YOUR_CHAT_ID"
  }'

# 2. Send test notification
curl -X POST http://localhost:8000/api/v2/notifications/test \
  -H "Content-Type: application/json" \
  -H "X-Bea-Token: test-token" \
  -d '{
    "channel": "telegram",
    "destination": "YOUR_CHAT_ID"
  }'
```

## Get Telegram Chat ID

1. Message your bot: `/start`
2. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. Look for: `"chat":{"id":123456789}`

## Usage

Notifications are **automatically** sent when missions complete or fail.

To trigger manually:

```python
from core.notifications import send_notification

await send_notification(
    user_id="default",
    mission_id="abc123",
    status="DONE",
    title="Your mission goal",
    result="Mission completed successfully!",
)
```

## API Endpoints

- `POST /api/v2/notifications/subscribe` - Subscribe to notifications
- `POST /api/v2/notifications/unsubscribe` - Unsubscribe
- `GET /api/v2/notifications/subscriptions` - List subscriptions
- `POST /api/v2/notifications/test` - Send test notification

See `docs/NOTIFICATIONS_SYSTEM.md` for full documentation.
