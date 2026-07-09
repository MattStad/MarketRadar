"""Runtime configuration, driven entirely by environment variables.

Everything the CI/CD pipeline needs to tune lives here so the same script can be
run locally or headlessly in GitHub Actions without code changes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def _split_csv(raw: str) -> list[str]:
    """Split a comma/space separated env value into a clean list."""
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_feeds(raw: str) -> list[dict]:
    """Parse the WILLHABEN_FEEDS env var (JSON array) into feed dicts."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        feeds = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for f in feeds if isinstance(feeds, list) else []:
        if isinstance(f, dict) and f.get("url"):
            out.append({
                "label": f.get("label", "willhaben"),
                "url": f["url"],
                "category": f.get("category", "apartment"),
            })
    return out


def _parse_immmo_feeds(raw: str) -> list[dict]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        feeds = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [{"url": f["url"]} for f in feeds
            if isinstance(f, dict) and f.get("url")]


@dataclass
class Config:
    """Fully resolved configuration for a single run."""

    # --- Targeting -----------------------------------------------------------
    target_zip_codes: list[str] = field(default_factory=list)
    """Restrict output to these ZIP/postal codes. Empty means "all"."""

    max_price_limit: int = 600_000
    """Hard ceiling. Listings above this are dropped before scoring."""

    min_price_limit: int = 20_000
    """Floor to filter out obviously broken / non-residential entries."""

    min_size_sqm: float = 15.0
    """Minimum living area to be considered a real apartment."""

    max_results: int = 250
    """How many listings the scraper attempts to collect per source."""

    # --- Scoring knobs -------------------------------------------------------
    price_sweet_spot: int = 250_000
    """At/under this absolute price the sweet-spot sub-score is maxed."""

    fair_ppsqm: int = 0
    """Optional fair-value €/m² reference for the market barometer's valuation
    signal. 0 = unset (the barometer then relies on the other signals). Set via
    ``FAIR_PPSQM`` to answer "are prices high vs. what I consider fair?"."""

    # --- Data pipeline -------------------------------------------------------
    sources: list[str] = field(default_factory=lambda: ["willhaben", "immmo"])
    """Which live scraper backends to run, e.g. ``willhaben,immmo``."""

    willhaben_feeds: list[dict] = field(default_factory=list)
    """Willhaben search feeds. Each is ``{"label","url","category"}``. Empty
    uses the built-in defaults (Vienna apartments + Austria houses). Override
    via the ``WILLHABEN_FEEDS`` env var as a JSON array."""

    immmo_feeds: list[dict] = field(default_factory=list)
    """IMMMO meta-search feeds. Each is ``{"url"}`` (page number appended).
    Empty uses the built-in default (buy, Vienna). Override via ``IMMMO_FEEDS``
    as a JSON array."""

    db_path: str = "data/radar.sqlite"
    """SQLite file used to preserve a rolling historical baseline."""

    output_path: str = "index.html"
    """Where the generated dashboard is written."""

    request_timeout: int = 20
    user_agent: str = (
        "Mozilla/5.0 (compatible; RealEstateMarketRadar/1.0; "
        "+https://github.com/)"
    )

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            target_zip_codes=_split_csv(os.environ.get("TARGET_ZIP_CODES", "")),
            max_price_limit=_get_int("MAX_PRICE_LIMIT", 600_000),
            min_price_limit=_get_int("MIN_PRICE_LIMIT", 20_000),
            min_size_sqm=_get_float("MIN_SIZE_SQM", 15.0),
            max_results=_get_int("MAX_RESULTS", 250),
            price_sweet_spot=_get_int("PRICE_SWEET_SPOT", 250_000),
            fair_ppsqm=_get_int("FAIR_PPSQM", 0),
            sources=_split_csv(os.environ.get("SOURCES", "")) or ["willhaben", "immmo"],
            willhaben_feeds=_parse_feeds(os.environ.get("WILLHABEN_FEEDS", "")),
            immmo_feeds=_parse_immmo_feeds(os.environ.get("IMMMO_FEEDS", "")),
            db_path=os.environ.get("DB_PATH", "data/radar.sqlite").strip()
            or "data/radar.sqlite",
            output_path=os.environ.get("OUTPUT_PATH", "index.html").strip()
            or "index.html",
            request_timeout=_get_int("REQUEST_TIMEOUT", 20),
            user_agent=os.environ.get("USER_AGENT", cls.user_agent),
        )
