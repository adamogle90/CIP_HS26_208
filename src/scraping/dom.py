"""Scrape the rendered price calendar from the DOM.

This is the validation path, not the collection path. It exists to
cross-check the API, and because it is how the dynamic element of the
booking widget is actually exercised.

Known defect in the rendered calendar: the cell adjacent to the
pre-selected date shows the marginal "additional day" price rather than the
standalone day price. The API does not have this problem.
"""
from __future__ import annotations

import re
import time

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from .browser import robust_click

CELL_TEXT_RE = re.compile(r"^(\d{1,2})\s+(\d{1,3}[.,]\d{2})$")
COLUMNS = ["date", "price_chf", "raw_text", "classes", "disabled"]

PADDING_CLASSES = ("calendar__outside", "calendar__hidden")
NEXT_HINTS = ("next", "forward", "chevron-right", "arrow-right")


def parse_calendar(html: str) -> pd.DataFrame:
    """One row per real calendar day in the current view.

    Cells carrying `calendar__outside` or `calendar__hidden` are padding from
    the adjacent month and are dropped: they have no price, and keeping them
    shadows the same date's real cell in the next view.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for cell in soup.select("td[data-day]"):
        classes = cell.get("class", [])
        if any(c in classes for c in PADDING_CLASSES):
            continue
        text = " ".join(cell.get_text(" ", strip=True).split())
        match = CELL_TEXT_RE.match(text)
        rows.append({
            "date": cell["data-day"],
            "price_chf": float(match.group(2).replace(",", ".")) if match else None,
            "raw_text": text,
            "classes": " ".join(classes),
            "disabled": "calendar__disabled" in classes,
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def find_next_arrow(driver):
    """The month-forward control, and whether it is disabled."""
    for button in driver.find_elements(By.TAG_NAME, "button"):
        hint = ((button.get_attribute("aria-label") or "") + " "
                + (button.get_attribute("class") or "")).lower()
        if any(k in hint for k in NEXT_HINTS):
            disabled = (
                button.get_attribute("disabled") is not None
                or (button.get_attribute("aria-disabled") or "").lower() == "true"
                or "disabled" in (button.get_attribute("class") or "").lower()
            )
            return button, disabled
    return None, None


def crawl_calendar(driver, max_steps: int = 14, settle: float = 2.5,
                   verbose: bool = True) -> pd.DataFrame:
    """Page forward through the month views, parsing each.

    Stops after two consecutive views with no priced dates, which is past the
    end of the season.
    """
    chunks, seen, dry_views = [], set(), 0
    for step in range(max_steps):
        view = parse_calendar(driver.page_source)
        new = view[~view["date"].isin(seen)]
        n_priced = int(new["price_chf"].notna().sum()) if len(new) else 0
        if verbose:
            span = f", {new['date'].min()} to {new['date'].max()}" if len(new) else ""
            print(f"    step {step}: {len(new)} new, {n_priced} priced{span}")
        if len(new):
            chunks.append(new)
            seen.update(new["date"])

        dry_views = dry_views + 1 if n_priced == 0 else 0
        if dry_views >= 2:
            break

        button, disabled = find_next_arrow(driver)
        if button is None or disabled:
            break
        try:
            robust_click(driver, button)
        except Exception:
            time.sleep(2)
            button, _ = find_next_arrow(driver)
            if button is None:
                break
            robust_click(driver, button)
        time.sleep(settle)

    if not chunks:
        return pd.DataFrame(columns=COLUMNS)

    out = pd.concat(chunks, ignore_index=True).drop_duplicates("date")
    out["date"] = pd.to_datetime(out["date"])
    out["price_chf"] = pd.to_numeric(out["price_chf"], errors="coerce")
    return out.sort_values("date").reset_index(drop=True)