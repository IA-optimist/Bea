#!/bin/bash

# JarvisMax Mobile Setup Script

echo "🚀 Setting up JarvisMax Mobile..."

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js first."
    exit 1
fi

echo "✅ Node.js version: $(node --version)"

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install npm first."
    exit 1
fi

echo "✅ npm version: $(npm --version)"

# Install dependencies
echo "📦 Installing dependencies..."
npm install

# Check if Expo CLI is installed globally
if ! command -v expo &> /dev/null; then
    echo "⚠️  Expo CLI not found globally. Installing..."
    npm install -g expo-cli
fi

echo "✅ Expo CLI version: $(expo --version)"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env
    echo "✅ .env file created"
else
    echo "✅ .env file already exists"
fi

# Clear cache
echo "🧹 Clearing cache..."
rm -rf node_modules/.cache
expo start -c --clear

echo "✨ Setup complete!"
echo ""
echo "To start the app, run:"
echo "  npm start          # Start Expo dev server"
echo "  npm run ios        # Run on iOS"
echo "  npm run android    # Run on Android"
echo "  npm run web        # Run on web"
