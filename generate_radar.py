#!/usr/bin/env python3
"""Real Estate Market Radar — entry point.

Runs the full pipeline: scrape -> clean -> persist -> score -> render the static
``index.html`` dashboard. All behaviour is controlled via environment variables
(see radar/config.py and the README).

Usage:
    python generate_radar.py
"""
from __future__ import annotations

import sys

from radar.config import Config
from radar.pipeline import run


def main() -> int:
    cfg = Config.from_env()
    try:
        run(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: {exc!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
