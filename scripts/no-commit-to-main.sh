#!/usr/bin/env bash
# Block direct commits to the main branch.
# Installed as a pre-commit hook.
branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" = "main" ]; then
    echo "ERROR: Direct commits to main are not allowed."
    echo "Create a feature branch first: git checkout -b feat/your-feature"
    exit 1
fi
