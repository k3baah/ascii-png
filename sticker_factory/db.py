"""SQLite schema and helper functions for the designs database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "sticker_factory.db"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

VALID_COPY_STATES = {"missing", "ready", "error"}
VALID_PUBLISH_STATES = {"never", "uploaded", "published", "deleted", "error"}

JSON_COLUMNS = {"listing_tags"}

V2_COLUMNS = {
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
}

INSERTABLE_COLUMNS = V2_COLUMNS - {"id"}
UPDATABLE_COLUMNS = INSERTABLE_COLUMNS - {"created_at"}

LEGACY_COLUMNS = {
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
}


def _get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Return a sqlite3 connection with row_factory set."""
    db_path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _create_v2_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS designs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            design_key TEXT NOT NULL,
            concept_id TEXT,
            variation_name TEXT,
            variation_fg TEXT,
            variation_bg TEXT,
            png_path TEXT,
            png_path_canonical TEXT,
            ascii_file_path TEXT,
            listing_title TEXT,
            listing_description TEXT,
            listing_tags TEXT,
            copy_state TEXT NOT NULL DEFAULT 'missing',
            copy_revision INTEGER NOT NULL DEFAULT 0,
            publish_state TEXT NOT NULL DEFAULT 'never',
            published_copy_revision INTEGER NOT NULL DEFAULT 0,
            is_superseded INTEGER NOT NULL DEFAULT 0,
            printify_product_id TEXT,
            etsy_listing_url TEXT,
            last_error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _create_v2_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_designs_active_design_key
        ON designs(design_key)
        WHERE is_superseded = 0
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_designs_active_png_path
        ON designs(png_path_canonical)
        WHERE is_superseded = 0 AND png_path_canonical IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_designs_copy_state
        ON designs(copy_state, is_superseded, created_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_designs_publish_state
        ON designs(publish_state, is_superseded, created_at)
        """
    )


def _next_backup_table_name(conn: sqlite3.Connection) -> str:
    base = "designs_legacy_backup"
    name = base
    idx = 1
    while _table_exists(conn, name):
        name = f"{base}_{idx}"
        idx += 1
    return name


def _safe_json_load(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _safe_json_list(value: Any) -> list[Any]:
    parsed = _safe_json_load(value)
    if isinstance(parsed, list):
        return parsed
    return []


def _canonicalize_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve(strict=False)
    else:
        path = path.resolve(strict=False)
    return str(path)


def _infer_identity_from_paths(
    png_path: str | None,
    ascii_file_path: str | None,
) -> tuple[str | None, str]:
    """Infer concept_id + variation_name from file naming conventions."""
    concept_id = None
    variation_name = "default"

    if png_path:
        stem = Path(png_path).stem
        if "_" in stem:
            concept_id, variation_name = stem.rsplit("_", 1)
        else:
            concept_id = stem

    if not concept_id and ascii_file_path:
        concept_id = Path(ascii_file_path).stem

    return concept_id, variation_name


def _make_design_key(
    concept_id: str | None,
    variation_name: str | None,
    png_path_canonical: str | None = None,
    legacy_id: int | None = None,
    ordinal: int = 0,
) -> str:
    if concept_id:
        return f"{concept_id}::{variation_name or 'default'}"
    if png_path_canonical:
        return f"path::{png_path_canonical}"
    return f"legacy::{legacy_id or 0}::{ordinal}"


def _legacy_status_to_states(status: str | None) -> tuple[str, str]:
    status = (status or "").lower()
    if status == "published":
        return "ready", "published"
    if status == "uploaded":
        return "ready", "uploaded"
    if status == "deleted":
        return "ready", "deleted"
    if status == "error":
        return "error", "error"
    if status == "copywritten":
        return "ready", "never"
    return "missing", "never"


def _migrate_legacy_table(conn: sqlite3.Connection) -> None:
    backup_table = _next_backup_table_name(conn)
    conn.execute(f"ALTER TABLE designs RENAME TO {backup_table}")
    _create_v2_table(conn)

    rows = conn.execute(
        f"SELECT * FROM {backup_table} ORDER BY created_at DESC, id DESC"
    ).fetchall()

    active_design_keys: set[str] = set()
    active_png_paths: set[str] = set()

    for row in rows:
        source = dict(row)
        png_paths = _safe_json_list(source.get("png_file_paths")) or [None]
        colors = _safe_json_list(source.get("colors"))

        for index, png_path in enumerate(png_paths):
            png_path = str(png_path) if png_path else None
            png_path_canonical = _canonicalize_path(png_path)

            concept_id, variation_name = _infer_identity_from_paths(
                png_path_canonical, source.get("ascii_file_path")
            )
            color = colors[index] if index < len(colors) and isinstance(colors[index], dict) else {}
            if color.get("name"):
                variation_name = color["name"]

            design_key = _make_design_key(
                concept_id=concept_id,
                variation_name=variation_name,
                png_path_canonical=png_path_canonical,
                legacy_id=source.get("id"),
                ordinal=index,
            )

            is_superseded = 0
            if design_key in active_design_keys:
                is_superseded = 1
            elif png_path_canonical and png_path_canonical in active_png_paths:
                is_superseded = 1
            else:
                active_design_keys.add(design_key)
                if png_path_canonical:
                    active_png_paths.add(png_path_canonical)

            copy_state, publish_state = _legacy_status_to_states(source.get("status"))
            listing_title = source.get("concept_title")
            copy_revision = 1 if listing_title else 0
            published_copy_revision = (
                copy_revision if publish_state in {"uploaded", "published"} else 0
            )

            conn.execute(
                """
                INSERT INTO designs (
                    design_key,
                    concept_id,
                    variation_name,
                    variation_fg,
                    variation_bg,
                    png_path,
                    png_path_canonical,
                    ascii_file_path,
                    listing_title,
                    listing_description,
                    listing_tags,
                    copy_state,
                    copy_revision,
                    publish_state,
                    published_copy_revision,
                    is_superseded,
                    printify_product_id,
                    etsy_listing_url,
                    last_error,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    design_key,
                    concept_id,
                    variation_name,
                    color.get("fg"),
                    color.get("bg"),
                    png_path_canonical or png_path,
                    png_path_canonical,
                    source.get("ascii_file_path"),
                    listing_title,
                    None,
                    None,
                    copy_state,
                    copy_revision,
                    publish_state,
                    published_copy_revision,
                    is_superseded,
                    source.get("printify_product_id"),
                    source.get("etsy_listing_url"),
                    None,
                    source.get("created_at"),
                    source.get("updated_at"),
                ),
            )


def _normalize_legacy_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    data = dict(kwargs)

    if "status" in data:
        copy_state, publish_state = _legacy_status_to_states(data.pop("status"))
        data.setdefault("copy_state", copy_state)
        data.setdefault("publish_state", publish_state)

    if "png_file_paths" in data and "png_path" not in data:
        png_paths = data.pop("png_file_paths")
        if isinstance(png_paths, str):
            png_paths = _safe_json_load(png_paths)
        if isinstance(png_paths, list) and png_paths:
            data["png_path"] = str(png_paths[0])
        elif png_paths:
            data["png_path"] = str(png_paths)

    if "concept_title" in data and "listing_title" not in data:
        data["listing_title"] = data.pop("concept_title")

    # Removed fields from v1 schema are ignored by v2 writes.
    data.pop("concept_brief", None)
    data.pop("ascii_art", None)
    data.pop("colors", None)

    return data


def _prepare_write_kwargs(
    kwargs: dict[str, Any],
    *,
    apply_defaults: bool,
) -> dict[str, Any]:
    data = _normalize_legacy_kwargs(kwargs)

    if "listing_tags" in data and data["listing_tags"] is not None:
        if isinstance(data["listing_tags"], str):
            parsed = _safe_json_load(data["listing_tags"])
            if isinstance(parsed, list):
                data["listing_tags"] = parsed
            else:
                raise ValueError("listing_tags must be a list or JSON list string")
        if not isinstance(data["listing_tags"], list):
            raise ValueError("listing_tags must be a list")
        data["listing_tags"] = json.dumps(data["listing_tags"])

    if "png_path" in data:
        data["png_path_canonical"] = _canonicalize_path(data["png_path"])
        if data["png_path_canonical"] is not None:
            data["png_path"] = data["png_path_canonical"]

    if "png_path_canonical" in data and data["png_path_canonical"] is not None:
        data["png_path_canonical"] = _canonicalize_path(data["png_path_canonical"])

    if apply_defaults:
        if "copy_state" not in data:
            has_copy = bool(data.get("listing_title") or data.get("listing_description"))
            data["copy_state"] = "ready" if has_copy else "missing"
        if "publish_state" not in data:
            data["publish_state"] = (
                "uploaded" if data.get("printify_product_id") else "never"
            )
        if "copy_revision" not in data:
            data["copy_revision"] = 1 if data["copy_state"] == "ready" else 0
        if "published_copy_revision" not in data:
            data["published_copy_revision"] = (
                data["copy_revision"]
                if data["publish_state"] in {"uploaded", "published"}
                else 0
            )
        data.setdefault("is_superseded", 0)

    needs_design_key = (
        apply_defaults
        or any(
            key in data
            for key in ("concept_id", "variation_name", "png_path", "png_path_canonical")
        )
    )
    if needs_design_key and "design_key" not in data:
        concept_id = data.get("concept_id")
        variation_name = data.get("variation_name")
        if (not concept_id or not variation_name) and (
            data.get("png_path_canonical") or data.get("ascii_file_path")
        ):
            inferred_concept, inferred_variation = _infer_identity_from_paths(
                data.get("png_path_canonical"), data.get("ascii_file_path")
            )
            concept_id = concept_id or inferred_concept
            variation_name = variation_name or inferred_variation
            if concept_id is not None:
                data["concept_id"] = concept_id
            if variation_name is not None:
                data["variation_name"] = variation_name

        data["design_key"] = _make_design_key(
            concept_id=concept_id,
            variation_name=variation_name,
            png_path_canonical=data.get("png_path_canonical"),
        )

    if "copy_state" in data and data["copy_state"] not in VALID_COPY_STATES:
        raise ValueError(
            f"Invalid copy_state '{data['copy_state']}'. Must be one of {VALID_COPY_STATES}"
        )
    if "publish_state" in data and data["publish_state"] not in VALID_PUBLISH_STATES:
        raise ValueError(
            f"Invalid publish_state '{data['publish_state']}'. Must be one of {VALID_PUBLISH_STATES}"
        )
    if "is_superseded" in data:
        data["is_superseded"] = int(bool(data["is_superseded"]))

    return data


def init_db(db_path: str | Path | None = None) -> None:
    """Create/migrate the designs table to the v2 DB-first schema."""
    conn = _get_connection(db_path)
    try:
        if not _table_exists(conn, "designs"):
            _create_v2_table(conn)
        else:
            existing_columns = _get_table_columns(conn, "designs")
            if "copy_state" not in existing_columns or "publish_state" not in existing_columns:
                _migrate_legacy_table(conn)
            else:
                missing_columns = V2_COLUMNS - existing_columns
                if missing_columns:
                    raise RuntimeError(
                        "Existing designs table is neither legacy nor full v2 schema. "
                        f"Missing columns: {sorted(missing_columns)}"
                    )

        _create_v2_indexes(conn)
        conn.commit()
    finally:
        conn.close()


def _serialize_row(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a dict, deserializing JSON columns."""
    data = dict(row)
    for col in JSON_COLUMNS:
        if data.get(col) is not None:
            parsed = _safe_json_load(data[col])
            data[col] = parsed if isinstance(parsed, list) else []
    return data


def insert_design(db_path: str | Path | None = None, **kwargs: Any) -> int:
    """Insert a new design row. Returns the new row id."""
    data = _prepare_write_kwargs(kwargs, apply_defaults=True)
    unknown = set(data) - INSERTABLE_COLUMNS
    if unknown:
        raise ValueError(f"Unknown insert columns: {sorted(unknown)}")

    if not data:
        raise ValueError("insert_design requires at least one field")

    columns = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    values = list(data.values())

    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            f"INSERT INTO designs ({columns}) VALUES ({placeholders})", values
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def get_design(design_id: int, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Retrieve a single design by id. Returns a dict or None."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM designs WHERE id = ?", (design_id,)).fetchone()
        if row is None:
            return None
        return _serialize_row(row)
    finally:
        conn.close()


def get_design_by_png_path(
    png_path: str | Path,
    db_path: str | Path | None = None,
    include_superseded: bool = False,
) -> dict[str, Any] | None:
    """Retrieve one design row by canonical PNG path."""
    canonical_path = _canonicalize_path(str(png_path))
    if canonical_path is None:
        return None

    conn = _get_connection(db_path)
    try:
        query = "SELECT * FROM designs WHERE png_path_canonical = ?"
        params: list[Any] = [canonical_path]
        if not include_superseded:
            query += " AND is_superseded = 0"
        query += " ORDER BY created_at DESC LIMIT 1"
        row = conn.execute(query, tuple(params)).fetchone()
        if row is None:
            return None
        return _serialize_row(row)
    finally:
        conn.close()


def update_design(
    design_id: int,
    db_path: str | Path | None = None,
    **kwargs: Any,
) -> int:
    """Update fields on an existing design. Returns number of rows affected."""
    data = _prepare_write_kwargs(kwargs, apply_defaults=False)
    unknown = set(data) - UPDATABLE_COLUMNS
    if unknown:
        raise ValueError(f"Unknown update columns: {sorted(unknown)}")

    if not data:
        return 0

    data["updated_at"] = "CURRENT_TIMESTAMP"

    set_clauses = []
    values: list[Any] = []
    for key, value in data.items():
        if value == "CURRENT_TIMESTAMP":
            set_clauses.append(f"{key} = CURRENT_TIMESTAMP")
        else:
            set_clauses.append(f"{key} = ?")
            values.append(value)

    values.append(design_id)
    set_clause = ", ".join(set_clauses)

    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(f"UPDATE designs SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return int(cursor.rowcount)
    finally:
        conn.close()


def list_designs(
    *,
    status: str | None = None,
    copy_state: str | None = None,
    publish_state: str | None = None,
    is_superseded: int | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List designs with optional compatibility and v2 filters."""
    if status is not None:
        status = status.lower()
        if status == "copywritten":
            copy_state = "ready"
            publish_state = publish_state or "never"
        elif status == "rendered":
            copy_state = "missing"
            publish_state = publish_state or "never"
        elif status in VALID_PUBLISH_STATES:
            publish_state = status
        else:
            raise ValueError(
                "Invalid status filter. Use legacy status aliases "
                "('rendered', 'copywritten') or publish states "
                f"{sorted(VALID_PUBLISH_STATES)}."
            )

    if copy_state is not None and copy_state not in VALID_COPY_STATES:
        raise ValueError(
            f"Invalid copy_state '{copy_state}'. Must be one of {VALID_COPY_STATES}"
        )
    if publish_state is not None and publish_state not in VALID_PUBLISH_STATES:
        raise ValueError(
            f"Invalid publish_state '{publish_state}'. Must be one of {VALID_PUBLISH_STATES}"
        )

    clauses = []
    values: list[Any] = []

    if copy_state is not None:
        clauses.append("copy_state = ?")
        values.append(copy_state)
    if publish_state is not None:
        clauses.append("publish_state = ?")
        values.append(publish_state)
    if is_superseded is not None:
        clauses.append("is_superseded = ?")
        values.append(int(bool(is_superseded)))

    query = "SELECT * FROM designs"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"

    conn = _get_connection(db_path)
    try:
        rows = conn.execute(query, values).fetchall()
        return [_serialize_row(row) for row in rows]
    finally:
        conn.close()
