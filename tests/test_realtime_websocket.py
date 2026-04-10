"""
Test script for real-time WebSocket metrics endpoint.
Usage: python tests/test_realtime_websocket.py
"""
import asyncio
import json
import websockets
from datetime import datetime


async def test_websocket_connection():
    """Test WebSocket connection and receive metrics."""
    uri = "ws://localhost:8000/ws/metrics?interval=2"
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Connected!")
            print("\nReceiving real-time metrics (Ctrl+C to stop):\n")
            
            message_count = 0
            while True:
                try:
                    message = await websocket.recv()
                    data = json.loads(message)
                    message_count += 1
                    
                    # Pretty print received data
                    timestamp = data.get('timestamp', 'N/A')
                    system = data.get('system', {})
                    missions = data.get('missions', {})
                    revenue = data.get('revenue', {})
                    
                    print(f"[Message #{message_count}] {timestamp}")
                    print(f"  System: CPU={system.get('cpu')}% | Memory={system.get('memory')}% | "
                          f"Used={system.get('memory_used_gb'):.2f}GB/{system.get('memory_total_gb'):.2f}GB")
                    print(f"  Missions: Total={missions.get('total')} | "
                          f"Approved={missions.get('approved')} | "
                          f"Done={missions.get('done')} | "
                          f"Pending={missions.get('pending')}")
                    print(f"  Revenue: MRR=${revenue.get('mrr'):.2f} | "
                          f"ARR=${revenue.get('arr'):.2f} | "
                          f"Daily=${revenue.get('daily_revenue'):.2f}")
                    print("-" * 80)
                    
                except websockets.exceptions.ConnectionClosed:
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ❌ Connection closed by server")
                    break
                    
    except ConnectionRefusedError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Connection refused. Is the server running?")
        print("Start the server with: uvicorn api.main:app --host 0.0.0.0 --port 8000")
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Test interrupted by user")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error: {e}")


async def test_http_endpoints():
    """Test HTTP endpoints for WebSocket status and snapshot."""
    import aiohttp
    
    base_url = "http://localhost:8000"
    
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Testing HTTP endpoints...")
    
    async with aiohttp.ClientSession() as session:
        # Test status endpoint
        try:
            async with session.get(f"{base_url}/metrics/websocket/status") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"\n✅ WebSocket Status:")
                    print(f"  Active connections: {data.get('active_connections')}")
                    print(f"  Endpoint: {data.get('endpoint')}")
                    print(f"  Status: {data.get('status')}")
                else:
                    print(f"❌ Status endpoint returned {resp.status}")
        except Exception as e:
            print(f"❌ Status endpoint error: {e}")
        
        # Test snapshot endpoint
        try:
            async with session.get(f"{base_url}/metrics/snapshot") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"\n✅ Metrics Snapshot:")
                    print(f"  Timestamp: {data.get('timestamp')}")
                    print(f"  System CPU: {data.get('system', {}).get('cpu')}%")
                    print(f"  System Memory: {data.get('system', {}).get('memory')}%")
                    print(f"  Missions Total: {data.get('missions', {}).get('total')}")
                    print(f"  Revenue MRR: ${data.get('revenue', {}).get('mrr'):.2f}")
                else:
                    print(f"❌ Snapshot endpoint returned {resp.status}")
        except Exception as e:
            print(f"❌ Snapshot endpoint error: {e}")


async def main():
    """Run all tests."""
    print("=" * 80)
    print("JarvisMax Real-Time WebSocket Test")
    print("=" * 80)
    
    # Test HTTP endpoints first
    await test_http_endpoints()
    
    print("\n" + "=" * 80)
    print("Testing WebSocket Connection")
    print("=" * 80)
    
    # Test WebSocket connection
    await test_websocket_connection()
    
    print("\n" + "=" * 80)
    print("Test completed")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
