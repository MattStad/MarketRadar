# Real Estate Market Radar

A **static-site generator** for spotting the best property deals. It scrapes
regional real-estate listings, computes a holistic **Deal Score (0–100)** for
each one across four weighted dimensions, ranks the best opportunities to the
top, and renders a single self-contained `index.html` dashboard ready for
**GitHub Pages**.

No instant alerts — it aggregates everything and shows you the strongest deals
first, with a transparent breakdown of *why* each one scored the way it did.

![dashboard](https://img.shields.io/badge/output-index.html-4f8cff)

## Deal Score — the multi-factor engine

A property is **never** ranked by price-per-m² alone. The final score is a
weighted blend (see [`radar/scoring.py`](radar/scoring.py)):

| Weight | Dimension | What it rewards |
|-------:|-----------|-----------------|
| **40%** | **Price/m² discount** | Negative deviation from the median €/m² computed **per category, per district** (houses and apartments are benchmarked separately). Uses a **confidence weighting**: without a real local sample (≥6 listings in that district) the discount is damped toward neutral and capped — so a cheap rural property can't top the ranking on a *fake* discount vs. a broad national median. |
| **20%** | **Layout & room efficiency** | Space-efficient plans (~22–30 m²/room). Bonus for a 3-room < 70 m² or 2-room < 48 m²; penalty for e.g. an oversized 1-room > 55 m². |
| **12%** | **Absolute price sweet-spot** | Low entry prices (progressive boost at/under `PRICE_SWEET_SPOT`, default €250k). |
| **12%** | **Price momentum** | Rewards listings whose price has **dropped since first seen** (tracked in the price-history table). Neutral until history exists. |
| **8%** | **Soft flags / keywords** | + `provisionsfrei`, `balkon`, `terrasse`, `gute anbindung` … / − `renovierungsbedürftig`, `befristet vermietet` … |
| **8%** | **Freshness** | Rewards recently-appeared listings; penalizes stale ones (45+ days on market). |

Every sub-score also emits human-readable **drivers** shown as pills on each card.
Momentum and freshness activate once the persistent DB has accumulated history
across runs.

**Quality guard (hard caps):** severe red flags cap the *final* score no matter
how cheap the listing is — teardown / building-plot / shell (`abbruch`, `rohbau`,
`bauland`, …) → max 42, reserved/sold → 48, needs-major-renovation → 58,
commercial/investment (`zinshaus`, `gewerbe`, …) → 62. This keeps junk out of the
top ranks.

## Market barometer (buy vs. wait)

At the top of the dashboard a **Market Barometer** gives a single *Market Heat*
score (0–100) and a **Buy / Selective / Wait** recommendation, with a gauge and a
breakdown of the signals behind it ([`radar/market.py`](radar/market.py)):

- **Valuation** — current median €/m² vs. your `FAIR_PPSQM` reference (answers
  "are prices high?"; only shown when the reference is set).
- **Asking-price trend** — are listings cutting or raising prices (from the
  accumulated price history).
- **Deal availability** — how many strong below-market deals are on the market.
- **Market turnover** — how fast listings are appearing (liquidity).

Higher heat = pricier / seller's market (lean toward waiting); lower = buyer's
market (good time to buy). Trend and turnover start at low confidence and sharpen
as the tool re-runs and builds history. *Heuristic on listing data — not
financial advice.*

## Interactive dashboard

The generated `index.html` is a **fully client-side filterable** dashboard (no
server needed). You can search and narrow results by:

- **Free-text search** (title, location, ZIP)
- **Source** (e.g. `willhaben-wohnung`, `willhaben-haus`) and **property type** (apartment / house)
- **Min deal score** (slider), **max price**, **min m²**, **min rooms**
- **Sort** by deal score, price ↑/↓, €/m² ↑, size ↓, or newest

Ranks renumber live as you filter/sort.

## Data sources

| Backend | Origin portals | Status |
|---------|----------------|--------|
| **`willhaben`** | Willhaben apartments (`willhaben-wohnung`) + houses (`willhaben-haus`) | ✅ live, default |
| **`immmo`** | [IMMMO](https://www.immmo.at) meta-search — aggregates **ImmobilienScout24, FindMyHome, dibeo, flatbee, immo.sn (Salzburger Nachrichten)** and more | ✅ live, default |
| `immoscout24` | ImmobilienScout24 (direct) | ⚠️ placeholder — direct SERP is client-rendered; reachable **indirectly via `immmo`** |

Each listing keeps its **origin portal** as its `source` label, so the dashboard
can filter by portal (e.g. `immobilienscout24`, `findmyhome`, `willhaben-haus`).
A typical run yields ~480 listings across ~7 sources.

> Why an aggregator? Among the major Austrian portals, Willhaben is the only one
> that exposes clean, complete data directly (embedded `__NEXT_DATA__` JSON).
> immoscout24.at / immowelt render listings client-side or gate their APIs, and
> derStandard only exposes €/m². IMMMO server-renders results from *many* portals
> with stable markup, so a single feed there unlocks broad, diverse coverage —
> including portals that block direct scraping. Feeds are configurable via
> `WILLHABEN_FEEDS` and `IMMMO_FEEDS`.

## Quick start

```bash
python generate_radar.py      # scrapes Willhaben live, writes ./index.html
open index.html               # (or just open it in a browser)
```

Runs with **zero third-party dependencies** — the entire pipeline (scraping via
`urllib`, storage via `sqlite3`, scoring and HTML rendering) uses only the Python
standard library. It scrapes **real listings from the internet**; there is no
demo/sample data.

## Configuration (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_ZIP_CODES` | *(all)* | Comma-separated ZIPs to include, e.g. `1020,1100,1160`. |
| `MAX_PRICE_LIMIT` | `600000` | Drop listings above this price. |
| `MIN_PRICE_LIMIT` | `20000` | Drop suspiciously cheap / broken entries. |
| `MIN_SIZE_SQM` | `15` | Minimum living area. |
| `PRICE_SWEET_SPOT` | `250000` | Absolute-price sub-score is maxed at/under this. |
| `FAIR_PPSQM` | *(unset)* | Your fair-value €/m² reference. When set, the market barometer reports how far current prices sit above/below it. |
| `SOURCES` | `willhaben,immmo` | Comma-separated live scraper backends. |
| `WILLHABEN_FEEDS` | *(condos + houses)* | JSON array of `{label,url,category}` feeds to override the defaults. |
| `IMMMO_FEEDS` | *(buy, Vienna)* | JSON array of `{url}` feeds (page number appended) to override the default. |
| `DB_PATH` | `data/radar.sqlite` | Historical baseline store. |
| `OUTPUT_PATH` | `index.html` | Where the dashboard is written. |

Examples:

```bash
TARGET_ZIP_CODES=1020,1100 MAX_PRICE_LIMIT=350000 python generate_radar.py

# Custom feeds (e.g. only Vienna houses):
WILLHABEN_FEEDS='[{"label":"willhaben-haus","category":"house","url":"https://www.willhaben.at/iad/immobilien/haus-kaufen/wien?rows=100&page={page}"}]' \
  python generate_radar.py
```

## How the data pipeline works

1. **Scrape & clean** ([`radar/scrapers`](radar/scrapers)) — each backend yields
   raw dicts; a shared stage parses messy strings (`"€ 249.000,-"`, `"73,5 m²"`),
   maps them to numbers, and **skips entries missing price or size**.
2. **Persist** ([`radar/storage.py`](radar/storage.py)) — listings are upserted
   into **SQLite** so a continuous historical baseline accumulates, and every
   price change is written to a `price_history` table. This is what makes
   location medians *stable* and powers the momentum/freshness metrics.
3. **Score & sort** ([`radar/scoring.py`](radar/scoring.py)) — medians are
   computed from the full history; candidates (seen in the last 30 days) are
   scored and sorted **descending by Deal Score**.
4. **Render** ([`radar/render.py`](radar/render.py)) — a single, fully-inlined
   `index.html` (no external CSS/JS/fonts).

### Scrapers

- **`willhaben`** ([`radar/scrapers/willhaben.py`](radar/scrapers/willhaben.py))
  fetches live Willhaben search pages per *feed* and parses the embedded
  `__NEXT_DATA__` JSON (no API key). Ships with two feeds — Vienna condos and
  Austria houses. Override via `WILLHABEN_FEEDS`.
- **`immmo`** ([`radar/scrapers/immmo.py`](radar/scrapers/immmo.py)) parses the
  server-rendered result lists of the IMMMO meta-search, attributing each listing
  to its origin portal. Override via `IMMMO_FEEDS`.

Both use only the standard library (`urllib`) and sleep between pages.

> ⚠️ **Respect each portal's Terms of Service and `robots.txt`.** Scrape only
> data you're permitted to access, at a polite rate. The sites' markup / embedded
> JSON changes without notice — maintain the parsers as needed. The direct
> `immoscout24` backend is an honest placeholder (its SERP is client-rendered);
> ImmobilienScout24 listings are covered indirectly through `immmo`.

Add a new source by subclassing `BaseScraper`, yielding record dicts with keys
`title, price, size_sqm, rooms, location, zip_code, url, description`, and
registering it in [`radar/scrapers/__init__.py`](radar/scrapers/__init__.py).

## Deploying to GitHub Pages (CI/CD)

[`.github/workflows/scrape_and_deploy.yml`](.github/workflows/scrape_and_deploy.yml)
runs **daily via cron** (05:30 UTC), regenerates `index.html`, commits it plus
the baseline DB back to the repo, and deploys to GitHub Pages.

Setup:

1. **Settings → Pages →** Source: *GitHub Actions*.
2. (Optional) **Settings → Secrets and variables → Actions → Variables:** set
   `TARGET_ZIP_CODES`, `MAX_PRICE_LIMIT`, `SOURCES`, `WILLHABEN_FEEDS`, `IMMMO_FEEDS`, etc.
3. Push to `main` — or trigger the workflow manually from the **Actions** tab.

The workflow has `contents: write` (to commit the refreshed dashboard) and
`pages: write` (to deploy).

## Project layout

```
generate_radar.py              # entry point
requirements.txt
radar/
  config.py                    # env-var driven configuration
  models.py                    # Listing dataclass
  storage.py                   # SQLite historical baseline + price history
  scoring.py                   # the 6-factor Deal Score engine + hard caps
  market.py                    # market barometer (buy vs. wait gauge)
  render.py                    # self-contained, filterable HTML generator
  pipeline.py                  # scrape -> store -> score -> render
  scrapers/
    base.py                    # BaseScraper + cleaning stage
    willhaben.py               # live Willhaben scraper (condos + houses)
    immmo.py                   # live IMMMO meta-search scraper (multi-portal)
    immoscout24.py             # placeholder template
.github/workflows/scrape_and_deploy.yml
```

---

*Informational tool only — not investment advice.*
