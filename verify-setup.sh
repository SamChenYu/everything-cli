#!/bin/bash

echo "Checking if secret scanning is active..."

# Check if pre-commit hooks are installed
if [ ! -f .git/hooks/pre-commit ]; then
    echo "ERROR: Pre-commit hooks NOT installed!"
    echo "   Run: ./setup.sh"
    exit 1
fi

# Check if detect-secrets is available
if ! command -v detect-secrets &> /dev/null; then
    echo "ERROR: detect-secrets NOT installed!"
    echo "   Run: ./setup.sh"
    exit 1
fi

# Check if hook references our config
if ! grep -q "pre-commit-config.yaml" .git/hooks/pre-commit; then
    echo "ERROR: Pre-commit hooks not properly configured!"
    echo "   Run: ./setup.sh"
    exit 1
fi

echo "SUCCESS: Secret scanning is properly configured!"
echo "SUCCESS: Pre-commit hooks are active"
echo "SUCCESS: detect-secrets is installed"
echo ""
echo "You're protected from committing secrets!"
