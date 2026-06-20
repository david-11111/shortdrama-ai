# Project Agent Instructions

This file is the persistent instruction entry point for Codex agents working in
this repository. Read it before starting any task in this project.

## Always Read First

1. Read this `AGENTS.md`.
2. Read `CLAUDE.md` when present; it contains the detailed project development rules.
3. Follow `karpathy-guidelines` for coding, debugging, refactoring, and review work.

## Working Rules

- Inspect the existing code and project structure before making changes.
- Prefer the smallest correct change that matches existing project patterns.
- Do not add unrequested features, abstractions, rewrites, or unrelated cleanup.
- Do not touch unrelated files.
- Protect user work: never revert changes you did not make unless explicitly asked.
- Before claiming completion, run relevant verification and report the exact command and result.

## Required Pre-Edit Confirmation

Before editing, creating, deleting, moving, or formatting any file, print this
confirmation first:

```text
规则确认：我已读取 AGENTS.md / CLAUDE.md；本次将修改 <文件/范围>；理由是 <原因>；不会触碰无关文件。
```

If this confirmation is missing, do not edit files. If you notice you edited
without printing it first, stop immediately, report the mistake, and re-align
with this file before continuing.

## If Instructions Conflict

User instructions in the current conversation take priority. Otherwise, follow
this file, then `CLAUDE.md`, then local code conventions.
