#!/usr/bin/env bash
# scripts/deliver_apk.sh — Send release APK to Telegram.
# Reads TELEGRAM_BOT_TOKEN and TELEGRAM_TARGET_CHAT_ID from environment.
# Never prints secret values. Fails safely if config is missing.

set -euo pipefail

APK_PATH="${1:-beamax_app/build/app/outputs/flutter-apk/app-release.apk}"
VERSION="${2:-1.0.0}"
DRY_RUN="${DRY_RUN:-false}"

# ── Validate secrets exist (without printing them) ─────────────────────────

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ "${TELEGRAM_BOT_TOKEN}" = "SET_ME" ]; then
    echo "⚠️  DRY-RUN: TELEGRAM_BOT_TOKEN not set or is placeholder."
    echo "   Set it in .env: TELEGRAM_BOT_TOKEN=<your-bot-token>"
    echo "   Then re-run this script."
    DRY_RUN="true"
fi

if [ -z "${TELEGRAM_TARGET_CHAT_ID:-}" ] || [ "${TELEGRAM_TARGET_CHAT_ID}" = "SET_ME" ]; then
    echo "⚠️  DRY-RUN: TELEGRAM_TARGET_CHAT_ID not set or is placeholder."
    echo "   Set it in .env: TELEGRAM_TARGET_CHAT_ID=<your-chat-id>"
    DRY_RUN="true"
fi

# ── Validate APK exists ───────────────────────────────────────────────────

if [ ! -f "$APK_PATH" ]; then
    echo "❌ APK not found at: $APK_PATH"
    echo "   Build it first: cd beamax_app && flutter build apk --release"
    exit 1
fi

APK_SIZE=$(stat -c%s "$APK_PATH" 2>/dev/null || stat -f%z "$APK_PATH" 2>/dev/null)
APK_SIZE_MB=$(echo "scale=1; $APK_SIZE / 1048576" | bc)
APK_NAME=$(basename "$APK_PATH")

echo "📦 APK: $APK_NAME ($APK_SIZE_MB MB)"
echo "🔖 Version: $VERSION"

# ── Dry run ───────────────────────────────────────────────────────────────

if [ "$DRY_RUN" = "true" ]; then
    echo ""
    echo "🏃 DRY-RUN MODE — would send:"
    echo "   File: $APK_PATH"
    echo "   Size: $APK_SIZE_MB MB"
    echo "   Caption: BeaMax v$VERSION release build"
    echo ""
    echo "To send for real, set TELEGRAM_BOT_TOKEN and TELEGRAM_TARGET_CHAT_ID"
    echo "in your .env file, then run:"
    echo "   source .env && bash scripts/deliver_apk.sh"
    exit 0
fi

# ── Send via Telegram Bot API ─────────────────────────────────────────────

CAPTION="📱 *BeaMax v${VERSION}*
Release build — $(date -u '+%Y-%m-%d %H:%M UTC')
Size: ${APK_SIZE_MB} MB
API: https://bea.beamaxapp.co.uk"

echo "📤 Sending to Telegram..."
HTTP_CODE=$(curl -s -o /tmp/tg_response.json -w "%{http_code}" \
    -F "chat_id=${TELEGRAM_TARGET_CHAT_ID}" \
    -F "document=@${APK_PATH}" \
    -F "caption=${CAPTION}" \
    -F "parse_mode=Markdown" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ APK delivered successfully!"
    # Extract message_id from response (without showing sensitive data)
    MSG_ID=$(python3 -c "import json; print(json.load(open('/tmp/tg_response.json')).get('result',{}).get('message_id','?'))" 2>/dev/null || echo "?")
    echo "   Message ID: $MSG_ID"
else
    echo "❌ Telegram API returned HTTP $HTTP_CODE"
    # Show error without leaking token
    python3 -c "import json; r=json.load(open('/tmp/tg_response.json')); print(f'   Error: {r.get(\"description\",\"unknown\")}')" 2>/dev/null || echo "   (could not parse response)"
    exit 1
fi

rm -f /tmp/tg_response.json
