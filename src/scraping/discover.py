"""Discover each shop's PriceNow identifiers with Selenium.

    python -m src.scraping.discover            # every resort
    python -m src.scraping.discover laax       # just one
    python -m src.scraping.discover --show     # print the current cache

The shop's own front end makes the API call we want; we read the product id,
the channel uuid and the form state out of Chrome's performance log rather
than guessing them. Form state in particular must come from the shop itself:
one shop's does not satisfy another's product.

Two things make this fiddly. The performance log is a rolling buffer, so it
is drained at every checkpoint rather than read once at the end — on shops
whose calendar is inline, the request fires during page load and is long
gone by the time the page settles. And some shops default to a product that
has no date picker (an annual pass), so `pre_steps` in resorts.yaml says
what to click first.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from urllib.parse import parse_qs, urlparse

from .browser import (apply_pre_steps, count_calendar_cells, dismiss_cookies,
                      make_driver, open_calendar)
from .config import DATA_RAW, load_discovered, load_resorts, save_discovered

PAGE_SETTLE = 8.0
COOKIE_ATTEMPTS = 5


def _drain(driver, sink: list) -> None:
    """Pull everything currently in the performance log into `sink`.

    get_log() empties the buffer, so entries are only seen once.
    """
    try:
        sink.extend(driver.get_log("performance"))
    except Exception:
        pass

def _has_validities(entries: list) -> bool:
    return _extract_validities(entries)[0] is not None


def _settle_draining(driver, entries: list, seconds: float, step: float = 1.0) -> None:
    """Wait, draining the performance log as we go.

    The log is a rolling buffer: on shops whose calendar renders inline, the
    validities request fires within a second or two of load and is gone long
    before a single read at the end.
    """
    waited = 0.0
    while waited < seconds:
        time.sleep(step)
        waited += step
        _drain(driver, entries)

def _extract_validities(entries: list):
    """Product id, channel uuid and form state from the page's own GET.

    Scans newest-first: pre_steps change the selected product, so the last
    request reflects the final state. The first one may be for whatever
    product the page happened to load with.
    """
    for entry in reversed(entries):
        try:
            message = json.loads(entry["message"])["message"]
        except Exception:
            continue
        if message.get("method") != "Network.requestWillBeSent":
            continue
        request = message["params"]["request"]
        url = request["url"]
        if "journey/validities" not in url:
            continue
        if (request.get("method") or "").upper() != "GET":
            continue
        match = re.search(r"/products/(\d+)/", url)
        query = parse_qs(urlparse(url).query)
        headers = {k.lower(): v for k, v in request["headers"].items()}
        return (match.group(1) if match else None,
                headers.get("pratiq-channel-uuid"),
                query.get("formState", [None])[0])
    return None, None, None


def _nudge_calendar(driver) -> bool:
    """Click the month-forward arrow to force a fresh validities request."""
    from .dom import find_next_arrow
    from .browser import robust_click
    button, disabled = find_next_arrow(driver)
    if button is None or disabled:
        return False
    try:
        robust_click(driver, button)
        time.sleep(3)
        return True
    except Exception:
        return False


def discover_one(key: str, cfg: dict, headless: bool = True,
                 verbose: bool = True) -> dict:
    """Open one shop and capture what the daily collector needs."""
    result = {
        "resort": cfg.get("name", key),
        "url": cfg["url"],
        "cantons": cfg.get("cantons"),
        "product_id": None,
        "channel_uuid": None,
        "api_version": None,
        "form_state": None,
        "layout": None,
        "pre_steps_done": [],
        "n_cells": 0,
        "discovered_at": None,
        "error": None,
    }
    entries: list = []
    driver = make_driver(headless=headless, perf_log=True)
    try:
        driver.get(cfg["url"])
        _settle_draining(driver, entries, PAGE_SETTLE)

        for _ in range(COOKIE_ATTEMPTS):
            if dismiss_cookies(driver):
                break
            _settle_draining(driver, entries, 3.0)
        _settle_draining(driver, entries, 2.0)

        try:
            result["pre_steps_done"] = apply_pre_steps(driver, cfg.get("pre_steps"))
        except Exception as exc:
            result["error"] = f"pre-step failed: {exc}"
        _settle_draining(driver, entries, 2.0)

        if not result["error"]:
            result["layout"] = open_calendar(driver)
            _settle_draining(driver, entries, 3.0)

            if result["layout"] is None:
                result["error"] = ("no calendar found — category page, or needs a "
                                   "pre_step to select the right product")
            else:
                result["n_cells"] = count_calendar_cells(driver)
                pid, uuid, form = _extract_validities(entries)

                if not (pid and uuid and form) and _nudge_calendar(driver):
                    _settle_draining(driver, entries, 3.0)
                    pid, uuid, form = _extract_validities(entries)

                result.update(product_id=pid, channel_uuid=uuid, form_state=form)
                if not (pid and uuid and form):
                    missing = [n for n, v in (("product_id", pid),
                                              ("channel_uuid", uuid),
                                              ("form_state", form)) if not v]
                    result["error"] = (f"validities GET not captured "
                                       f"(missing: {', '.join(missing)})")
                else:
                    result["discovered_at"] = (dt.datetime.now().astimezone()
                                               .isoformat(timespec="seconds"))

        if result["error"]:
            DATA_RAW.mkdir(parents=True, exist_ok=True)
            shot = DATA_RAW / f"discover_fail_{key}.png"
            driver.save_screenshot(str(shot))
            result["screenshot"] = shot.name
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if verbose:
        print(f"{key:14} layout={result['layout']}  product={result['product_id']}  "
              f"cells={result['n_cells']}  steps={result['pre_steps_done']}  "
              f"{result['error'] or 'ok'}")
    return result


def discover(keys=None, headless: bool = True) -> dict:
    """Discover the given resorts (all of them by default) and update the cache."""
    resorts = load_resorts()
    if keys:
        unknown = [k for k in keys if k not in resorts]
        if unknown:
            raise SystemExit(f"unknown resort(s) in resorts.yaml: {unknown}")
        resorts = {k: resorts[k] for k in keys}

    cache = load_discovered()
    for key, cfg in resorts.items():
        found = discover_one(key, cfg, headless=headless)
        if found["error"]:
            print(f"  keeping previous entry for {key}" if key in cache else
                  f"  no entry for {key}", file=sys.stderr)
            continue
        cache[key] = found

    path = save_discovered(cache)
    print(f"\nwrote {path.name} ({len(cache)} resorts)")
    return cache


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover PriceNow shop identifiers.")
    parser.add_argument("resorts", nargs="*", help="keys from resorts.yaml; omit for all")
    parser.add_argument("--show", action="store_true", help="print the cache and exit")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    args = parser.parse_args()

    if args.show:
        print(json.dumps(load_discovered(), indent=2, sort_keys=True))
        return

    discover(args.resorts or None, headless=not args.headed)


if __name__ == "__main__":
    main()