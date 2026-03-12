#!/usr/bin/env bash
# Validate that Bash commands operate within the workspace boundary.
# This is a PreToolUse hook for Claude Code.

TOOL_INPUT="$1"

# Extract command from JSON input
COMMAND=$(echo "$TOOL_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('command',''))" 2>/dev/null)

if [ -z "$COMMAND" ]; then
    exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
    exit 0
fi

# Warn if command references paths outside the workspace
if echo "$COMMAND" | grep -qE "cd\s+/(?!Users.*tello-ai-platform)" 2>/dev/null; then
    echo "⚠️  Warning: Command appears to change directory outside the workspace."
    echo "   Workspace root: $REPO_ROOT"
fi

exit 0
