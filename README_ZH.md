# Orchestrate - 多框架AI代理编排平台

[Français](README.md) | [English](README_EN.md) | [Español](README_ES.md) | [日本語](README_JA.md) | [Deutsch](README_DE.md)

## 🎯 概述

Orchestrate 是一个综合的AI代理编排平台，结合了强大的CLI进行多框架管理和原生移动应用，实现实时跟踪和3D工作流可视化。

### 🚀 主要功能

- **多框架支持**: LangChain, AutoGen, CrewAI, LlamaIndex, Haystack
- **5个集成CLI代理**: Gemini AI CLI, Codex CLI, Claude Code, GitHub Copilot CLI, OpenCode CLI
- **原生移动应用**: Flutter 与实时3D可视化
- **WebSocket集成**: 与Kimi Agent SDK的实时通信
- **3D仪表板**: 使用Three.js的交互式工作流可视化
- **实时监控**: 代理和工作流跟踪
- **模块化架构**: 可扩展和可维护的设计

## 📁 项目结构

```
Jarvismax-master/
├── orchestrate-cli/          # 编排CLI
│   ├── src/
│   │   ├── agents/          # 5个集成CLI代理
│   │   ├── orchestrators/   # 编排框架
│   │   ├── tools/          # 工具注册表
│   │   └── monitoring/     # 性能监控
│   ├── main.py             # CLI入口点
│   └── requirements.txt   # 依赖项
├── orchestrate-mobile/      # Flutter移动应用
│   ├── lib/
│   │   ├── screens/        # 应用屏幕
│   │   ├── widgets/       # UI组件
│   │   ├── services/      # 服务（WebSocket, API）
│   │   ├── models/        # 数据模型
│   │   └── utils/         # 工具
│   ├── assets/             # 资源（3D, 图像等）
│   ├── pubspec.yaml       # Flutter配置
│   └── backend/           # 后端服务器
└── README.md              # 主要文档
```

## 🛠️ 安装

### 前提条件

- Python 3.8+
- Flutter 3.13.0+
- Node.js 16+
- Git

### CLI安装

```bash
cd orchestrate-cli
pip install -r requirements.txt
```

### 移动应用安装

```bash
cd orchestrate-mobile
flutter pub get
```

## 🚀 使用

### 启动CLI

```bash
cd orchestrate-cli
python main.py --help
```

### 启动后端

```bash
cd orchestrate-mobile/backend
python websocket_server.py
```

### 启动移动应用

```bash
cd orchestrate-mobile
flutter run
```

## 🔧 配置

### 代理配置

编辑 `src/agents/agent_config.py` 配置每个代理的设置：

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

### WebSocket配置

修改 `websocket_server.py` 调整服务器参数：

```python
HOST = "0.0.0.0"
PORT = 8002
```

## 📊 高级功能

### 多框架编排

CLI支持多种编排框架：

- **LangChain**: AI应用行业标准
- **AutoGen**: 原生多代理协作
- **CrewAI**: 简单编排，逻辑清晰
- **LlamaIndex**: 专精于RAG和文档
- **Haystack**: 健壮的面向搜索框架

### 3D可视化

移动应用提供交互式3D工作流可视化：

- 代理的图形表示
- 实时状态跟踪
- 直观的3D导航
- 场景导出功能

### 实时监控

- 实时指标仪表板
- 警报和通知
- 执行历史
- 性能分析

## 🔄 API端点

### WebSocket

- `ws://localhost:8002/ws` - 主要通信通道
- `ws://localhost:8002/ws/agents` - 代理信息
- `ws://localhost:8002/ws/workflows` - 工作流状态

### REST API

- `GET /api/agents` - 列出代理
- `POST /api/workflows` - 创建工作流
- `GET /api/workflows/{id}` - 获取工作流详情
- `DELETE /api/workflows/{id}` - 删除工作流

## 🧪 开发

### 测试

```bash
# 单元测试
pytest tests/

# 集成测试
pytest tests/integration/
```

### 代码检查

```bash
# Python
flake8 src/
black src/

# Dart
dart analyze lib/
dart format lib/
```

## 📝 文档

- [完整文档](docs/)
- [API参考](docs/api.md)
- [贡献指南](docs/CONTRIBUTING.md)
- [变更日志](docs/CHANGELOG.md)

## 🤝 贡献

1. Fork项目
2. 创建分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 打开Pull Request

## 📄 许可证

此项目采用MIT许可证 - 详情请查看 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- [Flutter](https://flutter.dev/) - 移动框架
- [FastAPI](https://fastapi.tiangolo.com/) - Web框架
- [LangChain](https://langchain.com/) - 编排框架
- [Three.js](https://threejs.org/) - 3D图形库

---

**更多信息，请访问我们的[网站](https://orchestrate-ai.com)或联系 [info@orchestrate-ai.com](mailto:info@orchestrate-ai.com)。**