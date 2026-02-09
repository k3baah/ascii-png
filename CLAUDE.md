# Claude Code Instructions

## Project Overview

Sticker Factory — autonomous pipeline for an Etsy print-on-demand sticker store (Printify fulfillment).

**Pipeline:** Ideation → ASCII art generation → PNG rendering → Publish to Printify

**Tech:** Python, Pillow, SQLite, YAML config, CLI (click). See `SPEC.md` for full architecture.

**Package:** `sticker_factory/` — single modular package with: config.py, db.py, models.py, renderer.py, publisher.py, cli.py, ideation.py, ascii_gen.py

**Key constraints:**
- v0 = ASCII-to-PNG only, no LLM steps yet
- Print quality: 200-400px font, 2000-4000px output, white background default
- Every new ASCII design must have a matching concept file in `concepts/` (`designs/foo.txt` -> `concepts/foo.json`)
- Color variations: concept `variations` preferred; config color schemes are fallback
- Printify API key not yet set up — defer live API tests
- Read `SPEC.md` before implementing anything

## Session Protocol

1. Read `claude-progress.txt` and `PRD.json` first. Understand what's been done and what's next.
2. Pick the highest-priority feature where `passes` is `false` (lowest `priority` number).
3. Fix any bugs in existing features before implementing new ones.
4. Implement ONE feature per session, fully tested.
5. Test your code before marking anything as passing.
6. Only set `passes: true` after verifying the feature works end-to-end.
7. Commit after each completed feature with a descriptive message.
8. Update `claude-progress.txt` at end of session with what was done, current state, and any issues.

## PRD.json Rules

- NEVER remove or edit feature descriptions or steps -- only modify the `passes` field.
- Update progress notes if needed, but do not alter the spec.

## Code Standards

- Refer to `SPEC.md` for architectural decisions and design rationale.
- Leave code in a clean, mergeable state at end of session.
- Keep commits atomic: one feature = one commit.
