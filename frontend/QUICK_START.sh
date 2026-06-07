#!/bin/bash

# BeaMax AI OS Frontend - Quick Start Script

echo "=========================================="
echo "   BeaMax AI OS Frontend Setup"
echo "=========================================="
echo ""

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ first."
    exit 1
fi

# Check Node.js version
NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js version 18+ required. You have: $(node -v)"
    exit 1
fi

echo "✅ Node.js $(node -v) detected"
echo ""

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env
    echo "✅ .env file created"
else
    echo "ℹ️  .env file already exists"
fi
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
npm install
if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies"
    exit 1
fi
echo "✅ Dependencies installed"
echo ""

# Display summary
echo "=========================================="
echo "   Installation Complete! 🎉"
echo "=========================================="
echo ""
echo "Available commands:"
echo "  npm run dev     - Start development server (http://localhost:3000)"
echo "  npm run build   - Build for production"
echo "  npm run preview - Preview production build"
echo "  npm run lint    - Run ESLint"
echo ""
echo "Next steps:"
echo "  1. Ensure backend API is running at http://localhost:8000"
echo "  2. Run: npm run dev"
echo "  3. Open: http://localhost:3000"
echo ""
echo "Documentation:"
echo "  - README.md         - General documentation"
echo "  - DEPLOYMENT.md     - Deployment guide"
echo "  - PROJECT_SUMMARY.md - Complete feature list"
echo ""
echo "Happy coding! 🚀"
