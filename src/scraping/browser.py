"""Selenium helpers shared by discovery and the DOM validation path.

Only discovery needs a browser; daily collection is plain HTTP.
"""
from __future__ import annotations

import re
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

from .config import USER_AGENT

COOKIE_LABELS = ("Allow all cookies", "Allow all", "Accept all", "Accept", "OK",
                 "Alle zulassen", "Tout accepter", "Accetta tutto")
DATE_LABEL_RE = (
    r"\d{1,2}\.\d{1,2}\.\d{4}"                     # 28.11.2026
    r"|\d{1,2}/\d{1,2}/\d{4}"                      # 28/11/2026
    r"|[A-Za-zÀ-ÿ]{3,}\.?\s+\d{1,2},?\s+\d{4}"     # Sat, Dec 12, 2026
    r"|\d{1,2}\.?\s+[A-Za-zÀ-ÿ]{3,}\.?\s+\d{4}"    # 12. Dezember 2026 / 12 déc. 2026
)


def make_driver(headless: bool = True, perf_log: bool = True) -> webdriver.Chrome:
    """Chrome with a real UA plus our project identifier, and the network log on.

    The UA must stay a parseable browser string: the shops' front end throws a
    client-side exception on a non-standard one.
    """
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=950,950")
    opts.add_argument(f"--user-agent={USER_AGENT}")
    if perf_log:
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=opts)


def robust_click(driver, element) -> str:
    """Click an element, trying progressively blunter strategies."""
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(0.4)
    for how in ("native", "actions", "js"):
        try:
            if how == "native":
                element.click()
            elif how == "actions":
                ActionChains(driver).move_to_element(element).pause(0.2).click().perform()
            else:
                driver.execute_script("arguments[0].click();", element)
            return how
        except Exception:
            continue
    raise RuntimeError("all click strategies failed")


def _clickables(driver):
    return driver.find_elements(By.TAG_NAME, "button") + driver.find_elements(By.TAG_NAME, "a")


def click_text(driver, text: str) -> str:
    """Match on Selenium's rendered .text, not XPath.

    XPath concatenates child text nodes without whitespace, so a label split
    across two spans never matches contains().
    """
    for el in _clickables(driver):
        if " ".join((el.text or "").split()) == text:
            return robust_click(driver, el)
    raise RuntimeError(f"no clickable with text {text!r}")


def click_regex(driver, pattern: str) -> str:
    rx = re.compile(pattern)
    for el in _clickables(driver):
        label = " ".join((el.text or "").split())
        if rx.search(label):
            robust_click(driver, el)
            return label
    raise RuntimeError(f"no clickable matching /{pattern}/")


def dismiss_cookies(driver) -> bool:
    """Main document first, then any Cookiebot iframe.

    Must run BEFORE the calendar is opened: dismissing the banner afterwards
    closes the modal.
    """
    for label in COOKIE_LABELS:
        try:
            click_text(driver, label)
            return True
        except Exception:
            pass
    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
        if "cookiebot" not in (frame.get_attribute("src") or ""):
            continue
        driver.switch_to.frame(frame)
        try:
            for label in COOKIE_LABELS:
                try:
                    click_text(driver, label)
                    return True
                except Exception:
                    pass
        finally:
            driver.switch_to.default_content()
    return False


def open_calendar(driver, settle: float = 5.0):
    """Make the price calendar visible. Returns the layout, or None on failure.

    Two layouts exist across PriceNow shops: the calendar is already inline on
    the page (Titlis), or it sits behind a date-field button that opens a
    modal (Laax, Sörenberg, Chäserrugg).
    """
    if driver.find_elements(By.CSS_SELECTOR, "td[data-day]"):
        return "inline"
    try:
        click_regex(driver, DATE_LABEL_RE)
    except Exception:
        return None
    time.sleep(settle)
    return "modal" if driver.find_elements(By.CSS_SELECTOR, "td[data-day]") else None


def count_calendar_cells(driver) -> int:
    return len(driver.find_elements(By.CSS_SELECTOR, "td[data-day]"))

def apply_pre_steps(driver, steps, settle: float = 3.0) -> list:
    """Run the per-shop clicks needed before the calendar appears.

    Each step is either {"click_text": "..."} or {"click_regex": "..."}.
    Returns the labels actually clicked, so discovery can record them.
    """
    done = []
    for step in steps or []:
        if "click_text" in step:
            click_text(driver, step["click_text"])
            done.append(step["click_text"])
        elif "click_regex" in step:
            done.append(click_regex(driver, step["click_regex"]))
        else:
            raise ValueError(f"unknown pre-step: {step}")
        time.sleep(settle)
    return done