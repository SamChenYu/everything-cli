#!/bin/bash
# Stop and remove the clipconfirm LaunchAgent.
set -euo pipefail

LABEL="com.samcyu.clipconfirm"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ -f "$PLIST_DST" ]; then
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    echo "==> Removed $PLIST_DST and stopped the agent."
else
    echo "==> Not installed ($PLIST_DST not found)."
fi
