# Orchestrate - マルチフレームワークAIエージェントオーケストレーションプラットフォーム

[Français](README.md) | [English](README_EN.md) | [Español](README_ES.md) | [中文](README_ZH.md) | [Deutsch](README_DE.md)

## 🎯 概要

Orchestrateは、強力なCLIによるマルチフレームワーク管理と、リアルタイム追跡および3Dワークフロー可視化を提供するネイティブモバイルアプリを組み合わせた、包括的なAIエージェントオーケストレーションプラットフォームです。

### 🚕 主要機能

- **マルチフレームワークサポート**: LangChain, AutoGen, CrewAI, LlamaIndex, Haystack
- **5つの統合CLIエージェント**: Gemini AI CLI, Codex CLI, Claude Code, GitHub Copilot CLI, OpenCode CLI
- **ネイティブモバイルアプリ**: リアルタイム3D可視化を備えたFlutter
- **WebSocket統合**: Kimi Agent SDKとのリアルタイム通信
- **3Dダッシュボード**: Three.jsを使用したインタラクティブなワークフロー可視化
- **リアルタイム監視**: エージェントとワークフローの追跡
- **モジュラーなアーキテクチャ**: 拡張可能で保守性の高い設計

## 📁 プロジェクト構造

```
Jarvismax-master/
├── orchestrate-cli/          # オーケストレーションCLI
│   ├── src/
│   │   ├── agents/          # 5つの統合CLIエージェント
│   │   ├── orchestrators/   # オーケストレーションフレームワーク
│   │   ├── tools/          # ツールレジストリ
│   │   └── monitoring/     # パフォーマンス監視
│   ├── main.py             # エントリーポイント
│   └── requirements.txt   # 依存関係
├── orchestrate-mobile/      # Flutterモバイルアプリ
│   ├── lib/
│   │   ├── screens/        # 画面
│   │   ├── widgets/       # UIコンポーネント
│   │   ├── services/      # サービス（WebSocket, API）
│   │   ├── models/        # データモデル
│   │   └── utils/         # ユーティリティ
│   ├── assets/             # リソース（3D, 画像など）
│   ├── pubspec.yaml       # Flutter設定
│   └── backend/           # バックエンドサーバー
└── README.md              # メインドキュメント
```

## 🛠️ インストール

### 前提条件

- Python 3.8+
- Flutter 3.13.0+
- Node.js 16+
- Git

### CLIインストール

```bash
cd orchestrate-cli
pip install -r requirements.txt
```

### モバイルアプリインストール

```bash
cd orchestrate-mobile
flutter pub get
```

## 🚀 使用方法

### CLIを起動

```bash
cd orchestrate-cli
python main.py --help
```

### バックエンドを起動

```bash
cd orchestrate-mobile/backend
python websocket_server.py
```

### モバイルアプリを起動

```bash
cd orchestrate-mobile
flutter run
```

## 🔧 設定

### エージェント設定

`src/agents/agent_config.py`を編集して各エージェントの設定を構成：

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

### WebSocket設定

サーバーパラメータを調整するために`websocket_server.py`を修正：

```python
HOST = "0.0.0.0"
PORT = 8002
```

## 📊 高度な機能

### マルチフレームワークオーケストレーション

CLIは複数のオーケストレーションフレームワークをサポート：

- **LangChain**: AIアプリケーションの業界標準
- **AutoGen**: ネイティブなマルチエージェントによる協調
- **CrewAI**: 明確なロジックを持つシンプルなオーケストレーション
- **LlamaIndex**: RAGとドキュメントに特化
- **Haystack**: 堅牢で検索指向のフレームワーク

### 3D可視化

モバイルアプリはインタラクティブな3Dワークフロー可視化を提供：

- エージェントのグラフィカルな表現
- リアルタイム状態追跡
- 直感的な3Dナビゲーション
- シーンエクスポート機能

### リアルタイム監視

- リアルタイムメトリックダッシュボード
- アラートと通知
- 実行履歴
- パフォーマンス分析

## 🔄 APIエンドポイント

### WebSocket

- `ws://localhost:8002/ws` - メイン通信チャネル
- `ws://localhost:8002/ws/agents` - エージェント情報
- `ws://localhost:8002/ws/workflows` - ワークフロー状態

### REST API

- `GET /api/agents` - エージェントリスト
- `POST /api/workflows` - ワークフロー作成
- `GET /api/workflows/{id}` - ワークフロー詳細取得
- `DELETE /api/workflows/{id}` - ワークフロー削除

## 🧪 開発

### テスト

```bash
# ユニットテスト
pytest tests/

# 統合テスト
pytest tests/integration/
```

### リンティング

```bash
# Python
flake8 src/
black src/

# Dart
dart analyze lib/
dart format lib/
```

## 📝 ドキュメント

- [完全なドキュメント](docs/)
- [APIリファレンス](docs/api.md)
- [貢献ガイド](docs/CONTRIBUTING.md)
- [変更履歴](docs/CHANGELOG.md)

## 🤝 貢献

1. プロジェクトをフォーク
2. ブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add amazing feature'`)
4. ブランチをプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを開く

## 📄 ライセンス

このプロジェクトはMITライセンスの下で提供されています - 詳細は[LICENSE](LICENSE)ファイルを参照してください。

## 🙏 謝辞

- [Flutter](https://flutter.dev/) - モバイルフレームワーク
- [FastAPI](https://fastapi.tiangolo.com/) - Webフレームワーク
- [LangChain](https://langchain.com/) - オーケストレーションフレームワーク
- [Three.js](https://threejs.org/) - 3Dグラフィックスライブラリ

---

**詳細情報については、[ウェブサイト](https://orchestrate-ai.com)にアクセスするか、[info@orchestrate-ai.com](mailto:info@orchestrate-ai.com)までお問い合わせください。**