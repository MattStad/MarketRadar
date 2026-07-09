"""Scraper backends and the cleaning pipeline.

Each backend implements :class:`~radar.scrapers.base.BaseScraper` and yields raw
dicts; the shared cleaning stage in :mod:`radar.scrapers.base` turns those into
validated :class:`~radar.models.Listing` objects.

Only live, real-portal scrapers are registered here — there is no demo/sample
data. Configure which sources run via the ``SOURCES`` env var.
"""
from __future__ import annotations

from ..config import Config
from ..models import Listing
from .base import BaseScraper, clean_records
from .willhaben import WillhabenScraper
from .immmo import ImmmoScraper
from .immoscout24 import ImmoScout24Scraper

_REGISTRY: dict[str, type[BaseScraper]] = {
    "willhaben": WillhabenScraper,
    "immmo": ImmmoScraper,
    "immoscout24": ImmoScout24Scraper,
}


def build_scrapers(cfg: Config) -> list[BaseScraper]:
    """Instantiate the scrapers requested in the config."""
    scrapers: list[BaseScraper] = []
    for name in cfg.sources:
        cls = _REGISTRY.get(name.lower())
        if cls is None:
            print(f"[scrapers] unknown source '{name}', skipping "
                  f"(known: {', '.join(_REGISTRY)})")
            continue
        scrapers.append(cls(cfg))
    if not scrapers:
        raise SystemExit(
            f"No valid scrapers configured. Set SOURCES to one of: "
            f"{', '.join(_REGISTRY)}"
        )
    return scrapers


def scrape_all(cfg: Config) -> list[Listing]:
    """Run every configured scraper and return cleaned listings."""
    raw: list[dict] = []
    for scraper in build_scrapers(cfg):
        try:
            records = list(scraper.fetch())
            print(f"[scrapers] {scraper.name}: {len(records)} raw records")
            raw.extend(records)
        except Exception as exc:  # noqa: BLE001 - never let one source kill the run
            print(f"[scrapers] {scraper.name} failed: {exc!r}")
    return clean_records(raw, cfg)


__all__ = ["build_scrapers", "scrape_all", "BaseScraper", "clean_records"]
