#!/usr/bin/env bash
# Block direct commits to main/master branch.
# Enforces Issue → Worktree → PR workflow.

branch=$(git branch --show-current)

if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
    echo "ERROR: Direct commits to '$branch' are not allowed."
    echo ""
    echo "Follow the established workflow:"
    echo "  1. Create a GitHub Issue:  gh issue create"
    echo "  2. Enter a Worktree:       (use EnterWorktree in Claude Code)"
    echo "  3. Commit on the branch"
    echo "  4. Push and open a PR:     gh pr create"
    exit 1
fi
