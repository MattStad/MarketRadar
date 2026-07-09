"""Scraper base class + the shared cleaning / normalization stage."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Iterable, Optional

from ..config import Config
from ..models import Listing


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @abstractmethod
    def fetch(self) -> Iterable[dict]:
        """Yield raw record dicts with (at least) the following keys:

        ``title, price, size_sqm, rooms, location, zip_code, url, description``.

        Values may be dirty strings; the cleaning stage normalizes them.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Cleaning helpers
# --------------------------------------------------------------------------- #
_ZIP_RE = re.compile(r"\b(\d{4,5})\b")


def parse_number(raw) -> Optional[float]:
    """Turn messy portal strings like '€ 249.000,-' or '73,5 m²' into floats.

    Handles both German (1.234,56) and plain (1234.56) formats.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    s = str(raw)
    # Keep digits, separators and a leading minus.
    s = re.sub(r"[^0-9,.\-]", "", s)
    # Strip the Austrian "even amount" suffix (e.g. "65.000,-") and any stray
    # trailing separators / minus so they don't corrupt the number.
    s = re.sub(r"[-,.]+$", "", s)
    if not s or s in {"-", ".", ","}:
        return None

    has_comma = "," in s
    has_dot = "." in s
    if has_comma and has_dot:
        # Whichever comes last is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        # Comma as decimal if it looks like ",dd" at the end, else thousands.
        if re.search(r",\d{1,2}$", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    # dot-only: assume it's already decimal or thousands; strip thousands dots
    elif re.search(r"\.\d{3}(\D|$)", s):
        s = s.replace(".", "")

    try:
        return float(s)
    except ValueError:
        return None


def extract_zip(record: dict) -> str:
    zip_code = str(record.get("zip_code") or "").strip()
    if _ZIP_RE.fullmatch(zip_code):
        return zip_code
    # Try to pull it out of the location string.
    loc = str(record.get("location") or "")
    m = _ZIP_RE.search(loc)
    return m.group(1) if m else zip_code


def clean_records(raw: list[dict], cfg: Config) -> list[Listing]:
    """Normalize raw records into validated Listing objects.

    Drops anything missing price or size, out of the configured price band, or
    outside the target ZIP codes.
    """
    out: list[Listing] = []
    dropped = 0
    for rec in raw:
        price = parse_number(rec.get("price"))
        size = parse_number(rec.get("size_sqm"))
        if not price or not size:
            dropped += 1
            continue
        if size < cfg.min_size_sqm:
            dropped += 1
            continue
        if price < cfg.min_price_limit or price > cfg.max_price_limit:
            dropped += 1
            continue

        zip_code = extract_zip(rec)
        if cfg.target_zip_codes and zip_code not in cfg.target_zip_codes:
            dropped += 1
            continue

        rooms = parse_number(rec.get("rooms"))
        listing = Listing(
            source=str(rec.get("source") or "unknown"),
            title=str(rec.get("title") or "Untitled listing").strip(),
            price=float(price),
            size_sqm=float(size),
            rooms=rooms,
            location=str(rec.get("location") or "").strip(),
            zip_code=zip_code,
            url=str(rec.get("url") or "").strip(),
            description=str(rec.get("description") or "").strip(),
            category=str(rec.get("category") or "apartment").strip() or "apartment",
        )
        out.append(listing)

    print(f"[clean] kept {len(out)} listings, dropped {dropped}")
    return out
