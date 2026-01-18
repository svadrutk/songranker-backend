---
description: git commit and push
model: opencode/glm-4.6
subtask: true
---

commit and push

The commit message must follow the Conventional Commits specification:

<type>[optional scope]: <description>

[optional body]

[optional footer(s)]

Types:
- feat: A new feature
- fix: A bug fix
- docs: Documentation only changes
- style: Changes that do not affect the meaning of the code (formatting, etc.)
- refactor: A code change that neither fixes a bug nor adds a feature
- perf: A code change that improves performance
- test: Adding missing tests or correcting existing tests
- build: Changes that affect the build system or external dependencies
- ci: Changes to CI configuration files and scripts
- chore: Other changes that don't modify src or test files
- revert: Reverts a previous commit

Use "!" after the type/scope for breaking changes (e.g., feat!: ...) and include "BREAKING CHANGE:" in the footer.

Special mapping rules:
- For anything in `packages/web`, use the `docs` type.
- For anything in `packages/app`, use the `chore` type.

Content guidelines:
- Prefer explaining WHY something was done from an end-user perspective in the body.
- Be specific about user-facing changes; avoid generic messages like "improved experience".

if there are changes do a git pull --rebase
if there are conflicts DO NOT FIX THEM. notify me and I will fix them
