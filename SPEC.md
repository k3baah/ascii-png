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

## Build Order

1. **Config + DB** — config loading, SQLite schema, data models
2. **Renderer** — ASCII-to-PNG with print-quality sizing and color variations (refactor existing code)
3. **Ideation** — concept brief generation via Claude API
4. **ASCII generation** — ASCII art from concept briefs via Claude API
5. **CLI** — subcommands to run each step independently
6. **Publisher** — Printify API integration (once API key is set up)
7. **Pipeline glue** — `sticker run` to chain everything
