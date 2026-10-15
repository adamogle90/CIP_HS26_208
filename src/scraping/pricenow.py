"""Client and parser for the PriceNow booking API.

Every shop in the sample runs on PriceNow, so one client serves all of them.
What differs per shop is the product id, the channel uuid and the form state —
all of which are discovered by `discover.py` and cached.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

import pandas as pd
import requests

from .config import USER_AGENT

VALIDITIES_URL = "https://api.pricenow.dev/api/booking/products/{pid}/journey/validities"
DEFAULT_API_VERSION = "2025-02-18"


class PriceNowError(RuntimeError):
    """Raised when the API answers but refuses the request."""


def build_headers(shop_url: str, channel_uuid: str,
                  api_version: str = DEFAULT_API_VERSION) -> dict:
    """Minimal headers the API accepts.

    `pratiq-channel-uuid` is the one that matters — without it the API returns
    400 NO_CHANNEL_UUID_FOUND. The rest mirror what the shop's front end sends.
    """
    parts = urlparse(shop_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    return {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "accept-language": "en",
        "content-type": "application/json",
        "pratiq-channel-uuid": channel_uuid,
        "pratiq-api-version": api_version,
        "pratiq-superjson": "true",
        "Origin": origin,
        "Referer": origin + "/",
    }


def fetch_validities(product_id: str, headers: dict, form_state: str,
                     start: str, end: str, timeout: int = 30,
                     pause: float = 1.0) -> dict:
    """One request returns the whole season. start/end are 'YYYY-MM-DD'."""
    params = {
        "from": f"{start}T00:00:00.000+01:00",
        "to": f"{end}T23:59:59.999+01:00",
        "formState": form_state,
    }
    response = requests.get(VALIDITIES_URL.format(pid=product_id),
                            params=params, headers=headers, timeout=timeout)
    time.sleep(pause)
    if response.status_code != 200:
        raise PriceNowError(f"HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


def parse_validities(payload: dict, resort: str, observed_at: str) -> pd.DataFrame:
    """Flatten the API response into one row per (date, duration).

    Prices arrive in centimes. `duration_days` is derived from the validity
    window rather than the label, because labels are localised and
    inconsistent across shops.
    """
    try:
        options = payload["json"]["data"]["options"]
    except (KeyError, TypeError) as exc:
        raise PriceNowError(f"unexpected response shape: {exc}") from exc

    rows = []
    for option in options:
        start = pd.to_datetime(option["value"]["from"], utc=True).tz_convert("Europe/Zurich")
        end = pd.to_datetime(option["value"]["to"], utc=True).tz_convert("Europe/Zurich")
        price = option.get("price") or {}
        low, high = price.get("minPrice"), price.get("maxPrice")
        rows.append({
            "resort": resort,
            "date": start.normalize().tz_localize(None),
            "duration_days": int(round((end - start).total_seconds() / 86400)),
            "label": option.get("label"),
            "is_available": option.get("isAvailable"),
            "capacity_kind": (option.get("availableCapacity") or {}).get("kind"),
            "price_chf": None if low is None else low / 100,
            "max_price_chf": None if high is None else high / 100,
            "observed_at": observed_at,
        })
    return pd.DataFrame(rows)


def day_passes(frame: pd.DataFrame) -> pd.DataFrame:
    """The single-day rows, which are what the research questions use."""
    return (frame[frame["duration_days"] == 1]
            .sort_values(["resort", "date"])
            .reset_index(drop=True))