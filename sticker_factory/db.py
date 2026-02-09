"""SQLite schema and helper functions for the designs database."""

import json
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "sticker_factory.db"

VALID_STATUSES = {
    "ideated",
    "generated",
    "rendered",
    "pending_review",
    "approved",
    "rejected",
    "published",
}

JSON_COLUMNS = {"png_file_paths", "colors"}


def _get_connection(db_path=None):
    """Return a sqlite3 connection with row_factory set."""
    db_path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path=None):
    """Create the designs table if it does not exist."""
    conn = _get_connection(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS designs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_title TEXT,
                concept_brief TEXT,
                ascii_art TEXT,
                ascii_file_path TEXT,
                png_file_paths TEXT,
                colors TEXT,
                status TEXT,
                printify_product_id TEXT,
                etsy_listing_url TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _serialize_row(row):
    """Convert a sqlite3.Row to a dict, deserializing JSON columns."""
    d = dict(row)
    for col in JSON_COLUMNS:
        if d.get(col) is not None:
            d[col] = json.loads(d[col])
    return d


def insert_design(db_path=None, **kwargs):
    """Insert a new design row. Returns the new row id.

    JSON columns (png_file_paths, colors) accept Python objects
    and are serialized automatically.
    """
    for col in JSON_COLUMNS:
        if col in kwargs and kwargs[col] is not None:
            kwargs[col] = json.dumps(kwargs[col])

    if "status" in kwargs and kwargs["status"] not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{kwargs['status']}'. Must be one of {VALID_STATUSES}"
        )

    columns = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" for _ in kwargs)
    values = list(kwargs.values())

    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            f"INSERT INTO designs ({columns}) VALUES ({placeholders})", values
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_design(design_id, db_path=None):
    """Retrieve a single design by id. Returns a dict or None."""
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM designs WHERE id = ?", (design_id,)
        ).fetchone()
        if row is None:
            return None
        return _serialize_row(row)
    finally:
        conn.close()


def update_design(design_id, db_path=None, **kwargs):
    """Update fields on an existing design. Returns number of rows affected.

    JSON columns (png_file_paths, colors) accept Python objects
    and are serialized automatically.
    """
    for col in JSON_COLUMNS:
        if col in kwargs and kwargs[col] is not None:
            kwargs[col] = json.dumps(kwargs[col])

    if "status" in kwargs and kwargs["status"] not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{kwargs['status']}'. Must be one of {VALID_STATUSES}"
        )

    # Always bump updated_at on update
    kwargs["updated_at"] = "CURRENT_TIMESTAMP"

    set_clauses = []
    values = []
    for key, val in kwargs.items():
        if val == "CURRENT_TIMESTAMP":
            set_clauses.append(f"{key} = CURRENT_TIMESTAMP")
        else:
            set_clauses.append(f"{key} = ?")
            values.append(val)

    values.append(design_id)
    set_clause = ", ".join(set_clauses)

    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE designs SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def list_designs(status=None, db_path=None):
    """List all designs, optionally filtered by status. Returns a list of dicts."""
    conn = _get_connection(db_path)
    try:
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(
                    f"Invalid status '{status}'. Must be one of {VALID_STATUSES}"
                )
            rows = conn.execute(
                "SELECT * FROM designs WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM designs ORDER BY created_at DESC"
            ).fetchall()
        return [_serialize_row(row) for row in rows]
    finally:
        conn.close()
