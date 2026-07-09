"""IMMMO.at scraper (live).

IMMMO (https://www.immmo.at) is an Austrian meta-search that aggregates listings
from many portals (ImmobilienScout24, FindMyHome, dibeo, …). Its search result
pages are server-rendered HTML with stable, semantic markup, so a single feed
here yields genuinely *diverse* data across several origin portals — including
ones that block direct scraping. Each listing is attributed to its origin portal
as the ``source`` label. Standard library only (``urllib``).

Result-list markup (stable anchors):
    <li ... data-hostname="www.immobilienscout24.at" ...>
      <h3>Eigentumswohnung in <mark>1200</mark> <mark>Wien</mark></h3>
      <p class="result-link"><a href="https://…/expose/…">Title</a></p>
      <p class="price …">€ 139.000,-</p>
      <p class="result-details">1200 Wien / 46,08m² / <span class="num-rooms">2 Zimmer</span></p>
      … tags: #Altbau #renovierungsbedürftig …

IMPORTANT — respect IMMMO's Terms of Service and ``robots.txt``. Only scrape data
you are permitted to access, at a polite rate.
"""
from __future__ import annotations

import gzip
import re
import time
import urllib.request
from html import unescape
from typing import Iterable

from .base import BaseScraper

DEFAULT_FEEDS = [
    {"url": "https://www.immmo.at/immo/Immobilie-kaufen/Wien/{page}"},
]

_BLOCK_RE = re.compile(r'<li [^>]*data-objecttype="STRUCT"(.*?)</li>', re.DOTALL)
_HOST_RE = re.compile(r'data-hostname="([^"]+)"')
_H3_RE = re.compile(r"<h3>(.*?)</h3>", re.DOTALL)
_LINK_RE = re.compile(r'result-link"><a[^>]*href="([^"?]+)[^>]*>(.*?)</a>', re.DOTALL)
_PRICE_RE = re.compile(r'class="price[^"]*">([^<]+)<')
_DETAILS_RE = re.compile(r'class="result-details">(.*?)</p>', re.DOTALL)
_TAGS_RE = re.compile(r'class="[^"]*result-tags[^"]*">(.*?)</a>', re.DOTALL)

_APT_WORDS = ("wohnung", "dachgesch", "penthouse", "loft", "maisonette",
              "garconniere", "garçonniere", "apartement", "appartement")
_SKIP_WORDS = ("grundst", "gewerbe", "büro", "buero", "garage", "parkplatz",
               "lager", "geschäft", "geschaeft", "betrieb", "hotel", "pension",
               "zinshaus", "anlageobjekt")
# "…haus" as a whole word, but not false friends like "Zuhause"/"Rathaus".
_HOUSE_RE = re.compile(
    r"\b(?:einfamilien|reihen|doppel|stadt|land|bauern|ferien|wochenend|"
    r"garten|winzer|siedlungs)?haus\b|\b(?:villa|bungalow|chalet)\b")
_HOUSE_STOP = ("zuhause", "rathaus", "gasthaus", "kaufhaus", "krankenhaus",
               "elternhaus", "gartenhaus")


def _strip_tags(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def _clean_host(host: str) -> str:
    """Normalize any hostname/URL to a short portal label.

    'www.immobilienscout24.at/' -> 'immobilienscout24',
    'https://immo.snapp.at/x'  -> 'immo.snapp'.
    """
    host = host.strip().lower()
    host = re.sub(r"^https?://", "", host)   # drop scheme
    host = host.split("/")[0]                # drop any path
    host = host.replace("www.", "")
    host = re.sub(r"\.(co\.at|at|com|net|de|eu)$", "", host)
    host = host.strip("/.")
    return host or "immmo"


def _is_house(text: str) -> bool:
    t = re.sub("|".join(_HOUSE_STOP), " ", text.lower())
    return bool(_HOUSE_RE.search(t))


def _categorize(headline: str, title: str, size: float | None) -> str | None:
    # The standardized <h3> headline is the most reliable signal; fall back to
    # the marketing title only when the headline is generic ("Immobilie in …").
    for text in (headline.lower(), title.lower()):
        if any(w in text for w in _SKIP_WORDS):
            return None
        if _is_house(text):
            return "house"
        if any(w in text for w in _APT_WORDS):
            return "apartment"
    # Unknown type: very large footprints are usually plots/projects/commercial.
    if size is not None and size > 250:
        return None
    return "apartment"


class ImmmoScraper(BaseScraper):
    name = "immmo"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        feeds = getattr(cfg, "immmo_feeds", None) or DEFAULT_FEEDS
        self.feeds = []
        for f in feeds:
            url = f["url"]
            if "{page}" not in url:
                url = url.rstrip("/") + "/{page}"
            self.feeds.append({"url": url})

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

    def _parse_page(self, html: str) -> list[dict]:
        records: list[dict] = []
        for block in _BLOCK_RE.findall(html):
            host_m = _HOST_RE.search(block)
            link_m = _LINK_RE.search(block)
            price_m = _PRICE_RE.search(block)
            det_m = _DETAILS_RE.search(block)
            h3_m = _H3_RE.search(block)
            if not (link_m and price_m and det_m):
                continue

            details = _strip_tags(det_m.group(1))
            headline = _strip_tags(h3_m.group(1)) if h3_m else ""
            title = _strip_tags(link_m.group(2))

            size_m = re.search(r"([0-9][0-9.,]*)\s*m", details)
            rooms_m = re.search(r"([0-9][0-9.,]*)\s*Zimmer", details)
            size = None
            if size_m:
                from .base import parse_number
                size = parse_number(size_m.group(1))

            cat = _categorize(headline, title, size)
            if cat is None:
                continue

            zip_m = re.search(r"\b(\d{4,5})\b", headline) or \
                re.search(r"\b(\d{4,5})\b", details)

            tags_m = _TAGS_RE.search(block)
            tags = _strip_tags(tags_m.group(1)) if tags_m else ""

            records.append({
                "source": _clean_host(host_m.group(1)) if host_m else "immmo",
                "category": cat,
                "title": title or headline,
                "price": price_m.group(1),
                "size_sqm": size_m.group(1) if size_m else None,
                "rooms": rooms_m.group(1) if rooms_m else None,
                "location": details.split("/")[0].strip() or "Österreich",
                "zip_code": zip_m.group(1) if zip_m else "",
                "url": link_m.group(1),
                "description": f"{title} {tags}".strip(),
            })
        return records

    def _fetch_feed(self, feed: dict) -> list[dict]:
        collected: list[dict] = []
        seen_urls: set[str] = set()
        page = 1
        while len(collected) < self.cfg.max_results and page <= 40:
            html = self._get(feed["url"].format(page=page))
            page_records = self._parse_page(html)
            # Stop when a page repeats (past the last real page).
            fresh = [r for r in page_records if r["url"] not in seen_urls]
            if not fresh:
                break
            for r in fresh:
                seen_urls.add(r["url"])
            collected.extend(fresh)
            print(f"[immmo] page {page}: +{len(fresh)} (total {len(collected)})")
            page += 1
            time.sleep(1.2)  # be polite
        return collected[: self.cfg.max_results]

    def fetch(self) -> Iterable[dict]:
        out: list[dict] = []
        for feed in self.feeds:
            try:
                out.extend(self._fetch_feed(feed))
            except Exception as exc:  # noqa: BLE001
                print(f"[immmo] feed failed: {exc!r}")
        return out
