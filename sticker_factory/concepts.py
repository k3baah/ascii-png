"""Helpers for loading and validating concept JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONCEPTS_DIR = PROJECT_ROOT / "concepts"


def concept_path_for_id(
    concept_id: str,
    concepts_dir: Path | None = None,
) -> Path:
    """Return the canonical concept path for a concept id."""
    concepts_dir = concepts_dir or DEFAULT_CONCEPTS_DIR
    return concepts_dir / f"{concept_id}.json"


def load_concept(concept_path: str | Path) -> dict[str, Any]:
    """Load and validate a concept JSON file."""
    path = Path(concept_path)
    with open(path) as f:
        concept = json.load(f)

    if not isinstance(concept, dict):
        raise ValueError(f"Concept file must be an object: {path}")

    concept_id = concept.get("id") or path.stem
    if not isinstance(concept_id, str) or not concept_id.strip():
        raise ValueError(f"Concept id must be a non-empty string: {path}")
    concept["id"] = concept_id.strip()

    variations = concept.get("variations", [])
    if variations is None:
        variations = []
    if not isinstance(variations, list):
        raise ValueError(f"Concept variations must be a list: {path}")

    normalized_variations: list[dict[str, str]] = []
    for idx, item in enumerate(variations):
        if not isinstance(item, dict):
            raise ValueError(f"Variation #{idx} must be an object: {path}")

        scheme = item.get("scheme") or item.get("name")
        fg = item.get("fg")
        bg = item.get("bg")
        if not isinstance(scheme, str) or not scheme.strip():
            raise ValueError(f"Variation #{idx} missing non-empty scheme/name: {path}")
        if not isinstance(fg, str) or not fg.strip():
            raise ValueError(f"Variation #{idx} missing non-empty fg: {path}")
        if not isinstance(bg, str) or not bg.strip():
            raise ValueError(f"Variation #{idx} missing non-empty bg: {path}")

        normalized_variations.append(
            {"scheme": scheme.strip(), "fg": fg.strip(), "bg": bg.strip()}
        )
    concept["variations"] = normalized_variations

    keywords = concept.get("keywords")
    if keywords is not None:
        if not isinstance(keywords, list) or not all(
            isinstance(keyword, str) for keyword in keywords
        ):
            raise ValueError(f"Concept keywords must be a list of strings: {path}")

    ascii_file = concept.get("ascii_file")
    if ascii_file is not None and not isinstance(ascii_file, str):
        raise ValueError(f"Concept ascii_file must be a string: {path}")

    return concept


def discover_concept_for_ascii(
    ascii_file: str | Path,
    concepts_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Load the concept whose id matches the ASCII filename stem."""
    ascii_stem = Path(ascii_file).stem
    concept_path = concept_path_for_id(ascii_stem, concepts_dir=concepts_dir)
    if not concept_path.exists():
        return None
    return load_concept(concept_path)


def list_concepts(concepts_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load all valid concepts from the concepts directory."""
    concepts_dir = concepts_dir or DEFAULT_CONCEPTS_DIR
    if not concepts_dir.is_dir():
        return []
    concepts: list[dict[str, Any]] = []
    for concept_path in sorted(concepts_dir.glob("*.json")):
        concepts.append(load_concept(concept_path))
    return concepts
