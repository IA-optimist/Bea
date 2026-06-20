# Bea SDK

Python SDK for Bea AI Agent System - a clean, type-safe client for interacting with Bea's API and MCP server.

## Installation

```bash
pip install bea-sdk
```

## Quick Start

```python
from bea_sdk import BeaClient

# Initialize client
client = BeaClient(
    base_url="http://localhost:8000",
    api_token="your-api-token",  # Optional
)

# Health check
health = client.health_check()
print(f"Bea status: {health}")

# Submit a mission
mission = client.mission.submit(
    goal="Create a simple Python web server",
    mission_type="coding"
)
print(f"Mission ID: {mission['mission_id']}")

# Check mission status
status = client.mission.get_status(mission['mission_id'])
print(f"Status: {status['status']}")

# Search memory
results = client.memory.search("web server frameworks", top_k=5)
for result in results:
    print(f"- {result['text'][:100]}... (score: {result['score']:.2f})")

# Close client
client.close()
```

## Features

- **Mission Management**: Submit, monitor, and manage Bea missions
- **Memory Operations**: Search, store, and retrieve from Bea's vector memory
- **Type Safety**: Full type hints for better IDE support
- **Error Handling**: Structured exceptions for common error cases
- **Context Manager**: Support for `with` statement for automatic cleanup

## API Reference

### BeaClient

Main client for interacting with Bea AI Agent System.

```python
client = BeaClient(
    base_url="http://localhost:8000",
    api_token="optional-token",
    timeout=30
)
```

#### Methods

- `health_check()` - Check API server health
- `close()` - Close HTTP client

### MissionClient

Client for mission-related operations.

```python
mission_client = client.mission
```

#### Methods

- `submit(goal, mission_type="auto", context=None)` - Submit a new mission
- `get_status(mission_id)` - Get mission status
- `list_missions(limit=10, status=None)` - List recent missions
- `cancel(mission_id)` - Cancel a running mission
- `get_result(mission_id)` - Get mission result

### MemoryClient

Client for memory-related operations.

```python
memory_client = client.memory
```

#### Methods

- `search(query, top_k=5, filters=None)` - Search vector memory
- `store(text, metadata=None, memory_type="episodic")` - Store memory entry
- `get(memory_id)` - Retrieve specific memory entry
- `delete(memory_id)` - Delete memory entry
- `list_recent(limit=10, memory_type=None)` - List recent memory entries

## Error Handling

```python
from bea_sdk import BeaClient
from bea_sdk.exceptions import MissionError, MemoryError, ConnectionError

try:
    client = BeaClient(base_url="http://localhost:8000")
    mission = client.mission.submit("Build a REST API")
except ConnectionError as e:
    print(f"Connection failed: {e}")
except MissionError as e:
    print(f"Mission error: {e}")
finally:
    client.close()
```

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black bea_sdk/

# Lint code
ruff check bea_sdk/
```

## License

MIT License - see LICENSE file for details.
