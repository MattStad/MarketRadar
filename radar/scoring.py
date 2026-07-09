"""The multi-factor Deal Score engine (0 - 100).

A property is *never* ranked by price-per-sqm alone. The final score is a
weighted blend of four independent sub-scores, each of which also emits a set of
human-readable "drivers" that explain *why* a listing scored the way it did.

    deal_score = 0.40 * discount      # €/m² vs. per-category regional median
               + 0.20 * layout        # room / space efficiency
               + 0.12 * sweet_spot    # absolute entry price
               + 0.12 * momentum      # price drop since first listed
               + 0.08 * soft_flags    # keyword signals
               + 0.08 * freshness     # how recently it appeared
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable, Optional

from .config import Config
from .models import Listing


WEIGHTS = {
    "discount": 0.40,
    "layout": 0.20,
    "sweet_spot": 0.12,
    "momentum": 0.12,
    "soft_flags": 0.08,
    "freshness": 0.08,
}

# Keyword -> (points, label). Positive points reward, negative penalize.
POSITIVE_KEYWORDS = {
    "provisionsfrei": (18, "Provisionsfrei (no agent fee)"),
    "provisionsfreier": (18, "Provisionsfrei (no agent fee)"),
    "terrasse": (14, "Terrace"),
    "balkon": (12, "Balcony"),
    "loggia": (10, "Loggia"),
    "garten": (12, "Garden"),
    "gute anbindung": (10, "Good transit connection"),
    "u-bahn": (8, "Near subway"),
    "erstbezug": (10, "First occupancy / new build"),
    "saniert": (8, "Renovated / refurbished"),
    "garage": (8, "Garage / parking"),
    "tiefgarage": (8, "Underground parking"),
    "ruhelage": (6, "Quiet location"),
    "hell": (4, "Bright / lots of light"),
}

NEGATIVE_KEYWORDS = {
    "renovierungsbedürftig": (-22, "Needs renovation"),
    "sanierungsbedürftig": (-22, "Needs refurbishment"),
    "sanierungsbedarf": (-18, "Refurbishment needed"),
    "renovierungsbedarf": (-18, "Renovation needed"),
    "befristet vermietet": (-18, "Tenanted (fixed-term lease)"),
    "vermietet": (-10, "Currently tenanted"),
    "abrissreif": (-30, "Teardown condition"),
    "abbruch": (-30, "Teardown / demolition"),
    "rohbau": (-20, "Shell / unfinished build"),
    "bauland": (-18, "Building plot (not a home)"),
    "zinshaus": (-16, "Tenement block (investment)"),
    "anlageobjekt": (-12, "Pure investment object"),
    "sanierungsobjekt": (-16, "Fixer-upper project"),
    "bastler": (-16, "For DIY / handyman"),
    "reserviert": (-25, "Reserved"),
    "erbpacht": (-14, "Leasehold (Erbpacht)"),
    "reparaturbedarf": (-12, "Repairs needed"),
    "hochparterre": (-4, "Raised ground floor"),
    "souterrain": (-8, "Basement level"),
}

# Severe issues cap the *final* deal score no matter how cheap the property is.
# (keyword substrings, cap value, human label)
HARD_CAPS = [
    (42, ["abbruch", "abrissreif", "abbruchreif", "abbruchobjekt", "rohbau",
          "bauland", "baugrund", "zwangsversteigerung", "versteigerung",
          "rohdachboden", "sanierungsobjekt"],
     "Teardown / plot / shell"),
    (48, ["reserviert", "bereits verkauft", "verkauft!"],
     "Reserved / already sold"),
    (58, ["renovierungsbedürftig", "sanierungsbedürftig", "reparaturbedürftig",
          "sanierungsbedarf", "renovierungsbedarf", "bastler"],
     "Needs major renovation"),
    (62, ["zinshaus", "anlageobjekt", "gewerbe", "büro", "geschäftslokal"],
     "Commercial / investment object"),
]


def hard_cap(listing: Listing) -> tuple[float, str]:
    """Return the lowest applicable score cap and its reason ('' if none)."""
    hay = f"{listing.title}\n{listing.description}".lower()
    best_cap = 100.0
    reason = ""
    for cap, kws, label in HARD_CAPS:
        if any(k in hay for k in kws) and cap < best_cap:
            best_cap = cap
            reason = label
    return best_cap, reason


@dataclass
class SubScore:
    value: float                       # 0 - 100
    drivers: list[dict]                # [{"label": str, "kind": "positive"|...}]


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# 1. Price-per-sqm discount vs. the regional median (weight 50%)
# --------------------------------------------------------------------------- #
def compute_district_medians(
    baseline: Iterable[Listing], min_samples: int = 6
) -> tuple[dict[str, float], float]:
    """Return ``(medians_by_district, global_median)`` for price-per-sqm.

    Districts with fewer than ``min_samples`` observations fall back to the
    global median at scoring time so a single outlier can't define a region.
    """
    by_district: dict[str, list[float]] = {}
    by_category: dict[str, list[float]] = {}
    all_ppsqm: list[float] = []
    for lst in baseline:
        if lst.price_per_sqm and lst.price_per_sqm > 0:
            by_district.setdefault(lst.median_key, []).append(lst.price_per_sqm)
            by_category.setdefault(lst.category, []).append(lst.price_per_sqm)
            all_ppsqm.append(lst.price_per_sqm)

    global_median = statistics.median(all_ppsqm) if all_ppsqm else 0.0
    medians = {
        key: statistics.median(vals)
        for key, vals in by_district.items()
        if len(vals) >= min_samples
    }
    # Per-category fallback (e.g. all houses) — better than a mixed global
    # median when a specific district lacks enough samples.
    for cat, vals in by_category.items():
        if len(vals) >= min_samples:
            medians[f"__cat__:{cat}"] = statistics.median(vals)
    return medians, global_median


def score_discount(
    listing: Listing,
    medians: dict[str, float],
    global_median: float,
) -> SubScore:
    # Prefer the per-category district median (reliable), then per-category,
    # then global. Only a real *local* sample counts as high-confidence.
    reliable = listing.median_key in medians
    if reliable:
        reference = medians[listing.median_key]
        ref_label = "district"
    elif f"__cat__:{listing.category}" in medians:
        reference = medians[f"__cat__:{listing.category}"]
        ref_label = "regional"
    else:
        reference = global_median
        ref_label = "regional"
    drivers: list[dict] = []

    if not reference or not listing.price_per_sqm:
        return SubScore(50.0, [{"label": "No regional benchmark available",
                                "kind": "neutral"}])

    # Positive discount => cheaper than the region.
    discount = (reference - listing.price_per_sqm) / reference

    # Map a discount range of [-25%, +40%] onto [0, 100]; 0% discount -> ~38.
    value = _clamp((discount + 0.25) / 0.65 * 100.0)

    # Confidence damping: without a real local benchmark, a low €/m² usually
    # just means a cheaper *area* (e.g. a rural house), not a genuine bargain.
    # Pull the score toward neutral and cap the upside so such listings can't
    # dominate the ranking on a fake discount.
    if not reliable:
        value = 50.0 + (value - 50.0) * 0.4
        value = min(value, 66.0)

    pct = discount * 100
    conf = "" if reliable else " (broad benchmark)"
    if discount >= 0.20:
        drivers.append({"label": f"{pct:+.0f}% below {ref_label} median €/m²{conf}",
                        "kind": "positive" if reliable else "neutral"})
    elif discount >= 0.05:
        drivers.append({"label": f"{pct:+.0f}% under {ref_label} median €/m²{conf}",
                        "kind": "positive" if reliable else "neutral"})
    elif discount <= -0.10:
        drivers.append({"label": f"{pct:+.0f}% vs {ref_label} median €/m²",
                        "kind": "negative"})
    else:
        drivers.append({"label": f"Around the {ref_label} median €/m²",
                        "kind": "neutral"})

    drivers.append({
        "label": f"€{listing.price_per_sqm:,.0f}/m² vs €{reference:,.0f}/m² median",
        "kind": "neutral",
    })
    return SubScore(value, drivers)


# --------------------------------------------------------------------------- #
# 2. Layout & room efficiency (weight 25%)
# --------------------------------------------------------------------------- #
def score_layout(listing: Listing) -> SubScore:
    """Reward space-efficient, practical floor plans.

    We look at both the room density (rooms per m²) and a couple of concrete
    "good layout" heuristics, then penalize clearly wasteful partitions.
    """
    if not listing.rooms or listing.rooms <= 0:
        return SubScore(50.0, [{"label": "Room count unknown", "kind": "neutral"}])

    rooms = listing.rooms
    size = listing.size_sqm
    sqm_per_room = size / rooms
    drivers: list[dict] = []

    # Ideal ~22-30 m² per room. Score peaks in that band and tapers off.
    if 22 <= sqm_per_room <= 30:
        value = 85.0
    elif sqm_per_room < 22:
        # Very tight — still efficient but can feel cramped.
        value = 70.0
    else:
        # Larger rooms are fine but less "efficient" per our brief.
        # 30 m²/room -> 70, 60 m²/room -> ~15.
        value = _clamp(70.0 - (sqm_per_room - 30) * 1.8)

    # Concrete bonus cases from the brief.
    if rooms >= 3 and size < 70:
        value += 15
        drivers.append({"label": f"Efficient {rooms:g}-room under 70 m²",
                        "kind": "positive"})
    elif rooms >= 2 and size < 48:
        value += 12
        drivers.append({"label": f"Compact {rooms:g}-room under 48 m²",
                        "kind": "positive"})
    elif rooms == 1 and size > 55:
        value -= 20
        drivers.append({"label": f"Oversized 1-room ({size:g} m²) — poor partition",
                        "kind": "negative"})

    value = _clamp(value)

    if not drivers:
        if 22 <= sqm_per_room <= 30:
            drivers.append({"label": f"Balanced layout (~{sqm_per_room:.0f} m²/room)",
                            "kind": "positive"})
        elif sqm_per_room > 40:
            drivers.append({"label": f"Sprawling rooms (~{sqm_per_room:.0f} m²/room)",
                            "kind": "negative"})
        else:
            drivers.append({"label": f"~{sqm_per_room:.0f} m² per room",
                            "kind": "neutral"})
    return SubScore(value, drivers)


# --------------------------------------------------------------------------- #
# 3. Absolute price sweet-spot (weight 15%)
# --------------------------------------------------------------------------- #
def score_sweet_spot(listing: Listing, cfg: Config) -> SubScore:
    """Reward low absolute entry prices (less capital / leverage needed)."""
    sweet = cfg.price_sweet_spot
    ceiling = cfg.max_price_limit
    price = listing.price

    if price <= sweet:
        # Progressive boost: cheaper than the sweet spot => full marks, with a
        # small extra kicker for genuinely low entry prices.
        floor = sweet * 0.4
        if price <= floor:
            value = 100.0
        else:
            value = _clamp(100.0 - (price - floor) / (sweet - floor) * 15.0)
        drivers = [{"label": f"Entry-level price €{price:,.0f} (≤ sweet spot)",
                    "kind": "positive"}]
    else:
        # Linear taper from the sweet spot down to 0 at the ceiling.
        span = max(ceiling - sweet, 1)
        value = _clamp(85.0 * (1 - (price - sweet) / span))
        kind = "neutral" if value >= 45 else "negative"
        drivers = [{"label": f"Above sweet spot (€{price:,.0f})", "kind": kind}]
    return SubScore(value, drivers)


# --------------------------------------------------------------------------- #
# 4. Soft flags / keyword parsing (weight 10%)
# --------------------------------------------------------------------------- #
def score_soft_flags(listing: Listing) -> SubScore:
    haystack = f"{listing.title}\n{listing.description}".lower()
    value = 50.0
    drivers: list[dict] = []
    seen: set[str] = set()

    for kw, (pts, label) in POSITIVE_KEYWORDS.items():
        if kw in haystack and label not in seen:
            value += pts
            seen.add(label)
            drivers.append({"label": label, "kind": "positive"})

    for kw, (pts, label) in NEGATIVE_KEYWORDS.items():
        if kw in haystack and label not in seen:
            value += pts  # pts already negative
            seen.add(label)
            drivers.append({"label": label, "kind": "negative"})

    if not drivers:
        drivers.append({"label": "No standout keywords", "kind": "neutral"})
    return SubScore(_clamp(value), drivers)


# --------------------------------------------------------------------------- #
# 5. Price momentum — reward drops since first listed (weight 12%)
# --------------------------------------------------------------------------- #
def score_momentum(listing: Listing) -> SubScore:
    change = listing.price_change_pct
    if change is None:
        # No history yet (first time we've seen it).
        return SubScore(50.0, [{"label": "No price history yet",
                                "kind": "neutral"}])
    if change <= -0.5:
        drop = -change
        # A 15%+ drop maxes the sub-score.
        value = _clamp(60.0 + drop / 15.0 * 40.0)
        return SubScore(value, [{"label": f"Price dropped {drop:.0f}% since listed",
                                 "kind": "positive"}])
    if change >= 0.5:
        value = _clamp(45.0 - change)
        return SubScore(value, [{"label": f"Price raised {change:.0f}% since listed",
                                 "kind": "negative"}])
    return SubScore(55.0, [{"label": "Stable price", "kind": "neutral"}])


# --------------------------------------------------------------------------- #
# 6. Freshness — how recently the listing appeared (weight 8%)
# --------------------------------------------------------------------------- #
def score_freshness(listing: Listing) -> SubScore:
    days = listing.days_listed
    if days is None:
        return SubScore(60.0, [{"label": "New to the radar", "kind": "neutral"}])
    if days <= 2:
        return SubScore(95.0, [{"label": "Fresh listing (≤2 days)", "kind": "positive"}])
    if days <= 7:
        return SubScore(80.0, [{"label": f"Listed {days} days ago", "kind": "positive"}])
    if days <= 21:
        return SubScore(60.0, [{"label": f"Listed {days} days ago", "kind": "neutral"}])
    if days <= 45:
        return SubScore(45.0, [{"label": f"On market {days} days", "kind": "neutral"}])
    return SubScore(30.0, [{"label": f"Stale — {days} days on market",
                            "kind": "negative"}])


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def score_listing(
    listing: Listing,
    cfg: Config,
    medians: dict[str, float],
    global_median: float,
) -> Listing:
    subs = {
        "discount": score_discount(listing, medians, global_median),
        "layout": score_layout(listing),
        "sweet_spot": score_sweet_spot(listing, cfg),
        "momentum": score_momentum(listing),
        "soft_flags": score_soft_flags(listing),
        "freshness": score_freshness(listing),
    }
    total = sum(WEIGHTS[name] * sub.value for name, sub in subs.items())

    listing.score_breakdown = {
        name: {
            "value": round(sub.value, 1),
            "weight": WEIGHTS[name],
            "contribution": round(WEIGHTS[name] * sub.value, 1),
            "drivers": sub.drivers,
        }
        for name, sub in subs.items()
    }

    # Severe red flags cap the final score regardless of how cheap it is.
    cap, reason = hard_cap(listing)
    if total > cap:
        total = cap
        listing.score_breakdown["soft_flags"]["drivers"].insert(
            0, {"label": f"{reason} — score capped at {cap:.0f}", "kind": "negative"})

    listing.deal_score = round(total, 1)
    return listing


def score_all(
    candidates: list[Listing],
    baseline: list[Listing],
    cfg: Config,
) -> list[Listing]:
    """Score every candidate and return them sorted best-first."""
    medians, global_median = compute_district_medians(baseline)
    for listing in candidates:
        score_listing(listing, cfg, medians, global_median)
    candidates.sort(key=lambda l: l.deal_score, reverse=True)
    return candidates
