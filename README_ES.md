# Orchestrate - Plataforma de Orquestación de Agentes IA Multi-framework

[Français](README.md) | [English](README_EN.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | [Deutsch](README_DE.md)

## 🎯 Resumen

Orchestrate es una plataforma completa de orquestación de agentes IA que combina un CLI potente para la gestión multi-framework con una aplicación móvil nativa para seguimiento en tiempo real y visualización 3D de flujos de trabajo.

### 🚀 Características Principales

- **Soporte Multi-framework**: LangChain, AutoGen, CrewAI, LlamaIndex, Haystack
- **5 Agentes CLI Integrados**: Gemini AI CLI, Codex CLI, Claude Code, GitHub Copilot CLI, OpenCode CLI
- **Aplicación Móvil Nativa**: Flutter con visualización 3D en tiempo real
- **Integración WebSocket**: Comunicación en tiempo real con Kimi Agent SDK
- **Dashboard 3D**: Visualización interactiva de flujos de trabajo con Three.js
- **Monitoreo en Tiempo Real**: Seguimiento de agentes y flujos de trabajo
- **Arquitectura Modular**: Diseño extensible y mantenible

## 📁 Estructura del Proyecto

```
Jarvismax-master/
├── orchestrate-cli/          # CLI de orquestación
│   ├── src/
│   │   ├── agents/          # 5 agentes CLI integrados
│   │   ├── orchestrators/   # Frameworks de orquestación
│   │   ├── tools/          # Registro de herramientas
│   │   └── monitoring/     # Monitoreo de rendimiento
│   ├── main.py             # Punto de entrada CLI
│   └── requirements.txt   # Dependencias
├── orchestrate-mobile/      # Aplicación móvil Flutter
│   ├── lib/
│   │   ├── screens/        # Pantallas de la aplicación
│   │   ├── widgets/       # Componentes UI
│   │   ├── services/      # Servicios (WebSocket, API)
│   │   ├── models/        # Modelos de datos
│   │   └── utils/         # Utilidades
│   ├── assets/             # Recursos (3D, imágenes, etc.)
│   ├── pubspec.yaml       # Configuración Flutter
│   └── backend/           # Servidor backend
└── README.md              # Documentación principal
```

## 🛠️ Instalación

### Requisitos

- Python 3.8+
- Flutter 3.13.0+
- Node.js 16+
- Git

### Instalación del CLI

```bash
cd orchestrate-cli
pip install -r requirements.txt
```

### Instalación de la Aplicación Móvil

```bash
cd orchestrate-mobile
flutter pub get
```

## 🚀 Uso

### Iniciar el CLI

```bash
cd orchestrate-cli
python main.py --help
```

### Iniciar el Backend

```bash
cd orchestrate-mobile/backend
python websocket_server.py
```

### Iniciar la Aplicación Móvil

```bash
cd orchestrate-mobile
flutter run
```

## 🔧 Configuración

### Configuración de Agentes

Edita `src/agents/agent_config.py` para configurar la configuración de cada agente:

```python
{
    "gemini_cli": {
        "api_key": "tu_clave_api",
        "model": "gemini-pro"
    },
    "claude_code": {
        "api_key": "tu_clave_api",
        "model": "claude-3-sonnet"
    }
}
```

### Configuración WebSocket

Modifica `websocket_server.py` para ajustar los parámetros del servidor:

```python
HOST = "0.0.0.0"
PORT = 8002
```

## 📊 Características Avanzadas

### Orquestación Multi-framework

El CLI soporta múltiples frameworks de orquestación:

- **LangChain**: Estándar de la industria para aplicaciones IA
- **AutoGen**: Multi-agentes nativo con colaboración
- **CrewAI**: Orquestación simple con lógica clara
- **LlamaIndex**: Especializado en RAG y documentos
- **Haystack**: Robusto y orientado a búsqueda

### Visualización 3D

La aplicación móvil ofrece visualización 3D interactiva de flujos de trabajo:

- Representación gráfica de agentes
- Seguimiento en tiempo real de estados
- Navegación 3D intuitiva
- Capacidad de exportación de escenas

### Monitoreo en Tiempo Real

- Tablero con métricas en tiempo real
- Alertas y notificaciones
- Historial de ejecuciones
- Análisis de rendimiento

## 🔄 Endpoints de API

### WebSocket

- `ws://localhost:8002/ws` - Canal principal de comunicación
- `ws://localhost:8002/ws/agents` - Información de agentes
- `ws://localhost:8002/ws/workflows` - Estados de flujos de trabajo

### REST API

- `GET /api/agents` - Lista de agentes
- `POST /api/workflows` - Crear flujo de trabajo
- `GET /api/workflows/{id}` - Detalles del flujo de trabajo
- `DELETE /api/workflows/{id}` - Eliminar flujo de trabajo

## 🧪 Desarrollo

### Pruebas

```bash
# Pruebas unitarias
pytest tests/

# Pruebas de integración
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

## 📝 Documentación

- [Documentación Completa](docs/)
- [Referencia de API](docs/api.md)
- [Contribución](docs/CONTRIBUTING.md)
- [Changelog](docs/CHANGELOG.md)

## 🤝 Contribuir

1. Haz fork del proyecto
2. Crea una rama (`git checkout -b feature/amazing-feature`)
3. Commitea tus cambios (`git commit -m 'Add amazing feature'`)
4. Empuja la rama (`git push origin feature/amazing-feature`)
5. Abre un Pull Request

## 📄 Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para más detalles.

## 🙏 Agradecimientos

- [Flutter](https://flutter.dev/) - Framework móvil
- [FastAPI](https://fastapi.tiangolo.com/) - Framework web
- [LangChain](https://langchain.com/) - Framework de orquestación
- [Three.js](https://threejs.org/) - Biblioteca de gráficos 3D

---

**Para más información, visita nuestro [sitio web](https://orchestrate-ai.com) o contáctanos en [info@orchestrate-ai.com](mailto:info@orchestrate-ai.com).**