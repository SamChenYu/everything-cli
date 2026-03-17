#!/bin/bash
set -e

echo "Setting up everything-cli..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is required but not installed."
    exit 1
fi

# Install dependencies
echo "Installing dependencies..."
pip3 install -r requirements.txt

# Verify detect-secrets is installed
echo "Verifying detect-secrets installation..."
if ! command -v detect-secrets &> /dev/null; then
    echo "ERROR: detect-secrets installation failed."
    exit 1
fi
echo "detect-secrets $(detect-secrets --version) installed successfully"

# Install pre-commit hooks
echo "Installing pre-commit hooks for secret scanning..."
if ! command -v pre-commit &> /dev/null; then
    echo "ERROR: pre-commit is not installed. Installing from requirements.txt should have fixed this."
    exit 1
fi

pre-commit install

# Verify installation
echo ""
echo "Setup complete!"
echo ""
echo "Verifying pre-commit hooks are active..."
if [ -f .git/hooks/pre-commit ]; then
    echo "SUCCESS: Pre-commit hooks installed successfully"
    echo ""
    echo "Secret scanning protection is now active!"
else
    echo "ERROR: Pre-commit hooks not found. Something went wrong."
    exit 1
fi

echo ""
echo "Next steps:"
echo "   1. Copy .env.sample files in subdirectories"
echo "   2. Rename to .env and add your credentials"
echo "   3. The .env files are automatically ignored by git"
