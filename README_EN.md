# Orchestrate - Multi-framework AI Agent Orchestration Platform

[Français](README.md) | [Español](README_ES.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | [Deutsch](README_DE.md)

## 🎯 Overview

Orchestrate is a comprehensive AI agent orchestration platform that combines a powerful CLI for multi-framework management with a native mobile app for real-time tracking and 3D workflow visualization.

### 🚀 Key Features

- **Multi-framework Support**: LangChain, AutoGen, CrewAI, LlamaIndex, Haystack
- **5 Integrated CLI Agents**: Gemini AI CLI, Codex CLI, Claude Code, GitHub Copilot CLI, OpenCode CLI
- **Native Mobile App**: Flutter with real-time 3D visualization
- **WebSocket Integration**: Real-time communication with Kimi Agent SDK
- **3D Dashboard**: Interactive workflow visualization with Three.js
- **Real-time Monitoring**: Agent and workflow tracking
- **Modular Architecture**: Extensible and maintainable design

## 📁 Project Structure

```
Jarvismax-master/
├── orchestrate-cli/          # Orchestration CLI
│   ├── src/
│   │   ├── agents/          # 5 integrated CLI agents
│   │   ├── orchestrators/   # Orchestration frameworks
│   │   ├── tools/          # Tools registry
│   │   └── monitoring/     # Performance monitoring
│   ├── main.py             # CLI entry point
│   └── requirements.txt   # Dependencies
├── orchestrate-mobile/      # Flutter mobile app
│   ├── lib/
│   │   ├── screens/        # App screens
│   │   ├── widgets/       # UI components
│   │   ├── services/      # Services (WebSocket, API)
│   │   ├── models/        # Data models
│   │   └── utils/         # Utilities
│   ├── assets/             # Resources (3D, images, etc.)
│   ├── pubspec.yaml       # Flutter configuration
│   └── backend/           # Backend server
└── README.md              # Main documentation
```

## 🛠️ Installation

### Prerequisites

- Python 3.8+
- Flutter 3.13.0+
- Node.js 16+
- Git

### CLI Installation

```bash
cd orchestrate-cli
pip install -r requirements.txt
```

### Mobile App Installation

```bash
cd orchestrate-mobile
flutter pub get
```

## 🚀 Usage

### Start the CLI

```bash
cd orchestrate-cli
python main.py --help
```

### Start the Backend

```bash
cd orchestrate-mobile/backend
python websocket_server.py
```

### Start the Mobile App

```bash
cd orchestrate-mobile
flutter run
```

## 🔧 Configuration

### Agent Configuration

Edit `src/agents/agent_config.py` to configure each agent's settings:

```python
{
    "gemini_cli": {
        "api_key": "your_api_key",
        "model": "gemini-pro"
    },
    "claude_code": {
        "api_key": "your_api_key",
        "model": "claude-3-sonnet"
    }
}
```

### WebSocket Configuration

Modify `websocket_server.py` to adjust server parameters:

```python
HOST = "0.0.0.0"
PORT = 8002
```

## 📊 Advanced Features

### Multi-framework Orchestration

The CLI supports multiple orchestration frameworks:

- **LangChain**: Industry standard for AI applications
- **AutoGen**: Native multi-agents with collaboration
- **CrewAI**: Simple orchestration with clear logic
- **LlamaIndex**: Specialized in RAG and documents
- **Haystack**: Robust and research-oriented

### 3D Visualization

The mobile app provides interactive 3D workflow visualization:

- Graphical representation of agents
- Real-time state tracking
- Intuitive 3D navigation
- Scene export capabilities

### Real-time Monitoring

- Dashboard with real-time metrics
- Alerts and notifications
- Execution history
- Performance analysis

## 🔄 API Endpoints

### WebSocket

- `ws://localhost:8002/ws` - Main communication channel
- `ws://localhost:8002/ws/agents` - Agent information
- `ws://localhost:8002/ws/workflows` - Workflow states

### REST API

- `GET /api/agents` - List agents
- `POST /api/workflows` - Create workflow
- `GET /api/workflows/{id}` - Get workflow details
- `DELETE /api/workflows/{id}` - Delete workflow

## 🧪 Development

### Testing

```bash
# Unit tests
pytest tests/

# Integration tests
pytest tests/integration/
```

### Linting

```bash
# Python
flake8 src/
black src/

# Dart
dart analyze lib/
dart format lib/
```

## 📝 Documentation

- [Complete Documentation](docs/)
- [API Reference](docs/api.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Changelog](docs/CHANGELOG.md)

## 🤝 Contributing

1. Fork the project
2. Create a branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Flutter](https://flutter.dev/) - Mobile framework
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [LangChain](https://langchain.com/) - Orchestration framework
- [Three.js](https://threejs.org/) - 3D graphics library

---

**For more information, visit our [website](https://orchestrate-ai.com) or contact us at [info@orchestrate-ai.com](mailto:info@orchestrate-ai.com).**