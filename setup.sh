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
echo "Setting up Python projects..."

# Python folders setup
PYTHON_FOLDERS=("autogitignore" "gemini" "tcp-messenger")
for folder in "${PYTHON_FOLDERS[@]}"; do
    if [ -d "$folder" ]; then
        echo "Setting up $folder..."
        cd "$folder"

        if [ ! -d "venv" ]; then
            echo "  Creating virtual environment..."
            python3 -m venv venv
            echo "  Installing requirements..."
            source venv/bin/activate
            if [ -f "requirements.txt" ]; then
                pip install -r requirements.txt
            fi
            deactivate
        else
            echo "  Virtual environment already exists"
        fi

        cd ..
    fi
done

echo ""
echo "Setting up npm projects..."

# npm folders setup
NPM_FOLDERS=("spotify" "tele" "whatsapp")
for folder in "${NPM_FOLDERS[@]}"; do
    if [ -d "$folder" ]; then
        echo "Setting up $folder..."
        cd "$folder"

        if [ ! -d "node_modules" ]; then
            echo "  Running npm install..."
            npm install
        else
            echo "  node_modules already exists"
        fi

        if [ -f ".env.sample" ] && [ ! -f ".env" ]; then
            echo "  Copying .env.sample to .env..."
            cp .env.sample .env
        fi

        cd ..
    fi
done

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "   1. Update .env files in subdirectories with your credentials"
echo "   2. The .env files are automatically ignored by git"
