# JarvisMax Notification System

## Overview

The JarvisMax Notification System provides push notifications for mission status changes. Users can subscribe to receive notifications via **Telegram** or **Email** when missions complete (DONE) or fail (FAILED).

## Features

- ✅ **Multi-channel support**: Telegram Bot API and SMTP Email
- 🔔 **Status filtering**: Subscribe to specific mission statuses (DONE, FAILED, CANCELLED)
- 🔒 **User-scoped**: Each user manages their own notification preferences
- 🚀 **Async delivery**: Non-blocking notification dispatch
- 🛡️ **Fail-safe**: Notification errors never block mission execution
- 💾 **Persistent subscriptions**: Stored in JSON file (upgradeable to database)

## Architecture

### Components

```
core/notifications/
├── __init__.py                 # Package exports
├── models.py                   # Data models (Subscription, Payload, Channel)
├── notification_service.py     # Core service (subscription management, dispatch)
├── telegram_client.py          # Telegram Bot API client
├── email_client.py             # SMTP email client
└── mission_events.py           # Mission lifecycle hooks

api/routes/notifications.py     # REST API endpoints
```

### Data Flow

```
Mission Status Change (DONE/FAILED)
    ↓
trigger_mission_notification_sync()
    ↓
NotificationService.send_notification()
    ↓
Filter subscriptions by status & channel
    ↓
Dispatch to channels (Telegram/Email)
    ↓
Channel clients send notifications
```

## API Endpoints

### POST `/api/v2/notifications/subscribe`

Subscribe to mission notifications.

**Request:**
```json
{
  "channel": "telegram",           // "telegram" or "email"
  "destination": "123456789",      // chat_id for Telegram, email for Email
  "mission_statuses": ["DONE", "FAILED"]  // optional, defaults to ["DONE", "FAILED"]
}
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "message": "Subscribed to telegram notifications",
    "channel": "telegram",
    "destination": "123456789",
    "mission_statuses": ["DONE", "FAILED"]
  }
}
```

### POST `/api/v2/notifications/unsubscribe`

Unsubscribe from notifications.

**Request:**
```json
{
  "channel": "telegram"  // "telegram" or "email"
}
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "message": "Unsubscribed from telegram notifications",
    "channel": "telegram"
  }
}
```

### GET `/api/v2/notifications/subscriptions`

List all active subscriptions for current user.

**Response:**
```json
{
  "ok": true,
  "data": {
    "subscriptions": [
      {
        "channel": "telegram",
        "destination": "123456789",
        "enabled": true,
        "mission_statuses": ["DONE", "FAILED"],
        "created_at": 1712702400.0
      }
    ]
  }
}
```

### POST `/api/v2/notifications/test`

Send a test notification.

**Request:**
```json
{
  "channel": "telegram",
  "destination": "123456789"
}
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "message": "Test notification sent successfully",
    "channel": "telegram",
    "destination": "123456789"
  }
}
```

## Setup

### Telegram Bot

1. **Create a bot with @BotFather**:
   - Message @BotFather on Telegram
   - Send `/newbot`
   - Follow instructions to create your bot
   - Copy the bot token

2. **Configure environment**:
   ```bash
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

3. **Get your chat ID**:
   - Start a chat with your bot
   - Send `/start`
   - Get your chat_id using one of these methods:
     - Visit `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
     - Look for `"chat":{"id":123456789}` in the response
     - Or use @userinfobot to get your chat_id

4. **Subscribe via API**:
   ```bash
   curl -X POST http://localhost:8000/api/v2/notifications/subscribe \
     -H "Content-Type: application/json" \
     -H "X-Jarvis-Token: your-token" \
     -d '{
       "channel": "telegram",
       "destination": "123456789"
     }'
   ```

5. **Test the setup**:
   ```bash
   curl -X POST http://localhost:8000/api/v2/notifications/test \
     -H "Content-Type: application/json" \
     -H "X-Jarvis-Token: your-token" \
     -d '{
       "channel": "telegram",
       "destination": "123456789"
     }'
   ```

### Email (SMTP)

1. **Configure SMTP settings** in `.env`:
   ```bash
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your_email@gmail.com
   SMTP_PASSWORD=your_app_password
   EMAIL_FROM=noreply@jarvismax.ai
   ```

   **For Gmail**:
   - Enable 2FA on your Google account
   - Generate an "App Password": https://myaccount.google.com/apppasswords
   - Use the app password as `SMTP_PASSWORD`

2. **Subscribe via API**:
   ```bash
   curl -X POST http://localhost:8000/api/v2/notifications/subscribe \
     -H "Content-Type: application/json" \
     -H "X-Jarvis-Token: your-token" \
     -d '{
       "channel": "email",
       "destination": "user@example.com"
     }'
   ```

3. **Test the setup**:
   ```bash
   curl -X POST http://localhost:8000/api/v2/notifications/test \
     -H "Content-Type: application/json" \
     -H "X-Jarvis-Token: your-token" \
     -d '{
       "channel": "email",
       "destination": "user@example.com"
     }'
   ```

## Notification Format

### Telegram Message

```
✅ Mission DONE

ID: mission_abc123
Goal: Analyze codebase and generate report

Result:
Analysis complete. Found 3 optimization opportunities...
```

### Email

**Subject**: `[JarvisMax] Mission DONE: Analyze codebase...`

**Body** (HTML + Text):
- Status badge with color coding
- Mission ID (monospace)
- Goal/title
- Result or error message
- Formatted with proper styling

## Usage in Code

### Trigger notification manually

```python
from core.notifications import send_notification

await send_notification(
    user_id="user123",
    mission_id="mission_abc",
    status="DONE",
    title="Analyze Python codebase",
    result="Analysis complete: 45 files scanned, 3 issues found.",
)
```

### Subscribe a user programmatically

```python
from core.notifications import get_notification_service, NotificationChannel

service = get_notification_service()
subscription = service.subscribe(
    user_id="user123",
    channel=NotificationChannel.TELEGRAM,
    destination="123456789",
    mission_statuses=["DONE", "FAILED"],
)
```

### Check user subscriptions

```python
from core.notifications import get_notification_service

service = get_notification_service()
subs = service.get_subscriptions("user123")
for sub in subs:
    print(f"{sub.channel}: {sub.destination} (enabled: {sub.enabled})")
```

## Integration with Missions

Notifications are automatically triggered when missions reach terminal statuses:

1. **Mission DONE**: Triggered after `ms.complete()` in `api/routes/missions.py`
2. **Mission FAILED**: Triggered in exception handler when mission execution fails

Both triggers are **fail-safe** – notification errors are logged but never block mission execution.

### Hook location

```python
# In api/routes/missions.py, after mission completion:
ms.complete(result.mission_id, result_text=_final)

# Notification hook (fail-open)
try:
    from core.notifications.mission_events import trigger_mission_notification_sync
    trigger_mission_notification_sync(
        mission_id=str(result.mission_id),
        user_id="default",
        status="DONE",
        goal=req.input,
        result=_final[:1000] if _final else "",
    )
except Exception as _notif_err:
    log.debug("mission_notification_skipped", error=str(_notif_err)[:100])
```

## Storage

Subscriptions are stored in `workspace/notifications_subscriptions.json`:

```json
{
  "default": [
    {
      "user_id": "default",
      "channel": "telegram",
      "destination": "123456789",
      "enabled": true,
      "mission_statuses": ["DONE", "FAILED"],
      "priority_filter": null,
      "created_at": 1712702400.0
    }
  ]
}
```

**Future enhancement**: Migrate to PostgreSQL table for production scalability.

## Error Handling

- **Telegram API errors**: Logged but not retried (avoid rate limits)
- **SMTP errors**: Logged with connection/auth details
- **Missing configuration**: Service logs warning and skips channel
- **Notification dispatch errors**: Never block mission execution (fail-open design)

## Security

- **Authentication**: All API endpoints require `X-Jarvis-Token` header
- **User isolation**: Users can only manage their own subscriptions
- **Token security**: Telegram bot token stored in environment variables
- **SMTP credentials**: Stored in environment, never exposed in logs

## Logging

Structured logs with `structlog`:

```python
# Subscription created
log.info("notification_subscription_created", user_id="user123", channel="telegram")

# Notification sent
log.info("notification_sent", channel="telegram", mission_id="abc123", user_id="user123")

# Notification failed
log.error("telegram_api_error", status=400, error="Invalid chat_id")
```

## Frontend Integration (Optional)

Add notification settings to user settings page:

```javascript
// Subscribe to Telegram notifications
const response = await fetch('/api/v2/notifications/subscribe', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Jarvis-Token': token,
  },
  body: JSON.stringify({
    channel: 'telegram',
    destination: chatId,
    mission_statuses: ['DONE', 'FAILED'],
  }),
});
```

## Testing

### Test notification delivery

```bash
# Test Telegram
curl -X POST http://localhost:8000/api/v2/notifications/test \
  -H "Content-Type: application/json" \
  -H "X-Jarvis-Token: test-token" \
  -d '{"channel":"telegram","destination":"123456789"}'

# Test Email
curl -X POST http://localhost:8000/api/v2/notifications/test \
  -H "Content-Type: application/json" \
  -H "X-Jarvis-Token: test-token" \
  -d '{"channel":"email","destination":"user@example.com"}'
```

### Check logs

```bash
# Watch logs for notification events
docker-compose logs -f jarvismax | grep notification
```

## Troubleshooting

### Telegram notifications not working

1. Check bot token is set: `echo $TELEGRAM_BOT_TOKEN`
2. Verify bot is started: Send `/start` to your bot
3. Check chat_id is correct: Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Test with `/api/v2/notifications/test` endpoint
5. Check logs: `docker-compose logs jarvismax | grep telegram`

### Email notifications not working

1. Verify SMTP settings: `echo $SMTP_HOST $SMTP_USER`
2. Test SMTP connection manually:
   ```python
   import smtplib
   with smtplib.SMTP('smtp.gmail.com', 587) as server:
       server.starttls()
       server.login(user, password)
   ```
3. For Gmail: Ensure app password is used (not account password)
4. Check firewall allows port 587 outbound
5. Check logs: `docker-compose logs jarvismax | grep email`

### No notifications received

1. Check subscription exists: `GET /api/v2/notifications/subscriptions`
2. Verify mission status is in `mission_statuses` filter
3. Check notification service is initialized: Look for `notification_subscriptions_loaded` in logs
4. Ensure mission reaches terminal status (DONE/FAILED)

## Performance

- **Async delivery**: Notifications sent via `asyncio.gather()` – non-blocking
- **Fail-fast**: Network errors don't retry (avoid delays)
- **Lightweight**: ~20ms overhead per notification dispatch
- **Scalable**: Multiple subscriptions dispatched concurrently

## Future Enhancements

- [ ] Database storage (PostgreSQL table)
- [ ] Webhook channel support
- [ ] SMS notifications (Twilio integration)
- [ ] Push notifications for mobile app
- [ ] Notification history/audit log
- [ ] Rate limiting per user
- [ ] Notification templates with placeholders
- [ ] Delivery status tracking
- [ ] Retry logic with exponential backoff
- [ ] User notification preferences UI

## License

Part of JarvisMax OS – Internal use only.
