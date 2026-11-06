"""
research_questions.py
Analysis for the three research questions (CIP HS26, group 208).

Run it from the repo root:
    python src/analysis/research_questions.py
or give it the path to the panel:
    python src/analysis/research_questions.py path/to/ski_price_panel_cleaned.csv

It needs pandas, numpy, scipy and statsmodels. It prints all the numbers that
we use in section 3 of the report.

A few things to keep in mind when reading the output:
- The 4602 quotes are only 777 series (resort x ski date) that we saw up to 6
  times, so the rows are not independent. That is why the regressions use
  standard errors clustered by series.
- We only have 6 collection dates (15 Oct to 1 Nov). In a pooled regression,
  days_until_ski_date mostly says which ski date is quoted (early or late in
  the season) and not how the price moved. The within-series estimate further
  down is the one that is about repricing.
- The snapshots are 2 to 5 days apart, not daily, so one "consecutive pair" in
  RQ3 covers 2 to 5 days.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import spearmanr

pd.set_option("display.width", 130)

DEFAULT_PANEL = "data/processed/ski_price_panel_cleaned.csv"
N_BOOT = 500   # bootstrap repetitions
SEED = 42      # so the bootstrap gives the same interval every time

LEAD_BINS = [-1, 7, 14, 30, 60, 10**6]
LEAD_LABELS = ["0-7", "8-14", "15-30", "31-60", "60+"]
EXPOSURE_BINS = [-0.01, 0, 0.34, 1.01]
EXPOSURE_LABELS = ["none", "low", "high"]


def load(path):
    df = pd.read_csv(path, parse_dates=["ski_date", "snapshot_date"])


    needed = ["holiday_exposure", "piste_km", "any_feeder_hol", "resort_hol"]
    missing = [c for c in needed if c not in df.columns or df[c].isna().all()]
    if missing:
        sys.exit(f"Missing or empty columns in the panel: {missing}. "
                 "Run the cleaning script again so the joins are included.")

    df["log_price"] = np.log(df["price_chf"])
    df["month"] = df["ski_date"].dt.month
    # one id per (resort, ski_date) series, used for the clustered standard errors
    df["series_id"] = pd.factorize(df["resort"] + "|" + df["ski_date"].astype(str))[0]
    return df


def ols_cluster(formula, data):
    return smf.ols(formula, data).fit(cov_type="cluster",
                                      cov_kwds={"groups": data["series_id"]})


def pct(b):
    # coefficient of a log-price regression -> % difference in price
    return (np.exp(b) - 1) * 100


# ---------------------------------------------------------------------------
# RQ3: dynamic repricing
# ---------------------------------------------------------------------------
def rq3(df):
    print("=" * 78)
    print("RQ3: Dynamic repricing")
    print("=" * 78)

    # only quotes that have an earlier quote of the same resort and ski date
    v = df.dropna(subset=["prev_price_chf"]).sort_values(
        ["resort", "ski_date", "snapshot_date"]).copy()
    prev_snap = v.groupby(["resort", "ski_date"])["snapshot_date"].shift(1)
    v["gap_days"] = (v["snapshot_date"] - prev_snap).dt.days

    n = len(v)
    changed = int(v["repricing_flag"].sum())
    up = int((v["price_change_pct"] > 0).sum())
    down = int((v["price_change_pct"] < 0).sum())
    print(f"Valid pairs: {n}   changed: {changed} ({changed / n:.1%})   up: {up}   down: {down}")

    size = v[v["repricing_flag"]]["price_change_pct"].abs()
    print(f"Mean absolute % change per event: {size.mean():.2f}%  (min {size.min():.2f}, max {size.max():.2f})")

    series = v.groupby(["resort", "ski_date"])["repricing_flag"].any()
    print(f"Series with at least one change: {int(series.sum())} / {len(series)} ({series.mean():.1%})")

    t = v.groupby("resort")["repricing_flag"].agg(valid_pairs="size", changed_pairs="sum")
    t["pct_changed"] = (t["changed_pairs"] / t["valid_pairs"] * 100).round(1)
    print("\nBy resort:")
    print(t.to_string())

    v["lead"] = pd.cut(v["days_until_ski_date"], bins=LEAD_BINS, labels=LEAD_LABELS)
    lead_tbl = v.groupby("lead", observed=True)["repricing_flag"].agg(valid_pairs="size", changed_pairs="sum")
    lead_tbl["pct_changed"] = (lead_tbl["changed_pairs"] / lead_tbl["valid_pairs"] * 100).round(1)
    print("\nBy lead time (days until the ski date):")
    print(lead_tbl.to_string())

    print("\nDays between the two compared snapshots:")
    print(v["gap_days"].value_counts().sort_index().to_string())
    if (v["gap_days"] != 1).any():
        print("Note: the snapshots are not daily, each comparison covers 2 to 5 days.")

    return lead_tbl


# ---------------------------------------------------------------------------
# RQ2: price drivers
# ---------------------------------------------------------------------------
def rq2(df):
    print("\n" + "=" * 78)
    print("RQ2: Price drivers")
    print("=" * 78)

    print("\nMean price by month:")
    print(df.groupby("month")["price_chf"].agg(["mean", "std", "count"]).round(2).to_string())

    print("\nMean price, weekend vs weekday:")
    print(df.groupby("is_weekend")["price_chf"].agg(["mean", "std", "count"]).round(2).to_string())

    # one row per resort, then rank correlation with the resort attributes
    rs = df.groupby("resort").agg(
        mean_price=("price_chf", "mean"),
        piste_km=("piste_km", "first"),
        n_lifts=("n_lifts", "first"),
        base_altitude_m=("base_altitude_m", "first"),
        top_altitude_m=("top_altitude_m", "first"),
        vertical_drop_m=("vertical_drop_m", "first"))
    print("\nResort mean price and attributes:")
    print(rs.round(2).to_string())

    print("\nSpearman correlation of resort mean price with the attributes (only 6 resorts):")
    for c in ["piste_km", "n_lifts", "base_altitude_m", "top_altitude_m", "vertical_drop_m"]:
        r, p = spearmanr(rs["mean_price"], rs[c])
        print(f"  {c:18s} rho = {r:+.2f}   p = {p:.3f}")

    m = ols_cluster("log_price ~ days_until_ski_date + is_weekend + holiday_exposure + C(resort)", df)
    print("\nOLS on log(price), standard errors clustered by series")
    print(f"  R-squared: {m.rsquared:.3f}")
    for k in ["is_weekend[T.True]", "holiday_exposure", "days_until_ski_date"]:
        print(f"  {k:22s} coef {m.params[k]:+.5f}  ({pct(m.params[k]):+.2f}%)  p = {m.pvalues[k]:.4f}")

    # same ski date and resort, so only the lead time changes
    w = ols_cluster("log_price ~ days_until_ski_date + C(series_id)", df)
    b = w.params["days_until_ski_date"]
    print("\nWithin-series lead time effect (series fixed effects):")
    print(f"  every 10 days closer to the ski date: {pct(-10 * b):+.2f}% price   (p = {w.pvalues['days_until_ski_date']:.2g})")
    print("  only 6 collection dates, so this cannot be separated from calendar time yet")


# ---------------------------------------------------------------------------
# RQ1: holiday premium
# ---------------------------------------------------------------------------
def rq1(df):
    print("\n" + "=" * 78)
    print("RQ1: Holiday premium")
    print("=" * 78)

    f = "log_price ~ holiday_exposure + days_until_ski_date + is_weekend + C(resort)"
    m = smf.ols(f, df).fit()
    b = m.params["holiday_exposure"]
    print(f"OLS: holiday_exposure coef = {b:.4f}  ->  {pct(b):.1f}% (exposure from 0 to 1), R2 = {m.rsquared:.3f}")

    # bootstrap: draw whole series with replacement, not single rows
    rng = np.random.default_rng(SEED)
    keys = df[["resort", "ski_date"]].drop_duplicates().reset_index(drop=True)
    groups = {k: g for k, g in df.groupby(["resort", "ski_date"])}
    coefs = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(keys), len(keys))
        sample = pd.concat(
            [groups[(keys.loc[i, "resort"], keys.loc[i, "ski_date"])] for i in idx],
            ignore_index=True)
        coefs.append(smf.ols(f, sample).fit().params["holiday_exposure"])
    lo, hi = np.percentile(coefs, [2.5, 97.5])
    print(f"Bootstrap over whole series ({len(coefs)} reps): coef 95% CI [{lo:.4f}, {hi:.4f}]"
          f"  ->  {pct(lo):.1f}% to {pct(hi):.1f}%")

    print("\nMean price by holiday exposure (none = 0, low = up to 0.33, high = above 0.33):")
    bucket = pd.cut(df["holiday_exposure"], EXPOSURE_BINS, labels=EXPOSURE_LABELS)
    t = df.groupby(["resort", bucket], observed=True)["price_chf"].mean().unstack().round(2)
    t["high_vs_none_%"] = ((t["high"] / t["none"] - 1) * 100).round(1)
    print(t.to_string())

    # checks that the result does not depend on one specific choice
    print("\nRobustness (clustered SE, % price difference for the holiday variable):")
    flat = ["Lauchernalp", "Sörenberg"]   # their price does not change with the date
    runs = [
        ("baseline, clustered SE", f, df, "holiday_exposure"),
        ("+ month fixed effects", f + " + C(month)", df, "holiday_exposure"),
        ("without the 2 flat-price resorts", f, df[~df.resort.isin(flat)], "holiday_exposure"),
        ("without flat resorts + month FE", f + " + C(month)", df[~df.resort.isin(flat)], "holiday_exposure"),
        ("any_feeder_hol instead", f.replace("holiday_exposure", "any_feeder_hol"), df, "any_feeder_hol"),
        ("resort_hol (own canton) instead", f.replace("holiday_exposure", "resort_hol"), df, "resort_hol"),
    ]
    for label, formula, data, var in runs:
        r = ols_cluster(formula, data)
        ci = r.conf_int().loc[var]
        print(f"  {label:38s} {pct(r.params[var]):5.1f}%  [{pct(ci[0]):.1f}, {pct(ci[1]):.1f}]  n = {int(r.nobs)}")

    return t

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PANEL
    if not Path(path).exists():
        sys.exit(f"File not found: {path}\nRun it from the repo root or pass the path to the panel.")

    df = load(path)
    print(f"Loaded {len(df)} rows, {df['series_id'].nunique()} series, "
          f"{df['snapshot_date'].nunique()} snapshots from {path}\n")

    rq3(df)
    rq2(df)
    rq1(df)


if __name__ == "__main__":
    main()
