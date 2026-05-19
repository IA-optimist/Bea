# Orchestrate - Plateforme d'Orchestration d'Agents IA Multi-framework

[English](README_EN.md)

## 🎯 Présentation

Orchestrate est une plateforme complète d'orchestration d'agents IA qui combine un CLI puissant pour la gestion multi-framework et une application mobile native pour le suivi en temps réel et la visualisation 3D des workflows.

### 🚀 Caractéristiques Principales

- **Multi-framework Support**: LangChain, AutoGen, CrewAI, LlamaIndex, Haystack
- **5 Agents CLI Intégrés**: Gemini AI CLI, Codex CLI, Claude Code, GitHub Copilot CLI, OpenCode CLI
- **Application Mobile Native**: Flutter avec visualisation 3D en temps réel
- **WebSocket Integration**: Communication temps réel avec Kimi Agent SDK
- **Dashboard 3D**: Visualisation interactive des workflows avec Three.js
- **Monitoring en Temps Réel**: Suivi des agents et des workflows
- **Architecture Modulaire**: Conception extensible et maintenable

## 📁 Structure du Projet

```
Jarvismax-master/
├── orchestrate-cli/          # CLI d'orchestration
│   ├── src/
│   │   ├── agents/          # 5 agents CLI intégrés
│   │   ├── orchestrators/   # Frameworks d'orchestration
│   │   ├── tools/          # Registre d'outils
│   │   └── monitoring/     # Surveillance performance
│   ├── main.py             # Point d'entrée CLI
│   └── requirements.txt   # Dépendances
├── orchestrate-mobile/      # Application mobile Flutter
│   ├── lib/
│   │   ├── screens/        # Écrans de l'application
│   │   ├── widgets/       # Composants UI
│   │   ├── services/      # Services (WebSocket, API)
│   │   ├── models/        # Modèles de données
│   │   └── utils/         # Utilitaires
│   ├── assets/             # Ressources (3D, images, etc.)
│   ├── pubspec.yaml       # Configuration Flutter
│   └── backend/           # Serveur backend
└── README.md              # Documentation principale
```

## 🛠️ Installation

### Prérequis

- Python 3.8+
- Flutter 3.13.0+
- Node.js 16+
- Git

### Installation du CLI

```bash
cd orchestrate-cli
pip install -r requirements.txt
```

### Installation de l'Application Mobile

```bash
cd orchestrate-mobile
flutter pub get
```

## 🚀 Utilisation

### Démarrer le CLI

```bash
cd orchestrate-cli
python main.py --help
```

### Démarrer le Backend

```bash
cd orchestrate-mobile/backend
python websocket_server.py
```

### Démarrer l'Application Mobile

```bash
cd orchestrate-mobile
flutter run
```

## 🔧 Configuration

### Configuration des Agents

Éditez `src/agents/agent_config.py` pour configurer les paramètres de chaque agent :

```python
{
    "gemini_cli": {
        "api_key": "votre_cle_api",
        "model": "gemini-pro"
    },
    "claude_code": {
        "api_key": "votre_cle_api",
        "model": "claude-3-sonnet"
    }
}
```

### Configuration WebSocket

Modifiez `websocket_server.py` pour ajuster les paramètres du serveur :

```python
HOST = "0.0.0.0"
PORT = 8002
```

## 📊 Fonctionnalités Avancées

### Multi-framework Orchestration

Le CLI supporte plusieurs frameworks d'orchestration :

- **LangChain**: Standard de l'industrie pour les applications IA
- **AutoGen**: Multi-agents natif avec collaboration
- **CrewAI**: Orchestration simple et logique claire
- **LlamaIndex**: Spécialisé dans le RAG et les documents
- **Haystack**: Robuste et orienté recherche

### Visualisation 3D

L'application mobile offre une visualisation 3D interactive des workflows :

- Représentation graphique des agents
- Suivi en temps réel des états
- Navigation 3D intuitive
- Exportation de scènes

### Monitoring en Temps Réel

- Tableau de bord avec métriques en temps réel
- Alertes et notifications
- Historique des exécutions
- Analyse de performance

## 🔄 API Endpoints

### WebSocket

- `ws://localhost:8002/ws` - Canal principal de communication
- `ws://localhost:8002/ws/agents` - Informations sur les agents
- `ws://localhost:8002/ws/workflows` - État des workflows

### REST API

- `GET /api/agents` - Liste des agents
- `POST /api/workflows` - Créer un workflow
- `GET /api/workflows/{id}` - Détails d'un workflow
- `DELETE /api/workflows/{id}` - Supprimer un workflow

## 🧪 Développement

### Tests

```bash
# Tests unitaires
pytest tests/

# Tests d'intégration
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

- [Documentation Complète](docs/)
- [API Reference](docs/api.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Changelog](docs/CHANGELOG.md)

## 🤝 Contribuer

1. Fork le projet
2. Créez une branche (`git checkout -b feature/amazing-feature`)
3. Commitez vos changements (`git commit -m 'Add amazing feature'`)
4. Poussez la branche (`git push origin feature/amazing-feature`)
5. Ouvrez un Pull Request

## 📄 Licence

Ce projet est sous licence MIT - voir le fichier [LICENSE](LICENSE) pour plus de détails.

## 🙏 Remerciements

- [Flutter](https://flutter.dev/) - Framework mobile
- [FastAPI](https://fastapi.tiangolo.com/) - Framework web
- [LangChain](https://langchain.com/) - Framework d'orchestration
- [Three.js](https://threejs.org/) - 3D graphics library

---

**Pour plus d'informations, visitez notre [site web](https://orchestrate-ai.com) ou contactez-nous à [info@orchestrate-ai.com](mailto:info@orchestrate-ai.com).**