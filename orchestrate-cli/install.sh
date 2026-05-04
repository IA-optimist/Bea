#!/bin/bash

# Orchestrate CLI Installation Script
# Installs all necessary CLI agents and dependencies

set -e

echo "🚀 Starting Orchestrate CLI installation..."

# Check Python version
python_version=$(python3 --version 2>&1 | grep -o '[0-9]\+\.[0-9]\+' | head -1)
required_version="3.8"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python 3.8+ is required. Found: $python_version"
    exit 1
fi

echo "✅ Python version check passed: $python_version"

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Install CLI agents
echo "🤖 Installing CLI agents..."

# Install Gemini CLI
echo "   Installing Gemini CLI..."
pip install google-generativeai

# Install OpenAI Codex CLI
echo "   Installing OpenAI Codex CLI..."
pip install openai

# Install Claude Code CLI
echo "   Installing Claude Code CLI..."
npm install -g @codiumai/claude-code

# Install GitHub Copilot CLI
echo "   Installing GitHub Copilot CLI..."
npm install -g @codiumai/github-copilot-cli

# Install Aider CLI
echo "   Installing Aider CLI..."
pip install aider-chat

# Install OpenCode CLI
echo "   Installing OpenCode CLI..."
pip install opencode-ai

# Install Cursor CLI
echo "   Installing Cursor CLI..."
npm install -g @codiumai/cursor-cli

# Install OpenHands CLI
echo "   Installing OpenHands CLI..."
pip install openhands

# Install other dependencies
echo "   Installing additional dependencies..."

# Install browser automation tools
pip install selenium playwright
playwright install

# Install data science tools
pip install pandas numpy scikit-learn matplotlib seaborn

# Install development tools
pip install black flake8 mypy

# Install testing tools
pip install pytest pytest-asyncio pytest-cov

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data/documents
mkdir -p logs
mkdir -p tools
mkdir -p templates
mkdir -p tests
mkdir -p outputs

# Set up environment file
echo "🔧 Setting up environment file..."
if [ ! -f ".env" ]; then
    cat > .env << EOF
# Orchestrate CLI Environment Configuration

# LLM Provider APIs
OPENROUTER_API_KEY=your_openrouter_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
GOOGLE_GEMINI_API_KEY=your_google_gemini_api_key_here

# Tool APIs
GITHUB_TOKEN=your_github_token_here
CURSOR_API_KEY=your_cursor_api_key_here
OPENCODE_API_KEY=your_opencode_api_key_here

# Vector Database (Optional)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=your_qdrant_api_key_here
EOF
    echo "⚠️  Please edit .env file with your API keys"
fi

# Set up configuration file
echo "⚙️  Setting up configuration..."
if [ ! -f "config/orchestrate.yaml" ]; then
    mkdir -p config
    cp config/orchestrate.yaml.example config/orchestrate.yaml 2>/dev/null || true
fi

# Run initial test
echo "🧪 Running initial test..."
python test_all_cli.py || true

echo "✅ Installation completed successfully!"
echo ""
echo "🎯 Next steps:"
echo "1. Edit .env file with your API keys"
echo "2. Run 'python main.py' to start the CLI"
echo "3. Run 'python test_all_cli.py' to run comprehensive tests"
echo ""
echo "📚 Documentation: README.md"
echo "🔧 Configuration: config/orchestrate.yaml"
echo "🧪 Testing: test_all_cli.py"