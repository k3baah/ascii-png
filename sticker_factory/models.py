"""Data models -- Design, Concept, and other domain objects."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


VALID_STATUSES = (
    "ideated",
    "generated",
    "rendered",
    "pending_review",
    "approved",
    "rejected",
    "published",
)


@dataclass
class Design:
    """Mirrors the designs table in SQLite."""

    id: int | None = None
    concept_title: str = ""
    concept_brief: str = ""
    ascii_art: str = ""
    ascii_file_path: str = ""
    png_file_paths: list[str] = field(default_factory=list)
    colors: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ideated"
    printify_product_id: str | None = None
    etsy_listing_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for DB insertion or JSON export.

        JSON-typed fields (png_file_paths, colors) are serialized to JSON
        strings so they can be stored directly in SQLite TEXT/JSON columns.
        """
        return {
            "id": self.id,
            "concept_title": self.concept_title,
            "concept_brief": self.concept_brief,
            "ascii_art": self.ascii_art,
            "ascii_file_path": self.ascii_file_path,
            "png_file_paths": json.dumps(self.png_file_paths),
            "colors": json.dumps(self.colors),
            "status": self.status,
            "printify_product_id": self.printify_product_id,
            "etsy_listing_url": self.etsy_listing_url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> Design:
        """Construct a Design from a sqlite3.Row, dict, or tuple.

        JSON-typed columns are deserialized back into Python lists.
        """
        if hasattr(row, "keys"):
            # sqlite3.Row or dict-like
            d = dict(row)
        elif isinstance(row, (list, tuple)):
            keys = [
                "id",
                "concept_title",
                "concept_brief",
                "ascii_art",
                "ascii_file_path",
                "png_file_paths",
                "colors",
                "status",
                "printify_product_id",
                "etsy_listing_url",
                "created_at",
                "updated_at",
            ]
            d = dict(zip(keys, row))
        else:
            d = dict(row)

        # Deserialize JSON fields
        for key in ("png_file_paths", "colors"):
            val = d.get(key)
            if isinstance(val, str):
                d[key] = json.loads(val)
            elif val is None:
                d[key] = []

        return cls(**d)
