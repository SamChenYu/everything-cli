#!/bin/bash
# Build clipconfirm and install it as a launchd LaunchAgent that auto-starts at login.
set -euo pipefail

DIR="$HOME/clip-confirm"
BIN="$DIR/bin/clipconfirm"
LOG="$DIR/clipconfirm.log"
LABEL="com.samcyu.clipconfirm"
PLIST_SRC="$DIR/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> Building binary"
mkdir -p "$DIR/bin"
swiftc -O "$DIR/clipconfirm.swift" -o "$BIN"

echo "==> Writing LaunchAgent to $PLIST_DST"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__BIN__|$BIN|g" -e "s|__LOG__|$LOG|g" "$PLIST_SRC" > "$PLIST_DST"

echo "==> Loading agent"
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "==> Done. Status:"
launchctl list | grep clipconfirm || echo "(not listed yet — give it a second)"

echo
echo "Now copy something (cmd+C). If macOS asks, allow notifications for the"
echo "prompting process in System Settings > Notifications. A 'Copied ✓' banner"
echo "should appear on every successful copy. Silence = the copy was dropped."
