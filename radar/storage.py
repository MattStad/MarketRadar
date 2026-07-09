"""SQLite-backed store that preserves a continuous historical baseline.

Keeping every listing we have ever seen (upserted by ``listing_id``) lets us
compute *stable* location medians even when a single day's scrape returns only a
handful of listings for a given district. It also tracks price history so the
scoring engine can reward listings whose price has dropped since first seen.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from .models import Listing


_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id     TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    title          TEXT,
    price          REAL NOT NULL,
    size_sqm       REAL NOT NULL,
    rooms          REAL,
    location       TEXT,
    zip_code       TEXT,
    url            TEXT,
    description    TEXT,
    category       TEXT DEFAULT 'apartment',
    price_per_sqm  REAL,
    initial_price  REAL,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_zip ON listings (zip_code);
CREATE INDEX IF NOT EXISTS idx_listings_location ON listings (location);
CREATE INDEX IF NOT EXISTS idx_listings_category ON listings (category);

CREATE TABLE IF NOT EXISTS price_history (
    listing_id  TEXT NOT NULL,
    price       REAL NOT NULL,
    seen_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_listing ON price_history (listing_id);
"""


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the first release, if missing."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(listings)")}
        for col, ddl in (
            ("category", "ALTER TABLE listings ADD COLUMN category TEXT DEFAULT 'apartment'"),
            ("initial_price", "ALTER TABLE listings ADD COLUMN initial_price REAL"),
        ):
            if col not in cols:
                self.conn.execute(ddl)
        # Backfill initial_price for pre-existing rows.
        self.conn.execute(
            "UPDATE listings SET initial_price = price WHERE initial_price IS NULL"
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def upsert_many(self, listings: Iterable[Listing]) -> int:
        """Insert new listings / refresh known ones, recording price changes."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        count = 0
        for listing in listings:
            row = listing.to_row()
            prev = self.conn.execute(
                "SELECT price FROM listings WHERE listing_id = ?",
                (listing.listing_id,),
            ).fetchone()

            self.conn.execute(
                """
                INSERT INTO listings (
                    listing_id, source, title, price, size_sqm, rooms,
                    location, zip_code, url, description, category,
                    price_per_sqm, initial_price, first_seen, last_seen
                ) VALUES (
                    :listing_id, :source, :title, :price, :size_sqm, :rooms,
                    :location, :zip_code, :url, :description, :category,
                    :price_per_sqm, :price, :now, :now
                )
                ON CONFLICT(listing_id) DO UPDATE SET
                    price         = excluded.price,
                    size_sqm      = excluded.size_sqm,
                    rooms         = excluded.rooms,
                    title         = excluded.title,
                    location      = excluded.location,
                    zip_code      = excluded.zip_code,
                    url           = excluded.url,
                    description   = excluded.description,
                    category      = excluded.category,
                    price_per_sqm = excluded.price_per_sqm,
                    last_seen     = excluded.last_seen
                    -- initial_price intentionally preserved
                """,
                {**row, "now": now},
            )

            # Record a history point on first sight or when the price changed.
            if prev is None or abs((prev["price"] or 0) - listing.price) >= 1:
                self.conn.execute(
                    "INSERT INTO price_history (listing_id, price, seen_at) "
                    "VALUES (?, ?, ?)",
                    (listing.listing_id, listing.price, now),
                )
            count += 1
        self.conn.commit()
        return count

    def all_listings(self) -> list[Listing]:
        """Every listing ever seen — the baseline for median computation."""
        cur = self.conn.execute("SELECT * FROM listings")
        return [Listing.from_row(dict(r)) for r in cur.fetchall()]

    def recent_listings(self, max_age_days: int) -> list[Listing]:
        """Listings whose ``last_seen`` falls within ``max_age_days``.

        These are the candidates shown on the dashboard (fresh & available).
        """
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
        out: list[Listing] = []
        cur = self.conn.execute("SELECT * FROM listings")
        for r in cur.fetchall():
            try:
                seen = datetime.fromisoformat(r["last_seen"]).timestamp()
            except (ValueError, TypeError):
                continue
            if seen >= cutoff:
                out.append(Listing.from_row(dict(r)))
        return out
