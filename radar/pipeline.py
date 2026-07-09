"""End-to-end pipeline orchestration."""
from __future__ import annotations

from .config import Config
from .market import compute_barometer
from .render import render_html
from .scoring import score_all
from .scrapers import scrape_all
from .storage import Store

# Only show listings seen within this window on the dashboard (fresh/available),
# while still using the full historical DB for median computation.
RECENT_WINDOW_DAYS = 30


def run(cfg: Config | None = None) -> str:
    cfg = cfg or Config.from_env()
    print("=== Real Estate Market Radar ===")
    print(f"scope: zips={cfg.target_zip_codes or 'ALL'} "
          f"max_price={cfg.max_price_limit} sources={cfg.sources}")

    # 1. Scrape + clean.
    fresh = scrape_all(cfg)

    # 2. Persist into the rolling baseline DB, then read back.
    with Store(cfg.db_path) as store:
        store.upsert_many(fresh)
        baseline = store.all_listings()            # full history for medians
        candidates = store.recent_listings(RECENT_WINDOW_DAYS)  # what we display

    # If nothing is in the DB yet (e.g. first ever run with no persistence),
    # fall back to the freshly scraped batch.
    if not candidates:
        candidates = fresh
    if not baseline:
        baseline = fresh

    print(f"scoring {len(candidates)} candidates against "
          f"{len(baseline)} baseline listings")

    # 3. Score + sort (best deals first).
    ranked = score_all(candidates, baseline, cfg)

    # 3b. Derive the market barometer (buy vs. wait).
    barometer = compute_barometer(ranked, cfg)
    print(f"market: heat={barometer.heat} -> {barometer.recommendation} "
          f"({barometer.confidence} confidence)")

    # 4. Render the static dashboard.
    html_out = render_html(ranked, cfg, barometer)
    with open(cfg.output_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)
    print(f"wrote {cfg.output_path} ({len(html_out):,} bytes, "
          f"{len(ranked)} listings)")
    return cfg.output_path
