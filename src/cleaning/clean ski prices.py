"""
Real cleaning pipeline for CIP_HS26_208 scraped ski prices
============================================================

Runs the six checks from the feasibility study's "Cleaning, validation and
enrichment" table against the actual data in data/raw/ from Adam's scraper
(the prices_<snapshot>.csv files), not fake data.

Usage:
    python clean_ski_prices.py /path/to/data/raw
    (defaults to ./data/raw if no argument given -- i.e. run it from the
    repo root, or point it at wherever you've put the raw/ folder)

Output: ski_price_panel_cleaned.csv -- one row per (resort, ski_date,
snapshot_date) quote, enriched with days_until_ski_date, is_weekend,
price_change_pct and repricing_flag.

Notes on what the real data turned out to look like (read this before you
touch anything -- it changes how step 2 works compared to the toy example):

  - price_chf is ALREADY a clean float in Swiss francs (pricenow.py divides
    the raw cents from the site before writing the CSV) -- no "CHF 72.-"
    string parsing needed here, unlike the raw per-resort JSON files.
  - duration_days is always 1 in every row of every snapshot -- the scraper
    already filters down to single-day tickets before writing the CSV.
  - 5 of 6 resorts (Chaeserrugg, Laax, Nendaz-Veysonnaz, Soerenberg, Titlis)
    use ONE fixed label for their 1-day adult ticket, and EVERY row for that
    resort uses it -- so there's no mixed-product noise to filter out.
  - Lauchernalp is the exception: its site names each day's ticket after
    the date itself ("Sa 12.12.2026", "Su 13.12.2026", ...), so there's no
    single fixed label to match on -- step 2 below handles that with a
    regex instead of a literal string.
  - Soerenberg's price is CHF 64.0 in every single row across every
    snapshot so far -- flat, no variation at all. That might be a genuine
    finding (flat pricing) or the scraper grabbing a static listed price
    instead of the date-specific one -- worth asking Adam to double check
    against the live site before trusting it for RQ1/RQ3.
"""

import sys
import glob
import os
import re

import numpy as np
import pandas as pd

pd.set_option("display.width", 120)
pd.set_option("display.max_columns", 20)

# The one fixed label per resort, found by checking which label accounts for
# 100% of that resort's rows in the data collected so far. Lauchernalp has
# no fixed label -- it's matched by pattern instead (see is_canonical_label).
CANONICAL_LABELS = {
    "Chäserrugg": "4h & 1d Ski Ticket 26/27",
    "Laax": "1 Tag/Day",
    "Nendaz-Veysonnaz": "1 Jour Ski 4V",
    "Sörenberg": "4 Stundenkarte + Tageskarte Winter 2026 / 2027",
    "Titlis": "1 Tag und 1/2 Tag ab 12:00 Uhr",
}
LAUCHERNALP_LABEL_RE = re.compile(r"^[A-Za-z]{2} \d{2}\.\d{2}\.\d{4}$")  # "Sa 12.12.2026"


# ---------------------------------------------------------------------------
# LOAD + COMBINE  (this folds in step 5 "combining records" early, because
# with this data all 6 snapshots share one schema -- simpler to concat first
# and run the checks on the combined frame than to repeat them 6 times)
# ---------------------------------------------------------------------------

def load_raw(raw_dir: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(raw_dir, "prices_*.csv")))
    if not files:
        raise FileNotFoundError(f"No prices_*.csv files found in {raw_dir}")

    frames = []
    for f in files:
        df = pd.read_csv(f)
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)

    raw["ski_date"] = pd.to_datetime(raw["date"])
    # observed_at mixes CEST (+02:00) and CET (+01:00) timestamps across the
    # Oct->Nov snapshots (the DST switch). Parse as UTC first to unify the
    # mixed offsets into one instant, THEN convert to Europe/Zurich before
    # taking the calendar date -- taking the UTC date directly would be
    # wrong for any run close to local midnight (e.g. a 00:30 CET scrape is
    # already "the next day" locally, but still the previous day in UTC).
    # Doesn't change anything in the current 6 snapshots (none run near
    # midnight), but matters once daily automated runs start.
    observed = pd.to_datetime(raw["observed_at"], utc=True).dt.tz_convert("Europe/Zurich")
    raw["snapshot_date"] = observed.dt.tz_localize(None).dt.normalize()
    return raw


# ---------------------------------------------------------------------------
# STEP 1 — missing quotes / coverage
# "Distinguish sold out, not yet on sale and extraction failure, never
#  treating these as zero prices. Coverage and failed runs reported by resort."
# ---------------------------------------------------------------------------

def step1_coverage_and_availability(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()

    # In every snapshot collected SO FAR, every row has a price. That is NOT
    # guaranteed by the scraper: pricenow.py's parse_validities() writes
    # price_chf = None whenever the API's minPrice is null. "Not yet on sale"
    # (a (resort, ski_date) pair entirely ABSENT from an early snapshot, then
    # present later) is the common case and is reported below -- but a row
    # that IS present with a null price is a different, rarer case and must
    # not be silently treated as zero or dropped without a flag.
    coverage = (
        df.groupby("snapshot_date")
          .agg(resorts=("resort", "nunique"), quotes=("resort", "size"),
               earliest_ski_date=("ski_date", "min"), latest_ski_date=("ski_date", "max"))
    )
    print("Coverage by snapshot (rows = dates newly visible to the scraper that day):")
    print(coverage, "\n")

    null_price = df["price_chf"].isna()
    if null_price.any():
        print(f"WARNING: {null_price.sum()} row(s) have a null price_chf despite being present "
              f"in the data -- the API returned no price for these. Investigate before dropping; "
              f"never fill with 0.\n")
        print(df.loc[null_price, ["resort", "date"]].drop_duplicates(), "\n")

    # is_available can ALSO be null (option.get("isAvailable") on a missing
    # key), not just True/False. np.where treats NaN as truthy, so this must
    # be handled explicitly rather than with np.where(df["is_available"], ...)
    # -- otherwise a null availability silently becomes "available".
    status = pd.Series("unknown_availability", index=df.index, dtype="object")
    status[df["is_available"] == True] = "available"    # noqa: E712 (explicit True/False match, not truthy check)
    status[df["is_available"] == False] = "sold_out"     # noqa: E712
    df["status"] = status

    print("Status breakdown (current data):")
    print(df["status"].value_counts(), "\n")
    if (df["status"] == "unknown_availability").any():
        print(f"WARNING: {(df['status']=='unknown_availability').sum()} row(s) had a null "
              f"is_available value (neither True nor False) -- investigate.\n")

    return df


# ---------------------------------------------------------------------------
# STEP 2 — product matching ("compare standard adult full-day base prices
#  ... exclude half-days, insurance and promotions")
# In THIS data duration_days is already always 1 and 5/6 resorts only ever
# emit one label, so this step is mostly a safety net / documentation of
# what "the standard product" means per resort, not heavy filtering.
# ---------------------------------------------------------------------------

def step2_match_canonical_product(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Resorts the scraper produced that we have NO matching rule for at all
    # (new resort added since this script was written). These would
    # otherwise be silently dropped below -- flag loudly instead, since a
    # resort quietly vanishing from the cleaned output is much worse than a
    # noisy warning.
    known_resorts = set(CANONICAL_LABELS) | {"Lauchernalp"}
    unknown_resorts = set(df["resort"].unique()) - known_resorts
    if unknown_resorts:
        print(f"!!! UNKNOWN RESORT(S) WITH NO MATCHING RULE: {sorted(unknown_resorts)} !!!")
        print(f"!!! {len(df[df['resort'].isin(unknown_resorts)])} row(s) for these will be "
              f"DROPPED from the cleaned output until you add them to CANONICAL_LABELS "
              f"(or LAUCHERNALP_LABEL_RE-style handling if they use per-date labels). !!!\n")

    def is_canonical(row):
        if row["resort"] == "Lauchernalp":
            return bool(LAUCHERNALP_LABEL_RE.match(str(row["label"])))
        expected = CANONICAL_LABELS.get(row["resort"])
        return row["label"] == expected

    df["is_canonical_label"] = df.apply(is_canonical, axis=1)

    off_label = df[~df["is_canonical_label"]]
    if len(off_label):
        print(f"WARNING: {len(off_label)} row(s) don't match the expected adult-day-ticket "
              f"label for their resort -- these look like a different product (half-day, "
              f"youth, multi-day) and should be excluded or investigated:")
        print(off_label[["resort", "ski_date", "label"]].drop_duplicates(), "\n")
    else:
        print("All rows match each resort's canonical adult-day-ticket label "
              "(or, for Lauchernalp, the date-named label pattern). No off-label rows found.\n")

    df = df[df["is_canonical_label"]].drop(columns=["is_canonical_label", "duration_days",
                                                      "capacity_kind", "label", "date", "observed_at",
                                                      "max_price_chf"])
    return df


# ---------------------------------------------------------------------------
# STEP 3 — validity checks
# "Check positive prices ... and valid ski dates. Duplicate quote keys ...
#  will be investigated."
# ---------------------------------------------------------------------------

def step3_validity_checks(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    key_cols = ["resort", "ski_date", "snapshot_date"]
    dup_mask = df.duplicated(subset=key_cols, keep="first")
    if dup_mask.any():
        print(f"Dropping {dup_mask.sum()} duplicate quote row(s) (same resort + ski_date + "
              f"snapshot_date).\n")
    df = df[~dup_mask]

    bad_price = df["price_chf"] <= 0
    if bad_price.any():
        print(f"WARNING: {bad_price.sum()} non-positive price(s) -- investigate before dropping.\n")

    bad_dates = df["ski_date"].isna() | df["snapshot_date"].isna()
    if bad_dates.any():
        print(f"WARNING: {bad_dates.sum()} row(s) with unparseable dates.\n")

    return df


# ---------------------------------------------------------------------------
# STEP 4 — unusual prices
# ---------------------------------------------------------------------------

def step4_flag_unusual_prices(df: pd.DataFrame, lower=20, upper=200) -> pd.DataFrame:
    df = df.copy()
    df["price_flag_out_of_range"] = ~df["price_chf"].between(lower, upper)
    n_flagged = df["price_flag_out_of_range"].sum()
    print(f"Prices outside CHF {lower}-{upper}: {n_flagged} "
          f"(current data ranges CHF 45-97 across all resorts, so this should be 0 for now -- "
          f"keep the check in place for when more snapshots land).\n")

    # Resorts with zero price variance across the whole observation window.
    # CONFIRMED for Soerenberg (2026-11-02): Adam checked the live site --
    # it runs a flat-rate table (CHF 64 for adults, every date), not dynamic
    # pricing. Not a scraper bug; it's a genuine resort-level finding worth
    # a line in the final write-up (some resorts don't price dynamically at
    # all). It just means Soerenberg will correctly show 0% repricing in
    # RQ3 and no holiday premium in RQ1 -- there's nothing to compare.
    variance_by_resort = df.groupby("resort")["price_chf"].nunique()
    flat = variance_by_resort[variance_by_resort == 1]
    if len(flat):
        print(f"NOTE: {list(flat.index)} show(s) exactly ONE distinct price across every date "
              f"and every snapshot collected so far. For Soerenberg this is confirmed to be a "
              f"real flat-rate pricing model, not a scraping error -- if any OTHER resort shows "
              f"up here, that one still needs a source check.\n")

    return df


# ---------------------------------------------------------------------------
# STEP 6 — added variables (step 5 "combining" already happened at load time
# since all snapshots share one schema; holiday_exposure is left as an open
# column for Ogo's output -- see the join instructions at the bottom)
# ---------------------------------------------------------------------------

def step6_add_variables(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.sort_values(["resort", "ski_date", "snapshot_date"]).reset_index(drop=True)

    df["days_until_ski_date"] = (df["ski_date"] - df["snapshot_date"]).dt.days
    df["is_weekend"] = df["ski_date"].dt.dayofweek.isin([5, 6])

    group_cols = ["resort", "ski_date"]
    df["prev_price_chf"] = df.groupby(group_cols)["price_chf"].shift(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = (df["price_chf"] - df["prev_price_chf"]) / df["prev_price_chf"] * 100
    df["price_change_pct"] = pct.replace([np.inf, -np.inf], np.nan)  # guards a CHF 0 prev price
    df["repricing_flag"] = df["price_change_pct"].notna() & (df["price_change_pct"] != 0)

    # Placeholder for Ogo's holiday-exposure work -- join her output onto
    # `ski_date` once it's ready, e.g.:
    #   holiday = pd.read_csv("holiday_exposure.csv", parse_dates=["ski_date"])
    #   df = df.merge(holiday[["ski_date", "holiday_exposure"]], on="ski_date", how="left")
    #   df["holiday_exposure"] = df["holiday_exposure"].fillna(0.0)
    df["holiday_exposure"] = np.nan

    return df


# ---------------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------------

def main():
    raw_dir = sys.argv[1] if len(sys.argv) > 1 else "data/raw"

    print("=" * 78)
    print(f"LOAD + COMBINE  (reading prices_*.csv from {raw_dir})")
    print("=" * 78)
    raw = load_raw(raw_dir)
    print(f"{len(raw)} total raw rows across {raw['snapshot_date'].nunique()} snapshots, "
          f"{raw['resort'].nunique()} resorts.\n")

    print("=" * 78)
    print("STEP 1 — missing quotes / coverage / availability")
    print("=" * 78)
    df = step1_coverage_and_availability(raw)

    print("=" * 78)
    print("STEP 2 — matching the canonical adult-day-ticket product")
    print("=" * 78)
    df = step2_match_canonical_product(df)

    print("=" * 78)
    print("STEP 3 — validity checks")
    print("=" * 78)
    df = step3_validity_checks(df)

    print("=" * 78)
    print("STEP 4 — unusual prices")
    print("=" * 78)
    df = step4_flag_unusual_prices(df)

    print("=" * 78)
    print("STEP 6 — added variables")
    print("=" * 78)
    df = step6_add_variables(df)

    print("=" * 78)
    print("RESULT")
    print("=" * 78)
    print(f"Final cleaned panel: {len(df)} rows.\n")
    print(df.head(15).to_string(index=False))

    out_path = "ski_price_panel_cleaned.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
