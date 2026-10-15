"""Daily price collection. Pure HTTP — no browser needed.

    python -m src.scraping.collect
    python -m src.scraping.collect --resorts laax titlis

Writes, per run:
  data/raw/<resort>_<stamp>.json   the API response, verbatim and immutable
  data/raw/prices_<stamp>.csv      the parsed day passes for all resorts

Raw responses are never modified. Everything downstream is rebuilt from them,
so a parser fix can be applied retrospectively to the whole collection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import pandas as pd

from .config import (DATA_RAW, SEASON_END, SEASON_START, load_discovered,
                     load_resorts, save_discovered)
from .pricenow import (PriceNowError, build_headers, day_passes,
                       fetch_validities, parse_validities)


def collect_one(key: str, cfg: dict, found: dict, stamp: str,
                observed_at: str) -> pd.DataFrame:
    """Fetch and parse one resort's season. Raises PriceNowError on refusal."""
    headers = build_headers(
        shop_url=cfg["url"],
        channel_uuid=found["channel_uuid"],
        api_version=found.get("api_version") or "2025-02-18",
    )
    payload = fetch_validities(
        product_id=found["product_id"],
        headers=headers,
        form_state=found["form_state"],
        start=SEASON_START,
        end=SEASON_END,
    )

    DATA_RAW.mkdir(parents=True, exist_ok=True)
    (DATA_RAW / f"{key}_{stamp}.json").write_text(json.dumps(payload), encoding="utf-8")

    return parse_validities(payload, cfg.get("name", key), observed_at)


def collect(keys=None, rediscover: bool = True) -> pd.DataFrame:
    """Collect every configured resort. Re-discovers once if the API refuses."""
    resorts = load_resorts()
    found_all = load_discovered()
    if keys:
        resorts = {k: v for k, v in resorts.items() if k in keys}

    observed = dt.datetime.now().astimezone()
    stamp = f"{observed:%Y%m%d_%H%M}"
    observed_at = observed.isoformat(timespec="seconds")

    frames, failures = [], {}
    for key, cfg in resorts.items():
        found = found_all.get(key)
        if not found:
            failures[key] = "not discovered — run src.scraping.discover"
            continue
        try:
            frames.append(collect_one(key, cfg, found, stamp, observed_at))
            print(f"{key:14} ok")
        except PriceNowError as exc:
            if not rediscover:
                failures[key] = str(exc)
                continue
            # Channel uuids and product ids rotate. Refresh once, then retry.
            print(f"{key:14} refused ({exc}) — rediscovering", file=sys.stderr)
            from .discover import discover_one
            refreshed = discover_one(key, cfg, headless=True, verbose=False)
            if refreshed["error"]:
                failures[key] = f"rediscovery failed: {refreshed['error']}"
                continue
            found_all[key] = refreshed
            save_discovered(found_all)
            try:
                frames.append(collect_one(key, cfg, refreshed, stamp, observed_at))
                print(f"{key:14} ok (after rediscovery)")
            except PriceNowError as exc2:
                failures[key] = f"still refused after rediscovery: {exc2}"

    for key, reason in failures.items():
        print(f"{key:14} FAILED — {reason}", file=sys.stderr)
    if not frames:
        raise SystemExit("no resort returned data")

    everything = pd.concat(frames, ignore_index=True)
    passes = day_passes(everything)

    out_path = DATA_RAW / f"prices_{stamp}.csv"
    passes.to_csv(out_path, index=False)
    print(f"\n{len(passes)} day-pass rows across {passes['resort'].nunique()} "
          f"resorts -> {out_path.name}")
    return passes


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect PriceNow day-pass prices.")
    parser.add_argument("--resorts", nargs="*", help="keys from resorts.yaml; omit for all")
    parser.add_argument("--no-rediscover", action="store_true",
                        help="fail instead of refreshing stale identifiers")
    args = parser.parse_args()
    collect(args.resorts or None, rediscover=not args.no_rediscover)


if __name__ == "__main__":
    main()