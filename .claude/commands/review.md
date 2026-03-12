---
description: "Code review delegation"
---

# Code Review

Review the current changes for:

1. **Spec compliance** — Does the code match the plan/spec?
2. **Test coverage** — Are edge cases covered?
3. **Error handling** — Structured errors, no raw exceptions?
4. **Conventions** — Follows CLAUDE.md patterns?
5. **Security** — No secrets in code, no injection vectors?

Run: `git diff --stat` to see changed files, then review each.
