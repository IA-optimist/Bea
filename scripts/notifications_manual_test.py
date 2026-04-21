#!/usr/bin/env python3
"""
Test script for notification system
Tests subscription, notification dispatch, and channel clients
"""
import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.notifications import (
    get_notification_service,
    send_notification,
    NotificationChannel,
)
from core.notifications.models import NotificationPayload
from core.notifications.telegram_client import TelegramNotificationClient
from core.notifications.email_client import EmailNotificationClient


async def test_subscription():
    """Test subscription management"""
    print("\n=== Testing Subscription Management ===")
    
    service = get_notification_service()
    
    # Subscribe to Telegram
    sub1 = service.subscribe(
        user_id="test_user",
        channel=NotificationChannel.TELEGRAM,
        destination="123456789",
        mission_statuses=["DONE", "FAILED"],
    )
    print(f"✓ Subscribed to Telegram: {sub1.destination}")
    
    # Subscribe to Email
    sub2 = service.subscribe(
        user_id="test_user",
        channel=NotificationChannel.EMAIL,
        destination="test@example.com",
        mission_statuses=["DONE"],
    )
    print(f"✓ Subscribed to Email: {sub2.destination}")
    
    # List subscriptions
    subs = service.get_subscriptions("test_user")
    print(f"✓ Total subscriptions: {len(subs)}")
    for sub in subs:
        print(f"  - {sub.channel.value}: {sub.destination} ({sub.mission_statuses})")
    
    # Unsubscribe
    success = service.unsubscribe("test_user", NotificationChannel.TELEGRAM)
    print(f"✓ Unsubscribed from Telegram: {success}")
    
    subs = service.get_subscriptions("test_user")
    print(f"✓ Remaining subscriptions: {len(subs)}")
    
    return True


async def test_telegram_client():
    """Test Telegram client"""
    print("\n=== Testing Telegram Client ===")
    
    client = TelegramNotificationClient()
    
    if not client.enabled:
        print("⚠ Telegram client not configured (missing TELEGRAM_BOT_TOKEN)")
        return False
    
    print("✓ Telegram client initialized")
    print(f"  Bot token: {client.bot_token[:20]}...")
    
    # Create test payload
    payload = NotificationPayload(
        mission_id="test_mission_123",
        user_id="test_user",
        status="DONE",
        title="Test Mission: Analyze Python codebase",
        result="Analysis complete. Found 15 files, 500 lines of code, 0 issues.",
    )
    
    print("\nTest payload created:")
    print(f"  Mission ID: {payload.mission_id}")
    print(f"  Status: {payload.status}")
    print(f"  Title: {payload.title}")
    
    # Format message
    message = client._format_message(payload)
    print(f"\nFormatted message ({len(message)} chars):")
    print("---")
    print(message)
    print("---")
    
    return True


async def test_email_client():
    """Test Email client"""
    print("\n=== Testing Email Client ===")
    
    client = EmailNotificationClient()
    
    if not client.enabled:
        print("⚠ Email client not configured (missing SMTP credentials)")
        return False
    
    print("✓ Email client initialized")
    print(f"  SMTP Host: {client.smtp_host}")
    print(f"  SMTP Port: {client.smtp_port}")
    print(f"  From: {client.email_from}")
    
    # Create test payload
    payload = NotificationPayload(
        mission_id="test_mission_456",
        user_id="test_user",
        status="FAILED",
        title="Test Mission: Deploy application",
        error="Connection timeout: Unable to reach deployment server.",
    )
    
    print("\nTest payload created:")
    print(f"  Mission ID: {payload.mission_id}")
    print(f"  Status: {payload.status}")
    print(f"  Error: {payload.error}")
    
    # Format messages
    text_body = client._format_text(payload)
    html_body = client._format_html(payload)
    
    print(f"\nFormatted text body ({len(text_body)} chars):")
    print("---")
    print(text_body[:500])
    print("---")
    
    print(f"\nFormatted HTML body ({len(html_body)} chars)")
    
    return True


async def test_notification_dispatch():
    """Test notification dispatch"""
    print("\n=== Testing Notification Dispatch ===")
    
    service = get_notification_service()
    
    # Subscribe test user
    service.subscribe(
        user_id="test_dispatch",
        channel=NotificationChannel.TELEGRAM,
        destination="987654321",
        mission_statuses=["DONE", "FAILED"],
    )
    
    # Send notification
    payload = NotificationPayload(
        mission_id="dispatch_test_001",
        user_id="test_dispatch",
        status="DONE",
        title="Notification Dispatch Test",
        result="This is a test notification to verify dispatch logic.",
    )
    
    print("Dispatching notification to subscribed channels...")
    await service.send_notification(payload)
    print("✓ Notification dispatched (check logs for delivery status)")
    
    # Clean up
    service.unsubscribe("test_dispatch", NotificationChannel.TELEGRAM)
    
    return True


async def test_convenience_function():
    """Test convenience send_notification function"""
    print("\n=== Testing Convenience Function ===")
    
    # Subscribe test user
    service = get_notification_service()
    service.subscribe(
        user_id="test_convenience",
        channel=NotificationChannel.TELEGRAM,
        destination="111222333",
        mission_statuses=["DONE"],
    )
    
    # Send using convenience function
    print("Sending notification via send_notification()...")
    await send_notification(
        user_id="test_convenience",
        mission_id="conv_test_001",
        status="DONE",
        title="Convenience Function Test",
        result="Testing the convenience wrapper function.",
    )
    print("✓ Notification sent via convenience function")
    
    # Clean up
    service.unsubscribe("test_convenience", NotificationChannel.TELEGRAM)
    
    return True


async def main():
    """Run all tests"""
    print("╔═══════════════════════════════════════════════════╗")
    print("║   JarvisMax Notification System - Test Suite     ║")
    print("╚═══════════════════════════════════════════════════╝")
    
    tests = [
        ("Subscription Management", test_subscription),
        ("Telegram Client", test_telegram_client),
        ("Email Client", test_email_client),
        ("Notification Dispatch", test_notification_dispatch),
        ("Convenience Function", test_convenience_function),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test '{name}' failed with error: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status:10} {name}")
    
    passed = sum(1 for _, s in results if s)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
