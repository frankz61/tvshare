import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    -- processing | ready | failed
    status TEXT NOT NULL,
    duration REAL,
    width INTEGER,
    height INTEGER,
    size INTEGER,
    original_name TEXT,
    error TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_category ON videos(category_id);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    title TEXT NOT NULL,
    category_id INTEGER,
    created_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- categories ----

    def list_categories(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.sort_order,
                       (SELECT COUNT(*) FROM videos v WHERE v.category_id = c.id) AS video_count
                FROM categories c ORDER BY c.sort_order, c.id
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_category(self, category_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        return dict(row) if row else None

    def create_category(self, name: str) -> dict:
        with self.connect() as conn:
            next_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM categories").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO categories (name, sort_order, created_at) VALUES (?, ?, ?)",
                (name, next_order, time.time()),
            )
            category_id = cur.lastrowid
        return self.get_category(category_id)  # type: ignore[return-value]

    def update_category(self, category_id: int, name: str | None, sort_order: int | None) -> None:
        with self.connect() as conn:
            if name is not None:
                conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
            if sort_order is not None:
                conn.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (sort_order, category_id))

    def delete_category(self, category_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    # ---- videos ----

    def list_videos(self, category_id: int | None = None, uncategorized: bool = False) -> list[dict]:
        sql = "SELECT * FROM videos"
        args: tuple = ()
        if uncategorized:
            sql += " WHERE category_id IS NULL"
        elif category_id is not None:
            sql += " WHERE category_id = ?"
            args = (category_id,)
        sql += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def get_video(self, video_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None

    def create_video(self, video_id: str, title: str, category_id: int | None, original_name: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO videos (id, title, category_id, status, original_name, created_at)
                   VALUES (?, ?, ?, 'processing', ?, ?)""",
                (video_id, title, category_id, original_name, time.time()),
            )

    def update_video(self, video_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.connect() as conn:
            conn.execute(f"UPDATE videos SET {cols} WHERE id = ?", (*fields.values(), video_id))

    def delete_video(self, video_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))

    def videos_with_status(self, status: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM videos WHERE status = ? ORDER BY created_at", (status,)).fetchall()
        return [r["id"] for r in rows]

    # ---- uploads ----

    def create_upload(self, upload_id: str, filename: str, size: int, title: str, category_id: int | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO uploads (id, filename, size, title, category_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (upload_id, filename, size, title, category_id, time.time()),
            )

    def get_upload(self, upload_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
        return dict(row) if row else None

    def delete_upload(self, upload_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))

    def stale_uploads(self, older_than: float) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM uploads WHERE created_at < ?", (older_than,)).fetchall()
        return [r["id"] for r in rows]
