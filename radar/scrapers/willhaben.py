"""Willhaben.at scraper (live, multi-feed).

Willhaben ships its search results as JSON embedded in a ``__NEXT_DATA__``
script tag. This backend fetches the search result pages for one or more
*feeds* (e.g. apartments for sale, houses for sale), extracts that JSON and maps
the relevant attributes onto our raw-record shape. Uses only the standard
library (``urllib``) so it runs with zero third-party dependencies.

Each feed becomes a distinct ``source`` label so the dashboard can filter by it.

Verified attribute names (subject to change without notice — maintain as needed):
    PRICE, ESTATE_SIZE/LIVING_AREA, ESTATE_SIZE, NUMBER_OF_ROOMS,
    LOCATION, POSTCODE, HEADING, BODY_DYN, SEO_URL

IMPORTANT — respect willhaben's Terms of Service and ``robots.txt``. Only scrape
data you are permitted to access, at a polite rate.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.request
from typing import Iterable

from .base import BaseScraper

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

# Two genuinely different datasets from the same portal: condos and houses.
# Medians are computed per category (see Listing.median_key) so the discount
# stays fair across property types.
DEFAULT_FEEDS = [
    {
        "label": "willhaben-wohnung",
        "url": "https://www.willhaben.at/iad/immobilien/eigentumswohnung/wien"
               "?rows=100&page={page}",
        "category": "apartment",
    },
    {
        "label": "willhaben-haus",
        "url": "https://www.willhaben.at/iad/immobilien/haus-kaufen/haus-angebote"
               "?rows=100&page={page}",
        "category": "house",
    },
]


def _attr_map(ad: dict) -> dict[str, str]:
    """Willhaben stores fields as ``[{'name': ..., 'values': [...]}, ...]``."""
    out: dict[str, str] = {}
    for attr in ad.get("attributes", {}).get("attribute", []) or []:
        name = attr.get("name")
        values = attr.get("values") or []
        if name and values:
            out[name] = values[0]
    return out


class WillhabenScraper(BaseScraper):
    name = "willhaben"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        feeds = getattr(cfg, "willhaben_feeds", None) or DEFAULT_FEEDS
        self.feeds = []
        for f in feeds:
            url = f["url"]
            if "{page}" not in url:
                url += ("&" if "?" in url else "?") + "page={page}"
            self.feeds.append({
                "label": f.get("label", "willhaben"),
                "url": url,
                "category": f.get("category", "apartment"),
            })

    def _get(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.cfg.user_agent,
                "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "gzip",
            },
        )
        with urllib.request.urlopen(req, timeout=self.cfg.request_timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")

    def _parse_page(self, html: str, feed: dict) -> list[dict]:
        m = _NEXT_DATA_RE.search(html)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        try:
            ads = (
                data["props"]["pageProps"]["searchResult"]
                ["advertSummaryList"]["advertSummary"]
            )
        except (KeyError, TypeError):
            return []

        records: list[dict] = []
        for ad in ads:
            a = _attr_map(ad)
            seo = a.get("SEO_URL", "")
            url = f"https://www.willhaben.at/iad/{seo}" if seo else ""
            records.append({
                "source": feed["label"],
                "category": feed["category"],
                "title": a.get("HEADING") or ad.get("description", ""),
                "price": a.get("PRICE"),  # numeric str, or "Preis auf Anfrage"
                "size_sqm": a.get("ESTATE_SIZE/LIVING_AREA") or a.get("ESTATE_SIZE"),
                "rooms": a.get("NUMBER_OF_ROOMS"),
                "location": a.get("LOCATION") or a.get("DISTRICT", ""),
                "zip_code": a.get("POSTCODE", ""),
                "url": url,
                "description": a.get("BODY_DYN") or ad.get("description", ""),
            })
        return records

    def _fetch_feed(self, feed: dict) -> list[dict]:
        collected: list[dict] = []
        page = 1
        while len(collected) < self.cfg.max_results and page <= 15:
            html = self._get(feed["url"].format(page=page))
            page_records = self._parse_page(html, feed)
            if not page_records:
                break
            collected.extend(page_records)
            print(f"[willhaben:{feed['label']}] page {page}: "
                  f"+{len(page_records)} (total {len(collected)})")
            page += 1
            time.sleep(1.5)  # be polite
        return collected[: self.cfg.max_results]

    def fetch(self) -> Iterable[dict]:
        out: list[dict] = []
        for feed in self.feeds:
            try:
                out.extend(self._fetch_feed(feed))
            except Exception as exc:  # noqa: BLE001
                print(f"[willhaben:{feed['label']}] failed: {exc!r}")
        return out
