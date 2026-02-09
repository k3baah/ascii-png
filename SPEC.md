# Sticker Factory — Spec

## Overview

Autonomous sticker design pipeline for an Etsy print-on-demand store using Printify as fulfillment. The system generates sticker designs, renders them as print-ready PNGs, and publishes them via the Printify API.

**Approach:** Build each pipeline component independently and manually glue them together before automating the full chain.

## Pipeline Components

### 1. Ideation

- **Input:** Niche config (e.g. "developer/tech culture"), number of ideas to generate
- **Output:** Concept briefs stored in SQLite (title, description, style hints, suggested colors)
- **Engine:** Claude API (Anthropic) — two-step process:
  1. LLM generates concept briefs (e.g. "retro terminal skull with glitch effects")
  2. Separate LLM call generates ASCII art from the brief
- **Dedup:** Not enforced — similar designs are fine, variations sell

### 2. Design / Rendering

**v1: ASCII-to-PNG only.** AI image generation (ChatGPT image, Gemini Imagen) deferred to v2.

- **Input:** ASCII art text (from ideation or manual .txt files)
- **Output:** Print-ready PNG (transparent or white background, 300 DPI, ~2000-4000px)
- **Rendering:**
  - Monospace font rendering via Pillow
  - Large font size (200-400px) to hit print resolution natively — no upscaling
  - Configurable padding
- **Color variations:** Render the same design in multiple foreground color schemes to create product variations
- **Background rules:**
  - Default: white background (avoids die-cut spacing issues)
  - Option for transparent, but only when the design is contiguous (no large gaps that would create separate cut regions)
- **Art styles:** Mix of classic ASCII art (character pictures) and text/typography-based designs — LLM decides per concept

### 3. Review (v1: Manual)

- Designs land in a `designs/` folder and are logged in SQLite with status `pending_review`
- User manually inspects and approves/rejects via CLI (`sticker review --approve <id>` / `--reject <id>`)
- No automated review in v1

### 4. Publishing (Printify)

- **Status:** Printify account exists, API key not yet set up
- **Input:** Approved design PNG + metadata
- **Output:** Product created on Printify, linked to Etsy store
- **Product type:** Individual stickers (sticker sheets deferred to later)
- **Listing copy:** Deferred — will generate titles/descriptions/tags when building this component
- **Integration:** Via Printify REST API

## Tech Stack

- **Backend/pipeline:** Python (single package, modular)
- **Frontend/dashboard:** TypeScript (deferred — not in v1)
- **Runtime:** Local machine, cron/launchd for scheduling (later)
- **Config:** YAML config file (`config.yaml`) + `.env` for secrets (API keys)

## Project Structure

```
sticker-factory/          # will rename repo later
├── config.yaml           # niche, volume, font size, colors, etc.
├── .env                  # API keys (ANTHROPIC_API_KEY, PRINTIFY_API_KEY)
├── sticker_factory/
│   ├── __init__.py
│   ├── cli.py            # single CLI entry point with subcommands
│   ├── config.py         # config loading (YAML + env)
│   ├── db.py             # SQLite schema + helpers
│   ├── ideation.py       # concept generation via Claude
│   ├── ascii_gen.py      # ASCII art generation via Claude
│   ├── renderer.py       # ASCII-to-PNG rendering (Pillow)
│   ├── publisher.py      # Printify API integration
│   └── models.py         # data models (Design, Concept, etc.)
├── designs/              # generated ASCII art files
├── exports/              # rendered PNGs
├── requirements.txt
└── SPEC.md
```

## CLI Interface

Single CLI with subcommands:

```bash
sticker ideate              # generate concept briefs
sticker generate            # generate ASCII art from concepts
sticker render              # render ASCII art to PNG
sticker review              # list pending designs for review
sticker review --approve 3  # approve a design
sticker publish             # publish approved designs to Printify
sticker run                 # (later) chain all steps
```

Start with one design at a time; batch support added later.

## Data Model (SQLite)

### `designs` table

| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-increment |
| concept_title | TEXT | Short title (e.g. "Glitch Skull Terminal") |
| concept_brief | TEXT | Full concept description |
| ascii_art | TEXT | Generated ASCII art content |
| ascii_file_path | TEXT | Path to .txt file |
| png_file_paths | JSON | List of rendered PNGs (color variations) |
| colors | JSON | Color schemes used |
| status | TEXT | `ideated`, `generated`, `rendered`, `pending_review`, `approved`, `rejected`, `published` |
| printify_product_id | TEXT | Printify product ID (after publishing) |
| etsy_listing_url | TEXT | Etsy URL (after publishing) |
| created_at | DATETIME | Timestamp |
| updated_at | DATETIME | Timestamp |

## Observability

- **v1:** Structured logging to SQLite (pipeline runs, design statuses, errors)
- **Later:** TypeScript dashboard on top of SQLite, plus notifications (Slack/Discord)
- Track: designs generated, approved/rejected ratio, published count, error rate

## Error Handling (v1)

- Basic try/catch with logging
- Log errors, skip failed designs, continue with the rest
- No retries or dead letter queue in v1

## Configuration (`config.yaml`)

```yaml
niche: "developer and tech culture"
ideation:
  model: "claude-sonnet-4-5-20250929"
  ideas_per_run: 3
ascii_generation:
  model: "claude-sonnet-4-5-20250929"
rendering:
  font_size: 300
  padding: 40
  default_background: "white"
  color_schemes:
    - { name: "classic", fg: "white", bg: "black" }
    - { name: "matrix", fg: "#00ff00", bg: "transparent" }
    - { name: "sunset", fg: "#ff6b35", bg: "transparent" }
```

Volume (ideas_per_run) is configurable.

## Quality / Sizing

- Target: 300 DPI, 2000-4000px on longest side
- Achieved by rendering ASCII at large font sizes (200-400px) natively
- No AI upscaling in v1

## Budget

- Quality over cost — use the best models available
- No hard spend limits, but cost tracking per design logged in SQLite

## Out of Scope (v1)

- AI image generation (GPT image, Gemini Imagen) — v2
- Sticker sheet composition (multiple stickers on one sheet) — later
- Automated design review (LLM-based quality check) — later
- Etsy listing copy generation (titles, tags, descriptions) — deferred to publisher component
- TypeScript dashboard — later
- Trend-based ideation scraping — later
- Deduplication / similarity checking — not planned

## DB-First Publish Flow (v2 Data Model)

### Principles

- **DB is the single source of truth** for operational/publishing state.
- **One row = one rendered PNG.** Each color variation of a design gets its own row.
- **Copy state and publish state are separate.** Generating new copy does not implicitly republish.
- **Concept JSON files** (`concepts/`) stay on disk as human-editable creative input. DB references them via `concept_id` but does not duplicate their content.
- **Superseding is non-destructive.** Re-rendering marks older active rows as superseded while preserving publish history.
- **DB never lies about Printify state.** If a product is live on Printify, publish state reflects that.

### Revised `designs` table

| Column | Type | Description |
|---|---|---|
| id | INTEGER PK | Auto-increment |
| design_key | TEXT | Stable logical identity for the active design variant (e.g. `vibe-coder::matrix`) |
| concept_id | TEXT | References a concept JSON file (e.g. `vibe-coder`). NULL if no concept file. |
| variation_name | TEXT | Color scheme name (e.g. `matrix`, `classic`). Together with concept_id, uniquely identifies a design. |
| variation_fg | TEXT | Foreground color used for this render |
| variation_bg | TEXT | Background color used for this render |
| png_path | TEXT | Absolute path to the rendered PNG file |
| png_path_canonical | TEXT | Normalized absolute path (`Path.resolve(strict=False)`) used for lookup/uniqueness |
| ascii_file_path | TEXT | Path to source ASCII .txt file |
| listing_title | TEXT | Etsy listing title (written by copywrite) |
| listing_description | TEXT | Etsy listing description HTML (written by copywrite) |
| listing_tags | TEXT (JSON) | JSON array of Etsy tags (written by copywrite) |
| copy_state | TEXT | `missing`, `ready`, `error` |
| copy_revision | INTEGER | Incremented whenever listing copy is regenerated |
| publish_state | TEXT | `never`, `uploaded`, `published`, `deleted`, `error` |
| published_copy_revision | INTEGER | Copy revision that was last successfully published |
| is_superseded | INTEGER | 0 or 1. Set to 1 when a newer render replaces this image. Old Printify state preserved. |
| printify_product_id | TEXT | Printify product ID (set by publish) |
| etsy_listing_url | TEXT | Etsy URL (set by publish) |
| last_error | TEXT | Last pipeline error message for this row (optional) |
| created_at | DATETIME | Row creation timestamp |
| updated_at | DATETIME | Last update timestamp |

**Dropped columns** (vs v1): `concept_title`, `concept_brief`, `ascii_art`, `png_file_paths` (JSON list), `colors` (JSON list), `status`.

**Uniqueness rules (active rows only):**
- `UNIQUE(design_key) WHERE is_superseded=0`
- `UNIQUE(png_path_canonical) WHERE is_superseded=0 AND png_path_canonical IS NOT NULL`

### Lifecycle

```
render                      copywrite                     publish
  │                            │                            │
  ▼                            ▼                            ▼
INSERT row                 UPDATE row                   UPDATE row
copy_state=missing         listing_title=...            printify_product_id=...
publish_state=never        listing_description=...      publish_state=uploaded|published
copy_revision=0            listing_tags=...             published_copy_revision=copy_revision
is_superseded=0            copy_state=ready
                           copy_revision += 1
```

### Render behavior

- `sticker render <ascii_file>` renders PNGs and **inserts one DB row per variation**.
- **Variation source precedence:** concept JSON `variations` field first; if absent, fall back to `config.yaml` global `color_schemes`.
- **Concept auto-discovery:** infers `concept_id` from the ASCII filename (e.g. `designs/vibe-coder.txt` → `concepts/vibe-coder.json`). `--concept` flag overrides.
- **Idempotent by default:** skips variations that already have an active row + PNG on disk.
- **`--force` flag:** re-renders all variations. Old active rows are marked `is_superseded=1`. New rows are inserted as active rows.
- **Path handling:** render writes both `png_path` and canonicalized `png_path_canonical`.

### Copywrite behavior

- Writes `listing_title`, `listing_description`, `listing_tags` to the DB row.
- Sets `copy_state=ready`, increments `copy_revision`, and records errors via `copy_state=error` + `last_error`.
- Does **not** mutate `publish_state`.
- **Two input modes:**
  1. File paths / directories (looks up DB row by `png_path`)
  2. DB filter: `sticker copywrite --no-copy` processes rows where `copy_state=missing`
- Sidecar `.copy.json` files are **retired**.
- Existing sidecar files are imported via `sticker migrate-sidecars --dry-run|--apply` (no LLM regeneration required).

### Publish behavior

- **DB-first:** reads `png_path`, `listing_title`, `listing_description`, `listing_tags` from the DB row. No sidecar fallback.
- **Requires ready copy:** refuses to publish unless `copy_state=ready` and title/description are populated. Prints "run copywrite first" error.
- **Input modes:**
  1. `sticker publish --ready` — batch-publishes rows with `copy_state=ready`, `publish_state=never`, and `is_superseded=0`
  2. `sticker publish <id>` — publish a specific DB row by id
- Optional `--republish` allows publishing rows where `publish_state` is already `uploaded` or `published`.
- Updates the row: sets `printify_product_id`, `etsy_listing_url`, `published_copy_revision=copy_revision`, and `publish_state`:
  - `uploaded` when only Printify product creation succeeds
  - `published` when Etsy publish succeeds
- `--etsy / --no-etsy` flag controls whether to also push to Etsy (default: Printify only).

### CLI inspection commands

```bash
sticker list                    # table: id, concept, variation, copy_state, publish_state, is_superseded
sticker list --no-copy          # filter to rows missing listing copy
sticker list --unpublished      # filter to rows not yet published
sticker list --needs-republish  # copy_revision > published_copy_revision
sticker show <id>               # full detail on one row
```

### Sync with Printify

- `sticker sync` — on-demand command that fetches current products from Printify API and reconciles with DB.
- For active rows with a `printify_product_id`, marks `publish_state=deleted` if product no longer exists on Printify.
- Not run automatically. User invokes when needed.

### Concept files

- Stay in `concepts/` as human-editable JSON, git-tracked.
- Format: `{ id, brief, style, keywords, ascii_file, variations: [{scheme, fg, bg}] }`
- **Concept owns:** creative direction, variation definitions, keywords.
- **DB owns:** render state, listing copy, publish state, Printify IDs.
- Render reads `variations` from concept file to determine which color schemes to produce.

### Variation precedence (for render)

1. CLI flags (if render ever supports explicit `--variations`)
2. Concept JSON `variations` field
3. Global `config.yaml` `color_schemes` (fallback if no concept file)

## Build Order

1. **Config + DB** — config loading, SQLite schema, data models
2. **Renderer** — ASCII-to-PNG with print-quality sizing and color variations (refactor existing code)
3. **Ideation** — concept brief generation via Claude API
4. **ASCII generation** — ASCII art from concept briefs via Claude API
5. **CLI** — subcommands to run each step independently
6. **Publisher** — Printify API integration (once API key is set up)
7. **Pipeline glue** — `sticker run` to chain everything
