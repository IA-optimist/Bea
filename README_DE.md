# Orchestrate - Multi-Framework KI-Agent-Orchestrierungsplattform

[Français](README.md) | [English](README_EN.md) | [Español](README_ES.md) | [中文](README_ZH.md) | [日本語](README_JA.md)

## 🎯 Übersicht

Orchestrate ist eine umfassende KI-Agent-Orchestrierungsplattform, die eine leistungsstarke CLI für Multi-Framework-Management mit einer nativen Mobile-App für Echtzeit-Tracking und 3D-Workflow-Visualisierung kombiniert.

### 🚀 Hauptfunktionen

- **Multi-Framework-Unterstützung**: LangChain, AutoGen, CrewAI, LlamaIndex, Haystack
- **5 integrierte CLI-Agents**: Gemini AI CLI, Codex CLI, Claude Code, GitHub Copilot CLI, OpenCode CLI
- **Native Mobile App**: Flutter mit Echtzeit-3D-Visualisierung
- **WebSocket-Integration**: Echtzeit-Kommunikation mit Kimi Agent SDK
- **3D-Dashboard**: Interaktive Workflow-Visualisierung mit Three.js
- **Echtzeit-Überwachung**: Agent- und Workflow-Tracking
- **Modulare Architektur**: Erweiterbares und wartbares Design

## 📁 Projektstruktur

```
Jarvismax-master/
├── orchestrate-cli/          # Orchestrierungs-CLI
│   ├── src/
│   │   ├── agents/          # 5 integrierte CLI-Agents
│   │   ├── orchestrators/   # Orchestrierungs-Frameworks
│   │   ├── tools/          # Tool-Register
│   │   └── monitoring/     # Performance-Überwachung
│   ├── main.py             # CLI-Einstiegspunkt
│   └── requirements.txt   # Abhängigkeiten
├── orchestrate-mobile/      # Flutter-Mobile-App
│   ├── lib/
│   │   ├── screens/        # App-Bildschirme
│   │   ├── widgets/       # UI-Komponenten
│   │   ├── services/      # Dienste (WebSocket, API)
│   │   ├── models/        # Datenmodelle
│   │   └── utils/         # Hilfsfunktionen
│   ├── assets/             # Ressourcen (3D, Bilder etc.)
│   ├── pubspec.yaml       # Flutter-Konfiguration
│   └── backend/           # Backend-Server
└── README.md              # Hauptdokumentation
```

## 🛠️ Installation

### Voraussetzungen

- Python 3.8+
- Flutter 3.13.0+
- Node.js 16+
- Git

### CLI-Installation

```bash
cd orchestrate-cli
pip install -r requirements.txt
```

### Mobile-App-Installation

```bash
cd orchestrate-mobile
flutter pub get
```

## 🚀 Nutzung

### CLI starten

```bash
cd orchestrate-cli
python main.py --help
```

### Backend starten

```bash
cd orchestrate-mobile/backend
python websocket_server.py
```

### Mobile-App starten

```bash
cd orchestrate-mobile
flutter run
```

## 🔧 Konfiguration

### Agent-Konfiguration

Bearbeiten Sie `src/agents/agent_config.py`, um die Einstellungen jedes Agents zu konfigurieren:

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

### WebSocket-Konfiguration

Passen Sie `websocket_server.py` an, um Server-Parameter zu ändern:

```python
HOST = "0.0.0.0"
PORT = 8002
```

## 📊 Fortgeschrittene Funktionen

### Multi-Framework-Orchestrierung

Die CLI unterstützt mehrere Orchestrierungs-Frameworks:

- **LangChain**: Branchenstandard für KI-Anwendungen
- **AutoGen**: Native Multi-Agent-Zusammenarbeit
- **CrewAI**: Einfache Orchestrierung mit klarer Logik
- **LlamaIndex**: Spezialisiert auf RAG und Dokumente
- **Haystack**: Robust und suchorientiert

### 3D-Visualisierung

Die Mobile-App bietet interaktive 3D-Workflow-Visualisierung:

- Grafische Darstellung von Agents
- Echtzeit-Status-Tracking
- Intuitive 3D-Navigation
- Szenen-Export-Funktionen

### Echtzeit-Überwachung

- Dashboard mit Echtzeit-Metriken
- Alarme und Benachrichtigungen
- Ausführungsverlauf
- Performance-Analyse

## 🔄 API-Endpunkte

### WebSocket

- `ws://localhost:8002/ws` - Hauptkommunikationskanal
- `ws://localhost:8002/ws/agents` - Agent-Informationen
- `ws://localhost:8002/ws/workflows` - Workflow-Status

### REST API

- `GET /api/agents` - Agents auflisten
- `POST /api/workflows` - Workflow erstellen
- `GET /api/workflows/{id}` - Workflow-Details abrufen
- `DELETE /api/workflows/{id}` - Workflow löschen

## 🧪 Entwicklung

### Tests

```bash
# Unit-Tests
pytest tests/

# Integrationstests
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

## 📝 Dokumentation

- [Vollständige Dokumentation](docs/)
- [API-Referenz](docs/api.md)
- [Beitragen](docs/CONTRIBUTING.md)
- [Changelog](docs/CHANGELOG.md)

## 🤝 Beiträge

1. Fork das Projekt
2. Erstellen Sie einen Branch (`git checkout -b feature/amazing-feature`)
3. Committen Sie Ihre Änderungen (`git commit -m 'Add amazing feature'`)
4. Pushen Sie den Branch (`git push origin feature/amazing-feature`)
5. Öffnen Sie einen Pull Request

## 📄 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe die [LICENSE](LICENSE)-Datei für Details.

## 🙏 Danksagungen

- [Flutter](https://flutter.dev/) - Mobile Framework
- [FastAPI](https://fastapi.tiangolo.com/) - Web Framework
- [LangChain](https://langchain.com/) - Orchestrierungs-Framework
- [Three.js](https://threejs.org/) - 3D-Grafik-Bibliothek

---

**Weitere Informationen finden Sie auf unserer [Website](https://orchestrate-ai.com) oder kontaktieren Sie uns unter [info@orchestrate-ai.com](mailto:info@orchestrate-ai.com).**