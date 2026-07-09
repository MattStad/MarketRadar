"""ImmobilienScout24 scraper template.

A minimal, honest placeholder. ImmobilienScout24 employs aggressive bot
protection (Cloudflare / device fingerprinting), so a naive ``requests`` scrape
will usually be blocked. This class documents the shape a real implementation
should produce and, by default, returns nothing rather than pretending.

To implement for real you will typically need either:
  * their official partner/data API (preferred, ToS-compliant), or
  * a headless browser (Playwright/Selenium) with appropriate rate limiting.
"""
from __future__ import annotations

from typing import Iterable

from .base import BaseScraper


class ImmoScout24Scraper(BaseScraper):
    name = "immoscout24"

    def fetch(self) -> Iterable[dict]:
        print(
            "[immoscout24] template backend — no live implementation. "
            "Wire up the official API or a headless browser here. "
            "Each yielded dict should look like:\n"
            "  {'source','title','price','size_sqm','rooms',"
            "'location','zip_code','url','description'}"
        )
        return []
