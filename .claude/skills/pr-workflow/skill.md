---
name: pr-workflow
description: "PR creation and merge workflow"
---

# PR Workflow

## Creating a PR
1. Ensure all tests pass: `uv run pytest packages/ services/ -v`
2. Ensure lint passes: `uv run ruff check . && uv run ruff format --check .`
3. Push branch and create PR with `gh pr create`
4. PR title: conventional commit style
5. PR body: Summary, Test Plan, breaking changes

## Merging
1. Squash merge to main
2. Delete the feature branch after merge
3. Update MEMORY.md with new state
