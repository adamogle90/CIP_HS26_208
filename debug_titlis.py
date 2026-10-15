"""One-off: what does the Titlis shop actually request?"""
import json
import time

from selenium.webdriver.common.by import By

from src.scraping.browser import dismiss_cookies, make_driver, open_calendar
from src.scraping.config import load_resorts
from src.scraping.dom import find_next_arrow

cfg = load_resorts()["titlis"]
entries = []


def drain(d):
    try:
        entries.extend(d.get_log("performance"))
    except Exception as e:
        print("drain failed:", e)


def report(tag):
    hits = []
    for e in entries:
        try:
            m = json.loads(e["message"])["message"]
        except Exception:
            continue
        if m.get("method") != "Network.requestWillBeSent":
            continue
        r = m["params"]["request"]
        if "pricenow" in r["url"]:
            hits.append((r.get("method"), r["url"][:150]))
    print(f"\n=== {tag}: {len(entries)} log entries, {len(hits)} pricenow requests ===")
    for meth, url in hits:
        print(f"  {meth:7} {url}")


d = make_driver(headless=False, perf_log=True)
try:
    d.get(cfg["url"])
    for i in range(25):
        time.sleep(1)
        drain(d)
    report("after load")

    dismiss_cookies(d)
    time.sleep(3)
    drain(d)
    report("after cookies")

    print("\nlayout:", open_calendar(d))
    print("calendar cells:", len(d.find_elements(By.CSS_SELECTOR, "td[data-day]")))
    time.sleep(3)
    drain(d)
    report("after open_calendar")

    btn, disabled = find_next_arrow(d)
    print("\nnext arrow found:", btn is not None, "| disabled:", disabled)
    if btn is not None:
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.5)
        try:
            btn.click()
            print("clicked next")
        except Exception as e:
            print("click failed:", type(e).__name__)
        time.sleep(4)
        drain(d)
        report("after next-month click")

    # channel uuid from whatever pricenow request we did see
    for e in entries:
        try:
            m = json.loads(e["message"])["message"]
        except Exception:
            continue
        if m.get("method") != "Network.requestWillBeSent":
            continue
        r = m["params"]["request"]
        if "pricenow" in r["url"] and (r.get("method") or "").upper() == "GET":
            h = {k.lower(): v for k, v in r["headers"].items()}
            print("\nchannel uuid:", h.get("pratiq-channel-uuid"))
            print("api version: ", h.get("pratiq-api-version"))
            break

    # candidate product ids in the server-rendered payload
    import re
    src = d.page_source
    print("\npage source:", len(src), "chars")
    for pat in (r'"productId"\s*:\s*"?(\d+)', r'products/(\d+)/journey',
                r'"id"\s*:\s*(1[0-9]{6})', r'journey'):
        found = re.findall(pat, src)[:8]
        print(f"  {pat!r:36} -> {found}")

    input("\npress Enter to close...")
finally:
    d.quit()