"""Market barometer — a heuristic "buy vs. wait" gauge.

Given the scored listings (and the price history the store accumulates over
time), it derives a single *Market Heat* score (0-100) and a buy/wait
recommendation. Higher heat = pricier / seller's market (lean toward waiting);
lower heat = buyer's market (good time to buy).

It is deliberately transparent: every input signal is reported so the reader can
see *why*. It is a heuristic on listing data, **not** financial advice.

Signals (each expressed 0-100, higher = hotter / more expensive):
  * valuation  — current median €/m² vs. a configured fair-value reference
                 (only if FAIR_PPSQM is set)
  * trend      — are asking prices being cut or raised (from price history)
  * deals      — density of attractive below-market deals (inverse)
  * liquidity  — how fast the market is turning over (freshness)
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .config import Config
from .models import Listing


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Barometer:
    heat: float                       # 0-100, higher = hotter / pricier
    recommendation: str               # "BUY" | "NEUTRAL" | "WAIT"
    headline: str                     # short human verdict
    price_level: str                  # "low" | "moderate" | "elevated" | "high"
    confidence: str                   # "low" | "medium" | "high"
    median_ppsqm: float
    signals: list[dict] = field(default_factory=list)  # {label,detail,heat,active}


def compute_barometer(listings: list[Listing], cfg: Config) -> Barometer:
    ppsqm = [l.price_per_sqm for l in listings if l.price_per_sqm > 0]
    median_ppsqm = statistics.median(ppsqm) if ppsqm else 0.0
    n = len(listings)

    signals: list[dict] = []
    parts: list[tuple[float, float]] = []  # (heat, weight)

    # --- 1) Valuation vs. fair-value reference (optional) -------------------
    fair = cfg.fair_ppsqm
    if fair and median_ppsqm:
        dev = (median_ppsqm / fair - 1.0)  # +0.10 = 10% above reference
        val_heat = _clamp(50 + dev * 250)
        signals.append({
            "label": "Valuation vs. reference",
            "detail": f"Median €{median_ppsqm:,.0f}/m² is {dev*100:+.0f}% "
                      f"vs. €{fair:,.0f}/m² reference",
            "heat": val_heat, "active": True,
        })
        parts.append((val_heat, 0.35))

    # --- 2) Price trend / momentum (needs history) -------------------------
    changes = [l.price_change_pct for l in listings if l.price_change_pct is not None]
    max_days = max((l.days_listed or 0) for l in listings) if listings else 0
    has_history = max_days >= 2 and len(changes) >= max(5, n * 0.05)
    if has_history and changes:
        mean_change = statistics.mean(changes)
        cuts = sum(1 for c in changes if c <= -0.5)
        trend_heat = _clamp(50 + mean_change * 10)
        signals.append({
            "label": "Asking-price trend",
            "detail": (f"{cuts}/{len(changes)} tracked listings cut their price; "
                       f"avg change {mean_change:+.1f}%"),
            "heat": trend_heat, "active": True,
        })
        parts.append((trend_heat, 0.30))
    else:
        signals.append({
            "label": "Asking-price trend",
            "detail": "Builds as the tool re-runs and accumulates price history",
            "heat": 50, "active": False,
        })

    # --- 3) Deal density (inverse: more deals => cooler/buy-friendly) -------
    if n:
        strong = sum(1 for l in listings if l.deal_score >= 65)
        p = strong / n
        deal_heat = _clamp(50 + (0.15 - p) * 200)
        signals.append({
            "label": "Deal availability",
            "detail": f"{strong} of {n} listings ({p*100:.0f}%) score as strong "
                      f"deals (≥65)",
            "heat": deal_heat, "active": True,
        })
        parts.append((deal_heat, 0.25))

    # --- 4) Liquidity / turnover (needs freshness history) -----------------
    dated = [l.days_listed for l in listings if l.days_listed is not None]
    if has_history and dated:
        fresh = sum(1 for d in dated if d <= 7)
        f = fresh / len(dated)
        liq_heat = _clamp(30 + f * 120)
        signals.append({
            "label": "Market turnover",
            "detail": f"{f*100:.0f}% of listings appeared in the last 7 days",
            "heat": liq_heat, "active": True,
        })
        parts.append((liq_heat, 0.10))
    else:
        signals.append({
            "label": "Market turnover",
            "detail": "Builds as the tool re-runs and observes how long listings stay",
            "heat": 50, "active": False,
        })

    # --- Blend -------------------------------------------------------------
    if parts:
        total_w = sum(w for _, w in parts)
        heat = sum(h * w for h, w in parts) / total_w
    else:
        heat = 50.0
    heat = round(_clamp(heat), 1)

    # Confidence: more active signals (esp. history/valuation) => higher.
    active = sum(1 for s in signals if s["active"])
    confidence = "high" if active >= 3 else ("medium" if active == 2 else "low")

    if heat < 42:
        rec, headline = "BUY", "Buyer's market — a good window to buy"
    elif heat <= 60:
        rec, headline = "NEUTRAL", "Balanced market — buy selectively"
    else:
        rec, headline = "WAIT", "Seller's market — prices elevated, consider waiting"

    if heat < 35:
        level = "low"
    elif heat < 55:
        level = "moderate"
    elif heat < 70:
        level = "elevated"
    else:
        level = "high"

    return Barometer(
        heat=heat, recommendation=rec, headline=headline, price_level=level,
        confidence=confidence, median_ppsqm=median_ppsqm, signals=signals,
    )
