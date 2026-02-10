"""Data models -- Design, Concept, and other domain objects."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


VALID_COPY_STATES = ("missing", "ready", "error")
VALID_PUBLISH_STATES = ("never", "uploaded", "published", "deleted", "error")


@dataclass
class Design:
    """Mirrors the v2 designs table in SQLite."""

    id: int | None = None
    design_key: str = ""
    concept_id: str | None = None
    variation_name: str | None = None
    variation_fg: str | None = None
    variation_bg: str | None = None
    png_path: str | None = None
    png_path_canonical: str | None = None
    ascii_file_path: str | None = None
    listing_title: str | None = None
    listing_description: str | None = None
    listing_tags: list[str] = field(default_factory=list)
    copy_state: str = "missing"
    copy_revision: int = 0
    publish_state: str = "never"
    published_copy_revision: int = 0
    is_superseded: int = 0
    printify_product_id: str | None = None
    etsy_listing_url: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for DB insertion or JSON export.

        JSON-typed fields are serialized so they can be stored in SQLite TEXT.
        """
        return {
            "id": self.id,
            "design_key": self.design_key,
            "concept_id": self.concept_id,
            "variation_name": self.variation_name,
            "variation_fg": self.variation_fg,
            "variation_bg": self.variation_bg,
            "png_path": self.png_path,
            "png_path_canonical": self.png_path_canonical,
            "ascii_file_path": self.ascii_file_path,
            "listing_title": self.listing_title,
            "listing_description": self.listing_description,
            "listing_tags": json.dumps(self.listing_tags),
            "copy_state": self.copy_state,
            "copy_revision": self.copy_revision,
            "publish_state": self.publish_state,
            "published_copy_revision": self.published_copy_revision,
            "is_superseded": self.is_superseded,
            "printify_product_id": self.printify_product_id,
            "etsy_listing_url": self.etsy_listing_url,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> Design:
        """Construct a Design from a sqlite3.Row, dict, or tuple.

        JSON-typed columns are deserialized back into Python objects.
        """
        if hasattr(row, "keys"):
            # sqlite3.Row or dict-like
            d = dict(row)
        elif isinstance(row, (list, tuple)):
            keys = [
                "id",
                "design_key",
                "concept_id",
                "variation_name",
                "variation_fg",
                "variation_bg",
                "png_path",
                "png_path_canonical",
                "ascii_file_path",
                "listing_title",
                "listing_description",
                "listing_tags",
                "copy_state",
                "copy_revision",
                "publish_state",
                "published_copy_revision",
                "is_superseded",
                "printify_product_id",
                "etsy_listing_url",
                "last_error",
                "created_at",
                "updated_at",
            ]
            d = dict(zip(keys, row))
        else:
            d = dict(row)

        val = d.get("listing_tags")
        if isinstance(val, str):
            try:
                d["listing_tags"] = json.loads(val)
            except json.JSONDecodeError:
                d["listing_tags"] = []
        elif val is None:
            d["listing_tags"] = []

        return cls(**d)
