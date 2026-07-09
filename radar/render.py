"""Renders the scored listings into a single, self-contained ``index.html``.

No external CSS/JS/fonts — everything is inlined so the file works as a static
GitHub Pages artifact and even when opened directly from disk. The dashboard is
interactive: all filtering/sorting happens client-side over data embedded in the
card markup, so it needs no server.
"""
from __future__ import annotations

import html
import statistics
from datetime import datetime, timezone

from .config import Config
from .market import Barometer
from .models import Listing

_SUB_ORDER = ["discount", "layout", "sweet_spot", "momentum", "soft_flags", "freshness"]
_SUB_LABELS = {
    "discount": "Price/m² Discount",
    "layout": "Layout Efficiency",
    "sweet_spot": "Price Sweet-Spot",
    "momentum": "Price Momentum",
    "soft_flags": "Keywords & Flags",
    "freshness": "Freshness",
}
_CATEGORY_LABELS = {"apartment": "Apartment", "house": "House"}


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _fmt_eur(value) -> str:
    return f"€{value:,.0f}".replace(",", ".")


def _score_tier(score: float) -> tuple[str, str]:
    if score >= 75:
        return "tier-elite", "Top Deal"
    if score >= 60:
        return "tier-strong", "Strong"
    if score >= 45:
        return "tier-fair", "Fair"
    return "tier-weak", "Weak"


def _driver_pills(drivers: list[dict]) -> str:
    pills = []
    for d in drivers:
        kind = d.get("kind", "neutral")
        icon = {"positive": "▲", "negative": "▼", "neutral": "•"}.get(kind, "•")
        pills.append(
            f'<span class="pill pill-{_esc(kind)}">{icon} {_esc(d["label"])}</span>'
        )
    return "".join(pills)


def _breakdown_bars(breakdown: dict) -> str:
    rows = []
    for key in _SUB_ORDER:
        sub = breakdown.get(key, {})
        value = sub.get("value", 0)
        weight = int(round(sub.get("weight", 0) * 100))
        rows.append(f"""
            <div class="bar-row">
              <div class="bar-head">
                <span class="bar-label">{_esc(_SUB_LABELS[key])}
                  <span class="bar-weight">{weight}%</span></span>
                <span class="bar-value">{value:.0f}</span>
              </div>
              <div class="bar-track"><div class="bar-fill" style="width:{value:.0f}%"></div></div>
            </div>""")
    return "".join(rows)


def _card(listing: Listing, rank: int) -> str:
    tier_class, tier_label = _score_tier(listing.deal_score)
    bd = listing.score_breakdown

    all_drivers: list[dict] = []
    for key in _SUB_ORDER:
        all_drivers.extend(bd.get(key, {}).get("drivers", []))
    all_drivers.sort(key=lambda d: 0 if d.get("kind") != "neutral" else 1)

    rooms = f"{listing.rooms:g}" if listing.rooms else "–"
    title_html = _esc(listing.title)
    if listing.url:
        title_html = (f'<a href="{_esc(listing.url)}" target="_blank" '
                      f'rel="noopener">{title_html}</a>')

    cat_label = _CATEGORY_LABELS.get(listing.category, listing.category.title())
    days = listing.days_listed
    change = listing.price_change_pct

    # Small meta line: freshness + price change.
    meta_bits = [f'<span class="tag tag-cat">{_esc(cat_label)}</span>']
    if days is not None:
        fresh_cls = "tag-fresh" if days <= 7 else ("tag-stale" if days > 45 else "tag")
        meta_bits.append(f'<span class="tag {fresh_cls}">🕑 '
                         f'{"today" if days == 0 else f"{days}d listed"}</span>')
    if change is not None and change <= -0.5:
        meta_bits.append(f'<span class="tag tag-drop">💶 {change:.0f}% since listed</span>')
    elif change is not None and change >= 0.5:
        meta_bits.append(f'<span class="tag tag-up">💶 +{change:.0f}% since listed</span>')
    meta_html = "".join(meta_bits)

    # Data attributes drive the client-side filtering/sorting.
    search_blob = f"{listing.title} {listing.location} {listing.zip_code}".lower()
    data_attrs = (
        f'data-score="{listing.deal_score:.1f}" '
        f'data-price="{listing.price:.0f}" '
        f'data-size="{listing.size_sqm:.1f}" '
        f'data-rooms="{listing.rooms or 0:g}" '
        f'data-ppsqm="{listing.price_per_sqm:.0f}" '
        f'data-source="{_esc(listing.source)}" '
        f'data-category="{_esc(listing.category)}" '
        f'data-days="{days if days is not None else 9999}" '
        f'data-search="{_esc(search_blob)}"'
    )

    return f"""
    <article class="card {tier_class}" {data_attrs}>
      <div class="card-top">
        <div class="score-badge">
          <div class="score-num">{listing.deal_score:.0f}</div>
          <div class="score-lbl">{_esc(tier_label)}</div>
        </div>
        <div class="card-headings">
          <div class="rank">#<span class="rank-n">{rank}</span></div>
          <h2 class="card-title">{title_html}</h2>
          <div class="card-loc">📍 {_esc(listing.location) or "Unknown location"}
            {f'· {_esc(listing.zip_code)}' if listing.zip_code else ''}</div>
          <div class="card-meta">{meta_html}</div>
        </div>
      </div>

      <div class="metrics">
        <div class="metric"><span class="m-lbl">Price</span>
          <span class="m-val">{_fmt_eur(listing.price)}</span></div>
        <div class="metric"><span class="m-lbl">Size</span>
          <span class="m-val">{listing.size_sqm:g} m²</span></div>
        <div class="metric"><span class="m-lbl">Rooms</span>
          <span class="m-val">{rooms}</span></div>
        <div class="metric"><span class="m-lbl">Price/m²</span>
          <span class="m-val">{_fmt_eur(listing.price_per_sqm)}</span></div>
      </div>

      <div class="drivers">{_driver_pills(all_drivers)}</div>

      <details class="breakdown">
        <summary>Score breakdown</summary>
        <div class="bars">{_breakdown_bars(bd)}</div>
      </details>
    </article>"""


def _source_checkboxes(listings: list[Listing]) -> str:
    sources = sorted({l.source for l in listings})
    boxes = []
    for s in sources:
        boxes.append(
            f'<label class="chk"><input type="checkbox" class="f-source" '
            f'value="{_esc(s)}" checked> {_esc(s)}</label>'
        )
    return "".join(boxes)


def _barometer_panel(bar: Barometer) -> str:
    rec_class = {"BUY": "rec-buy", "NEUTRAL": "rec-neutral", "WAIT": "rec-wait"}[
        bar.recommendation]
    rec_word = {"BUY": "Buy", "NEUTRAL": "Selective", "WAIT": "Wait"}[
        bar.recommendation]
    pos = max(2.0, min(98.0, bar.heat))

    rows = []
    for s in bar.signals:
        dim = "" if s.get("active") else " sig-dim"
        rows.append(f"""
          <div class="sig{dim}">
            <div class="sig-top"><span class="sig-label">{_esc(s['label'])}</span>
              <span class="sig-heat">{s['heat']:.0f}</span></div>
            <div class="sig-track"><div class="sig-fill" style="width:{s['heat']:.0f}%"></div></div>
            <div class="sig-detail">{_esc(s['detail'])}</div>
          </div>""")

    median = _fmt_eur(bar.median_ppsqm)
    return f"""
    <section class="barometer">
      <div class="baro-main">
        <div class="baro-head">
          <span class="baro-title">Market Barometer</span>
          <span class="baro-conf">{_esc(bar.confidence)} confidence</span>
        </div>
        <div class="baro-verdict">
          <span class="rec-badge {rec_class}">{rec_word}</span>
          <div class="baro-verdict-text">
            <div class="baro-headline">{_esc(bar.headline)}</div>
            <div class="baro-sub">Price level: <b>{_esc(bar.price_level)}</b>
              · Median <b>{median}/m²</b> · Heat <b>{bar.heat:.0f}/100</b></div>
          </div>
        </div>
        <div class="gauge">
          <div class="gauge-bar"><div class="gauge-marker" style="left:{pos:.1f}%"></div></div>
          <div class="gauge-zones">
            <span>Buy</span><span>Balanced</span><span>Wait</span>
          </div>
        </div>
      </div>
      <div class="baro-signals">{''.join(rows)}</div>
    </section>"""


def render_html(listings: list[Listing], cfg: Config, barometer: Barometer) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(listings)
    scores = [l.deal_score for l in listings]
    avg_score = statistics.mean(scores) if scores else 0
    top_score = max(scores) if scores else 0
    med_ppsqm = (
        statistics.median([l.price_per_sqm for l in listings if l.price_per_sqm])
        if listings else 0
    )
    max_price = max((l.price for l in listings), default=cfg.max_price_limit)
    n_sources = len({l.source for l in listings})

    zip_scope = ", ".join(cfg.target_zip_codes) if cfg.target_zip_codes else "All areas"
    cards = "\n".join(_card(l, i + 1) for i, l in enumerate(listings))

    empty_state = "" if listings else """
      <div class="empty">No listings matched the current filters.
      Adjust <code>TARGET_ZIP_CODES</code> / <code>MAX_PRICE_LIMIT</code> and re-run.</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Real Estate Market Radar</title>
<style>
  :root {{
    --bg: #0d1117; --panel: #161b22; --panel-2: #1c2230;
    --border: #2a313c; --text: #e6edf3; --muted: #8b949e;
    --accent: #4f8cff; --good: #2ea043; --good-soft: #10331d;
    --bad: #f85149; --bad-soft: #3a1517; --neutral: #30363d;
    --elite: #ffd23f; --strong: #2ea043; --fair: #4f8cff; --weak: #6e7681;
    --amber: #d29922;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
    line-height: 1.5;
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  header.hero {{
    background: linear-gradient(160deg, #11151c 0%, #0d1117 100%);
    border-bottom: 1px solid var(--border);
    padding: 40px 24px 28px;
  }}
  .hero-inner {{ max-width: 1200px; margin: 0 auto; }}
  .hero h1 {{ margin: 0; font-size: 30px; letter-spacing: -0.5px; font-weight: 700; }}
  .hero .radar {{ color: var(--accent); }}
  .hero p.sub {{ margin: 6px 0 22px; color: var(--muted); font-size: 15px; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 14px; }}
  .stat {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 18px; min-width: 120px;
  }}
  .stat .n {{ font-size: 22px; font-weight: 700; }}
  .stat .l {{ font-size: 12px; color: var(--muted); text-transform: uppercase;
    letter-spacing: .5px; }}

  /* ---- Market barometer ---- */
  .barometer {{ display: grid; grid-template-columns: 1.15fr 1fr; gap: 22px;
    margin-top: 22px; background: var(--panel); border: 1px solid var(--border);
    border-radius: 14px; padding: 18px 20px; }}
  .baro-head {{ display: flex; justify-content: space-between; align-items: center; }}
  .baro-title {{ font-size: 13px; text-transform: uppercase; letter-spacing: .6px;
    color: var(--muted); font-weight: 700; }}
  .baro-conf {{ font-size: 11px; color: var(--muted); border: 1px solid var(--border);
    border-radius: 999px; padding: 2px 9px; }}
  .baro-verdict {{ display: flex; gap: 14px; align-items: center; margin: 14px 0 16px; }}
  .rec-badge {{ font-size: 20px; font-weight: 800; letter-spacing: .3px;
    padding: 10px 16px; border-radius: 12px; white-space: nowrap; }}
  .rec-buy {{ color: #7ee2a0; background: var(--good-soft); box-shadow: inset 0 0 0 2px var(--good); }}
  .rec-neutral {{ color: #f0c674; background: #3a2f12; box-shadow: inset 0 0 0 2px var(--amber); }}
  .rec-wait {{ color: #ff9c96; background: var(--bad-soft); box-shadow: inset 0 0 0 2px var(--bad); }}
  .baro-headline {{ font-size: 16px; font-weight: 650; }}
  .baro-sub {{ font-size: 13px; color: var(--muted); margin-top: 2px; }}
  .baro-sub b {{ color: var(--text); }}
  .gauge-bar {{ position: relative; height: 12px; border-radius: 999px;
    background: linear-gradient(90deg, #2ea043 0%, #d29922 52%, #f85149 100%); }}
  .gauge-marker {{ position: absolute; top: -4px; width: 4px; height: 20px;
    background: #fff; border-radius: 3px; transform: translateX(-50%);
    box-shadow: 0 0 0 2px rgba(0,0,0,.45); }}
  .gauge-zones {{ display: flex; justify-content: space-between; margin-top: 6px;
    font-size: 11px; color: var(--muted); }}
  .baro-signals {{ display: flex; flex-direction: column; gap: 10px;
    justify-content: center; }}
  .sig-dim {{ opacity: .5; }}
  .sig-top {{ display: flex; justify-content: space-between; font-size: 12.5px; }}
  .sig-label {{ color: var(--text); font-weight: 600; }}
  .sig-heat {{ color: var(--muted); font-weight: 700; }}
  .sig-track {{ height: 5px; background: var(--panel-2); border-radius: 4px;
    overflow: hidden; margin: 3px 0; }}
  .sig-fill {{ height: 100%; background: linear-gradient(90deg, #2ea043, #d29922, #f85149);
    border-radius: 4px; }}
  .sig-detail {{ font-size: 11.5px; color: var(--muted); }}
  @media (max-width: 720px) {{ .barometer {{ grid-template-columns: 1fr; }} }}

  /* ---- Filter bar ---- */
  .filters {{
    position: sticky; top: 0; z-index: 20;
    background: rgba(13,17,23,.92); backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
  }}
  .filters-inner {{ max-width: 1200px; margin: 0 auto; padding: 14px 24px;
    display: flex; flex-wrap: wrap; gap: 14px 20px; align-items: flex-end; }}
  .fgroup {{ display: flex; flex-direction: column; gap: 4px; }}
  .fgroup label.cap {{ font-size: 11px; text-transform: uppercase;
    letter-spacing: .5px; color: var(--muted); }}
  .filters input[type="text"], .filters input[type="number"], .filters select {{
    background: var(--panel-2); border: 1px solid var(--border); color: var(--text);
    border-radius: 8px; padding: 8px 10px; font-size: 14px; min-width: 120px;
  }}
  .filters input[type="text"] {{ min-width: 220px; }}
  .filters input[type="range"] {{ width: 150px; accent-color: var(--accent); }}
  .chk {{ font-size: 13px; color: var(--text); display: inline-flex;
    align-items: center; gap: 5px; margin-right: 10px; white-space: nowrap; }}
  .chk input {{ accent-color: var(--accent); }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 4px 0; align-items: center; }}
  .score-out {{ font-weight: 700; color: var(--accent); }}
  #reset {{ background: var(--panel-2); border: 1px solid var(--border);
    color: var(--text); border-radius: 8px; padding: 8px 14px; cursor: pointer;
    font-size: 13px; }}
  #reset:hover {{ border-color: var(--accent); }}
  .result-count {{ margin-left: auto; font-size: 13px; color: var(--muted);
    align-self: center; }}
  .result-count b {{ color: var(--text); }}

  main {{ max-width: 1200px; margin: 0 auto; padding: 22px 24px 60px; }}
  .grid {{ display: grid; gap: 18px;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }}

  .card {{ background: var(--panel); border: 1px solid var(--border);
    border-radius: 14px; padding: 18px; display: flex; flex-direction: column;
    gap: 14px; position: relative; overflow: hidden; }}
  .card.hidden {{ display: none; }}
  .card::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }}
  .card.tier-elite::before {{ background: var(--elite); }}
  .card.tier-strong::before {{ background: var(--strong); }}
  .card.tier-fair::before {{ background: var(--fair); }}
  .card.tier-weak::before {{ background: var(--weak); }}

  .card-top {{ display: flex; gap: 14px; align-items: flex-start; }}
  .score-badge {{ flex: 0 0 auto; width: 64px; height: 64px; border-radius: 12px;
    background: var(--panel-2); border: 1px solid var(--border);
    display: flex; flex-direction: column; align-items: center; justify-content: center; }}
  .tier-elite .score-badge {{ box-shadow: inset 0 0 0 2px var(--elite); }}
  .tier-strong .score-badge {{ box-shadow: inset 0 0 0 2px var(--strong); }}
  .tier-fair .score-badge {{ box-shadow: inset 0 0 0 2px var(--fair); }}
  .score-num {{ font-size: 26px; font-weight: 800; line-height: 1; }}
  .score-lbl {{ font-size: 10px; color: var(--muted); text-transform: uppercase;
    letter-spacing: .5px; margin-top: 3px; }}
  .card-headings {{ min-width: 0; }}
  .rank {{ font-size: 12px; color: var(--muted); font-weight: 600; }}
  .card-title {{ margin: 2px 0 4px; font-size: 16px; font-weight: 650; line-height: 1.3; }}
  .card-loc {{ font-size: 13px; color: var(--muted); }}
  .card-meta {{ margin-top: 6px; display: flex; flex-wrap: wrap; gap: 5px; }}
  .tag {{ font-size: 11px; padding: 2px 7px; border-radius: 6px;
    background: var(--panel-2); border: 1px solid var(--border); color: var(--muted); }}
  .tag-cat {{ color: var(--accent); border-color: #24406b; }}
  .tag-fresh {{ color: #7ee2a0; border-color: #1d5230; }}
  .tag-stale {{ color: #ff9c96; border-color: #5a2224; }}
  .tag-drop {{ color: #7ee2a0; border-color: #1d5230; }}
  .tag-up {{ color: #ff9c96; border-color: #5a2224; }}

  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
  .metric {{ background: var(--panel-2); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 6px; text-align: center; }}
  .m-lbl {{ display: block; font-size: 10px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .4px; }}
  .m-val {{ display: block; font-size: 14px; font-weight: 700; margin-top: 2px; }}

  .drivers {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .pill {{ font-size: 11.5px; padding: 3px 9px; border-radius: 999px;
    border: 1px solid var(--border); background: var(--panel-2); }}
  .pill-positive {{ color: #7ee2a0; background: var(--good-soft); border-color: #1d5230; }}
  .pill-negative {{ color: #ff9c96; background: var(--bad-soft); border-color: #5a2224; }}
  .pill-neutral {{ color: var(--muted); }}

  details.breakdown {{ border-top: 1px solid var(--border); padding-top: 10px; }}
  details.breakdown summary {{ cursor: pointer; font-size: 13px; color: var(--muted);
    user-select: none; }}
  details.breakdown summary:hover {{ color: var(--text); }}
  .bars {{ margin-top: 12px; display: flex; flex-direction: column; gap: 10px; }}
  .bar-head {{ display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }}
  .bar-label {{ color: var(--muted); }}
  .bar-weight {{ font-size: 10px; background: var(--neutral); color: var(--text);
    padding: 1px 5px; border-radius: 4px; margin-left: 4px; }}
  .bar-value {{ font-weight: 700; }}
  .bar-track {{ height: 6px; background: var(--panel-2); border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 100%; background: linear-gradient(90deg, var(--accent), #7ee2a0);
    border-radius: 4px; }}

  .empty, #no-results {{ text-align: center; color: var(--muted); padding: 60px 20px;
    border: 1px dashed var(--border); border-radius: 12px; }}
  #no-results {{ display: none; grid-column: 1 / -1; }}
  .empty code {{ background: var(--panel-2); padding: 2px 6px; border-radius: 4px; }}

  footer {{ max-width: 1200px; margin: 0 auto; padding: 20px 24px 50px;
    color: var(--muted); font-size: 12.5px; border-top: 1px solid var(--border); }}
  .methodology {{ margin-top: 8px; }}
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <h1>Real Estate <span class="radar">Market Radar</span></h1>
      <p class="sub">Holistic deal scoring across price, layout, affordability,
        momentum &amp; signals — best opportunities first.</p>
      <div class="stats">
        <div class="stat"><div class="n">{total}</div><div class="l">Listings</div></div>
        <div class="stat"><div class="n">{n_sources}</div><div class="l">Sources</div></div>
        <div class="stat"><div class="n">{top_score:.0f}</div><div class="l">Top Score</div></div>
        <div class="stat"><div class="n">{avg_score:.0f}</div><div class="l">Avg Score</div></div>
        <div class="stat"><div class="n">{_fmt_eur(med_ppsqm)}</div><div class="l">Median €/m²</div></div>
        <div class="stat"><div class="n">{_esc(zip_scope)}</div><div class="l">Scope</div></div>
      </div>
      {_barometer_panel(barometer)}
    </div>
  </header>

  <div class="filters">
    <div class="filters-inner">
      <div class="fgroup">
        <label class="cap" for="f-search">Search</label>
        <input type="text" id="f-search" placeholder="Title, location, ZIP…">
      </div>
      <div class="fgroup">
        <label class="cap">Sources</label>
        <div class="chips">{_source_checkboxes(listings)}</div>
      </div>
      <div class="fgroup">
        <label class="cap">Type</label>
        <div class="chips">
          <label class="chk"><input type="checkbox" class="f-cat" value="apartment" checked> Apartment</label>
          <label class="chk"><input type="checkbox" class="f-cat" value="house" checked> House</label>
        </div>
      </div>
      <div class="fgroup">
        <label class="cap" for="f-score">Min score <span class="score-out" id="score-out">0</span></label>
        <input type="range" id="f-score" min="0" max="100" value="0" step="1">
      </div>
      <div class="fgroup">
        <label class="cap" for="f-maxprice">Max price €</label>
        <input type="number" id="f-maxprice" placeholder="{max_price:.0f}" min="0" step="10000">
      </div>
      <div class="fgroup">
        <label class="cap" for="f-minsize">Min m²</label>
        <input type="number" id="f-minsize" placeholder="0" min="0" step="5">
      </div>
      <div class="fgroup">
        <label class="cap" for="f-minrooms">Min rooms</label>
        <select id="f-minrooms">
          <option value="0">Any</option><option value="1">1+</option>
          <option value="2">2+</option><option value="3">3+</option>
          <option value="4">4+</option><option value="5">5+</option>
        </select>
      </div>
      <div class="fgroup">
        <label class="cap" for="f-sort">Sort by</label>
        <select id="f-sort">
          <option value="score">Deal score ↓</option>
          <option value="price-asc">Price ↑</option>
          <option value="price-desc">Price ↓</option>
          <option value="ppsqm-asc">€/m² ↑</option>
          <option value="size-desc">Size ↓</option>
          <option value="days-asc">Newest</option>
        </select>
      </div>
      <button id="reset">Reset</button>
      <div class="result-count"><b id="shown">{total}</b> / {total} shown</div>
    </div>
  </div>

  <main>
    {empty_state}
    <div class="grid" id="grid">
      {cards}
      <div id="no-results">No listings match your filters. Try loosening them.</div>
    </div>
  </main>

  <footer>
    <div>Generated {now} · Sorted by Deal Score (desc) · Filtering runs entirely in your browser.</div>
    <div class="methodology">
      <strong>Deal Score</strong> = 40% price/m² discount vs. per-category regional median
      · 20% layout efficiency · 12% price sweet-spot · 12% price momentum (drops since listed)
      · 8% keyword signals · 8% freshness. Informational only — not investment advice.
    </div>
  </footer>

<script>
(function () {{
  var grid = document.getElementById('grid');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var noResults = document.getElementById('no-results');
  var shown = document.getElementById('shown');
  var $ = function (id) {{ return document.getElementById(id); }};

  var search = $('f-search'), scoreR = $('f-score'), scoreOut = $('score-out');
  var maxPrice = $('f-maxprice'), minSize = $('f-minsize'),
      minRooms = $('f-minrooms'), sortSel = $('f-sort');

  function checkedValues(cls) {{
    return Array.prototype.slice.call(document.querySelectorAll('.' + cls))
      .filter(function (c) {{ return c.checked; }})
      .map(function (c) {{ return c.value; }});
  }}

  function apply() {{
    var q = search.value.trim().toLowerCase();
    var minScore = parseFloat(scoreR.value) || 0;
    var maxP = parseFloat(maxPrice.value);
    var minS = parseFloat(minSize.value);
    var minR = parseFloat(minRooms.value) || 0;
    var srcs = checkedValues('f-source');
    var cats = checkedValues('f-cat');
    scoreOut.textContent = minScore;

    var visible = 0;
    cards.forEach(function (card) {{
      var d = card.dataset;
      var ok = true;
      if (q && d.search.indexOf(q) === -1) ok = false;
      if (ok && parseFloat(d.score) < minScore) ok = false;
      if (ok && !isNaN(maxP) && parseFloat(d.price) > maxP) ok = false;
      if (ok && !isNaN(minS) && parseFloat(d.size) < minS) ok = false;
      if (ok && parseFloat(d.rooms) < minR) ok = false;
      if (ok && srcs.indexOf(d.source) === -1) ok = false;
      if (ok && cats.indexOf(d.category) === -1) ok = false;
      card.classList.toggle('hidden', !ok);
      if (ok) visible++;
    }});

    shown.textContent = visible;
    noResults.style.display = visible === 0 ? 'block' : 'none';
    sortCards();
  }}

  function sortCards() {{
    var mode = sortSel.value;
    var vis = cards.filter(function (c) {{ return !c.classList.contains('hidden'); }});
    vis.sort(function (a, b) {{
      var da = a.dataset, db = b.dataset;
      switch (mode) {{
        case 'price-asc': return da.price - db.price;
        case 'price-desc': return db.price - da.price;
        case 'ppsqm-asc': return da.ppsqm - db.ppsqm;
        case 'size-desc': return db.size - da.size;
        case 'days-asc': return da.days - db.days;
        default: return db.score - da.score;
      }}
    }});
    vis.forEach(function (c, i) {{
      grid.appendChild(c);
      var rn = c.querySelector('.rank-n');
      if (rn) rn.textContent = i + 1;
    }});
    grid.appendChild(noResults);
  }}

  document.querySelectorAll('.filters input, .filters select').forEach(function (el) {{
    el.addEventListener('input', apply);
    el.addEventListener('change', apply);
  }});
  $('reset').addEventListener('click', function () {{
    search.value = ''; scoreR.value = 0; maxPrice.value = '';
    minSize.value = ''; minRooms.value = '0'; sortSel.value = 'score';
    document.querySelectorAll('.f-source, .f-cat').forEach(function (c) {{ c.checked = true; }});
    apply();
  }});

  apply();
}})();
</script>
</body>
</html>"""
