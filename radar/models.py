"""Core data structures shared across the pipeline."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Listing:
    """A single, cleaned real-estate listing.

    Only ``price`` and ``size_sqm`` are strictly required for scoring; entries
    missing either are dropped during cleaning.
    """

    source: str
    title: str
    price: float               # EUR
    size_sqm: float            # living area in m^2
    location: str              # human-readable district / city
    zip_code: str = ""
    rooms: Optional[float] = None
    url: str = ""
    description: str = ""
    category: str = "apartment"  # "apartment" | "house" | ...
    listing_id: str = ""       # stable id used for dedup + DB primary key

    # Historical fields, populated from the persistent store.
    first_seen: str = ""       # ISO timestamp of first observation
    last_seen: str = ""        # ISO timestamp of most recent observation
    initial_price: Optional[float] = None  # price when first observed

    # Populated by the scoring engine (not persisted as a hard dependency).
    price_per_sqm: float = 0.0
    deal_score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.price and self.size_sqm:
            self.price_per_sqm = round(self.price / self.size_sqm, 2)
        if not self.listing_id:
            self.listing_id = self._derive_id()

    def _derive_id(self) -> str:
        """Deterministic id so re-scrapes update rather than duplicate rows."""
        if self.url:
            basis = self.url
        else:
            basis = f"{self.source}|{self.title}|{self.location}|{self.price}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def district_key(self) -> str:
        """District identifier (ZIP preferred, else the location string)."""
        if self.zip_code:
            return self.zip_code
        return self.location.strip().lower() or "unknown"

    @property
    def median_key(self) -> str:
        """Grouping key for €/m² medians.

        Houses and apartments have very different €/m² levels, so medians are
        computed *per category per district* to keep the discount fair.
        """
        return f"{self.category}:{self.district_key}"

    @property
    def days_listed(self) -> Optional[int]:
        """Days between first observation and now (needs history)."""
        if not self.first_seen:
            return None
        from datetime import datetime, timezone
        try:
            first = datetime.fromisoformat(self.first_seen)
        except ValueError:
            return None
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - first).days)

    @property
    def price_change_pct(self) -> Optional[float]:
        """Percentage change vs. the first observed price (negative = drop)."""
        if not self.initial_price or self.initial_price <= 0:
            return None
        if abs(self.initial_price - self.price) < 1:
            return 0.0
        return (self.price - self.initial_price) / self.initial_price * 100.0

    def to_row(self) -> dict:
        """Flatten for SQLite persistence (scoring fields excluded)."""
        return {
            "listing_id": self.listing_id,
            "source": self.source,
            "title": self.title,
            "price": self.price,
            "size_sqm": self.size_sqm,
            "rooms": self.rooms,
            "location": self.location,
            "zip_code": self.zip_code,
            "url": self.url,
            "description": self.description,
            "category": self.category,
            "price_per_sqm": self.price_per_sqm,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Listing":
        return cls(
            source=row["source"],
            title=row["title"],
            price=row["price"],
            size_sqm=row["size_sqm"],
            location=row["location"],
            zip_code=row.get("zip_code", "") or "",
            rooms=row.get("rooms"),
            url=row.get("url", "") or "",
            description=row.get("description", "") or "",
            category=row.get("category", "apartment") or "apartment",
            listing_id=row["listing_id"],
            first_seen=row.get("first_seen", "") or "",
            last_seen=row.get("last_seen", "") or "",
            initial_price=row.get("initial_price"),
        )

    def as_dict(self) -> dict:
        return asdict(self)
