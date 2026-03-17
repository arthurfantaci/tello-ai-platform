#!/usr/bin/env bash
# PreToolUse hook: Block implementation code edits on the main branch.
#
# Enforces the workflow: Issue → Worktree/Branch → then implement.
# Applies to Edit and Write tool calls targeting service/package source code.
#
# Exit codes:
#   0 = allow (not on main, or not an implementation file)
#   2 = block (on main AND editing implementation code)

TOOL_INPUT="$1"

# Extract file_path from JSON input
FILE_PATH=$(echo "$TOOL_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('file_path',''))" 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Only guard implementation code — services, packages, and scripts
# Allow edits to .claude/*, docs/*, testing/*, CLAUDE.md, memory files, etc.
if ! echo "$FILE_PATH" | grep -qE "(services|packages|scripts)/.+\.(py|toml)$"; then
    exit 0
fi

# Check current branch
BRANCH=$(git branch --show-current 2>/dev/null)
if [ -z "$BRANCH" ]; then
    exit 0
fi

if [ "$BRANCH" = "main" ]; then
    echo "BLOCKED: Cannot edit implementation code on the main branch."
    echo ""
    echo "You must follow the implementation workflow:"
    echo "  1. Brainstorm  — invoke superpowers:brainstorming"
    echo "  2. Write Spec  — invoke superpowers:writing-plans"
    echo "  3. Create Issue — gh issue create"
    echo "  4. Create Worktree — use EnterWorktree tool"
    echo "  5. Then implement on the worktree branch"
    echo ""
    echo "Current branch: $BRANCH"
    echo "Target file: $FILE_PATH"
    exit 2
fi

# On a non-main branch — allow
exit 0
