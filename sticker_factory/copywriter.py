"""Listing copy generation -- Claude vision generates Etsy-optimised titles, descriptions, and tags."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import anthropic

from sticker_factory.config import get_config
from sticker_factory.concepts import load_concept

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an Etsy listing copywriter for a print-on-demand sticker shop called PurplePixelsCo. \
You specialise in developer and tech culture stickers.

Given a sticker image, generate a listing with a title, HTML description, and 13 tags \
optimised for Etsy search.

## Title rules
- Short, clear, descriptive. Lead with what the item IS.
- Keep it scannable — a buyer on mobile should instantly understand the product.
- Use a colon or dash to separate the main descriptor from secondary details.
- Do NOT keyword-stuff or use pipes to separate phrases.
- Good: "Vibe Coder ASCII Art Vinyl Sticker: Green Matrix Developer Decal"
- Bad: "Sticker | Developer | Coder | ASCII | Green | Tech Gift | Laptop"

## Description rules
- Write 2-3 short paragraphs in HTML (<p> tags).
- First sentence must contain your strongest keywords (first 160 chars show in search).
- Do NOT copy the title verbatim. Rephrase and expand.
- Include: what it is, what it looks like, material (vinyl), use cases (laptops, water bottles, notebooks, phone cases), size info (various sizes available), durability (waterproof, UV-resistant).
- Write in a friendly, authentic brand voice. Not robotic.

## Tag rules
- Exactly 13 tags. Each tag is a multi-word phrase, max 20 characters.
- Spread across these categories:
  - Descriptive (what it is): e.g. "ASCII art sticker"
  - Materials/technique: e.g. "vinyl decal"
  - Who it's for: e.g. "gift for coder"
  - Occasions: e.g. "developer gift"
  - Style: e.g. "retro tech art"
  - Solution/use: e.g. "laptop decoration"
  - Size: e.g. "small vinyl decal"
- All 13 must be unique — no repeated phrases.
- Use long-tail keywords: "developer sticker" beats "sticker".
- Do NOT repeat category/attribute terms that Etsy adds automatically.

## Output format
Return ONLY valid JSON, no markdown fences:
{"title": "...", "description": "<p>...</p>", "tags": ["tag1", "tag2", ...]}
"""


def find_concept(image_path: Path) -> dict | None:
    """Find the concept file for a given image by matching the design name prefix.

    Scans concepts/ directory for a JSON file whose id matches the longest
    prefix of the image filename. E.g. vibe-coder_matrix_r88.png matches
    concepts/vibe-coder.json.
    """
    concepts_dir = Path(image_path).resolve().parents[0]
    # Walk up to project root to find concepts/
    for parent in Path(image_path).resolve().parents:
        candidate = parent / "concepts"
        if candidate.is_dir():
            concepts_dir = candidate
            break
    else:
        return None

    stem = Path(image_path).stem  # e.g. "vibe-coder_matrix_r88"
    best_match = None
    best_len = 0

    for concept_file in concepts_dir.glob("*.json"):
        try:
            concept = load_concept(concept_file)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Skipping invalid concept file %s: %s", concept_file, exc)
            continue

        concept_id = concept.get("id", concept_file.stem)
        if stem.startswith(concept_id) and len(concept_id) > best_len:
            best_match = concept
            best_len = len(concept_id)

    return best_match


def _build_user_prompt(concept: dict | None) -> str:
    """Build the user text prompt, optionally enriched with concept context."""
    if not concept:
        return "Generate an Etsy listing for this sticker."

    parts = ["Generate an Etsy listing for this sticker.", "", "## Design context"]
    if concept.get("brief"):
        parts.append(f"Concept: {concept['brief']}")
    if concept.get("style"):
        parts.append(f"Style: {concept['style']}")
    if concept.get("keywords"):
        parts.append(f"Keywords: {', '.join(concept['keywords'])}")
    return "\n".join(parts)


def generate_copy(image_path: Path, concept: dict | None = None) -> dict:
    """Send a sticker PNG to Claude and get back Etsy listing copy.

    Parameters
    ----------
    image_path : Path
        Path to the sticker PNG.
    concept : dict, optional
        Concept context (brief, style, keywords) to include in the prompt.

    Returns dict with keys: title, description, tags.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    cfg = get_config()
    model = cfg.get("copywriting", {}).get("model", "claude-sonnet-4-5-20250929")
    api_key = cfg.get("secrets", {}).get("anthropic_api_key")
    if not api_key:
        raise ValueError(
            "No Anthropic API key. Set ANTHROPIC_API_KEY in .env."
        )

    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    suffix = image_path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else f"image/{suffix.lstrip('.')}"

    user_prompt = _build_user_prompt(concept)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if the model adds them despite instructions
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    copy = json.loads(raw)

    # Validate structure
    if "title" not in copy or "description" not in copy or "tags" not in copy:
        raise ValueError(f"Claude response missing required fields: {list(copy.keys())}")
    if not isinstance(copy["tags"], list):
        raise ValueError("tags must be a list")

    logger.info("Generated copy for %s: %s", image_path.name, copy["title"])
    return copy


def write_sidecar(image_path: Path, copy: dict) -> Path:
    """Write listing copy to a sidecar JSON file next to the image."""
    image_path = Path(image_path)
    sidecar_path = image_path.with_suffix(".copy.json")
    with open(sidecar_path, "w") as f:
        json.dump(copy, f, indent=2)
    return sidecar_path


def read_sidecar(image_path: Path) -> dict | None:
    """Read listing copy from a sidecar JSON file, or None if it doesn't exist."""
    sidecar_path = Path(image_path).with_suffix(".copy.json")
    if not sidecar_path.exists():
        return None
    with open(sidecar_path) as f:
        return json.load(f)
