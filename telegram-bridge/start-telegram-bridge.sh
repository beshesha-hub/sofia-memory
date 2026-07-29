#!/bin/bash
# Start the Telegram-Claude Bridge
# Usage: ./start-telegram-bridge.sh
#
# Make sure to set your Anthropic API key first:
#   export ANTHROPIC_API_KEY="your-key-here"
#
# Or create a .env file in this directory with:
#   ANTHROPIC_API_KEY=your-key-here

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env file if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
  echo "Loaded .env file"
fi

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "Error: ANTHROPIC_API_KEY is not set."
  echo ""
  echo "Option 1: Export it in your terminal:"
  echo "  export ANTHROPIC_API_KEY=\"your-key-here\""
  echo ""
  echo "Option 2: Create a .env file in this directory:"
  echo "  echo 'ANTHROPIC_API_KEY=your-key-here' > $SCRIPT_DIR/.env"
  echo ""
  exit 1
fi

# Install dependencies if needed
if [ ! -d "$SCRIPT_DIR/node_modules" ]; then
  echo "Installing dependencies..."
  cd "$SCRIPT_DIR"
  npm init -y > /dev/null 2>&1
  npm install node-telegram-bot-api @anthropic-ai/sdk > /dev/null 2>&1
  echo "Dependencies installed."
fi

echo "Starting Telegram-Claude Bridge..."
echo "Press Ctrl+C to stop."
echo ""

node "$SCRIPT_DIR/telegram-bridge.js"
