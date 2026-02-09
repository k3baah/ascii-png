# DB-First Publish Flow Runbook

This project now uses a DB-first workflow:

- One DB row per rendered PNG variation
- Copy is stored in DB (not sidecar files)
- Publish reads from DB rows

## Prereqs

1. Run from repo root:
```bash
cd /Users/kofi/projects/ascii-png
```

2. Ensure config/secrets are available:
- `config.yaml` has `printify` config
- `.env` has `PRINTIFY_API_KEY`
- `.env` has `ANTHROPIC_API_KEY` (for `copywrite`)

3. Optional: use a custom DB path:
```bash
export STICKER_FACTORY_DB_PATH=/path/to/sticker_factory.db
```

If not set, DB defaults to `sticker_factory.db` in repo root.

## One-Time Migration Behavior

The first command that touches DB (`render`, `copywrite`, `publish`, `list`, `show`, `sync`) will auto-migrate legacy schema to v2.

Legacy table is preserved as `designs_legacy_backup*`.

## Normal Daily Flow

### 0. Create concept JSON (required)

Every new design should have a concept file at:
`concepts/<design-stem>.json`

Example:
- ASCII file: `designs/ship-it.txt`
- Required concept file: `concepts/ship-it.json`

### 1. Render and register rows
```bash
python -m sticker_factory render designs/vibe-coder.txt --output-dir exports/
```

Notes:
- Concept auto-discovery: `designs/vibe-coder.txt` looks for `concepts/vibe-coder.json`
- Render now requires a concept file by default.
- Variation precedence: concept `variations` first, then `config.yaml` fallback
- Re-render same design + supersede active rows:
```bash
python -m sticker_factory render designs/vibe-coder.txt --output-dir exports/ --force
```

Emergency override (not recommended):
```bash
python -m sticker_factory render designs/quick-test.txt --allow-no-concept
```

### 2. Generate listing copy into DB

Process specific files/dirs:
```bash
python -m sticker_factory copywrite exports/
```

Process all active rows missing copy:
```bash
python -m sticker_factory copywrite --no-copy
```

Regenerate copy even when already ready:
```bash
python -m sticker_factory copywrite --no-copy --overwrite
```

### 3. Inspect rows

Show table:
```bash
python -m sticker_factory list
```

Filters:
```bash
python -m sticker_factory list --no-copy
python -m sticker_factory list --unpublished
python -m sticker_factory list --needs-republish
```

Show one row:
```bash
python -m sticker_factory show 123
```

### 4. Publish

Publish one row:
```bash
python -m sticker_factory publish 123 --no-etsy
```

Publish one row and push to Etsy:
```bash
python -m sticker_factory publish 123 --etsy
```

Batch publish all ready rows (active + never published):
```bash
python -m sticker_factory publish --ready --no-etsy
```

Republish a row already uploaded/published:
```bash
python -m sticker_factory publish 123 --republish --no-etsy
```

## Sidecar Import (Legacy Copy)

Copy sidecars are no longer written by `copywrite`, but existing sidecars can be imported.

Preview changes:
```bash
python -m sticker_factory migrate-sidecars exports/ --dry-run
```

Apply import:
```bash
python -m sticker_factory migrate-sidecars exports/ --apply
```

## Printify Reconciliation

Mark active DB rows as deleted when product is missing from Printify:
```bash
python -m sticker_factory sync
```

## Expected Row State Fields

- `copy_state`: `missing | ready | error`
- `publish_state`: `never | uploaded | published | deleted | error`
- `is_superseded`: `0 | 1`
- `copy_revision`, `published_copy_revision`: used for republish detection
