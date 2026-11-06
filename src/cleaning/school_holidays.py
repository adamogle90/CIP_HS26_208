"""
School-holiday variables for CIP_HS26_208 ski price panel
==========================================================

Adds the cantonal school-holiday flags for the 2026/27 ski season to the
cleaned price panel (called from step6_add_variables in clean_ski_prices.py).

Usage:
    from school_holidays import add_school_holidays
    df = add_school_holidays(df)
    (run the pipeline from the repo root -- the flags file is read from
    data/school_holidays/, see the README in that folder for method and sources)

Adds to the panel:
  - one <canton>_hol column per canton (0/1): is ski_date inside a school
    holiday period of that canton (weekends next to a holiday included)
  - resort_hol: the flag of the canton where the resort lies
  - feeder_hol_count: how many of the feeder cantons (ZH, BE, AG, LU, SG) are
    on school holiday that day (0-5)

Notes:
  - Valais is split in two because its school holidays differ by region:
    vso_hol (Oberwallis, used for Lauchernalp) and vsf_hol (Valais romand,
    used for Nendaz-Veysonnaz).
  - Some cantons let municipalities set sport and spring holidays; one
    representative municipality is used per canton (see the README).
"""

import pandas as pd

FLAGS_PATH = "data/school_holidays/school_holidays_flags_2026_27.csv"

# Canton flag that applies to the canton where each resort lies.
RESORT_FLAG = {
    "Chäserrugg": "sg_hol",
    "Laax": "gr_hol",
    "Lauchernalp": "vso_hol",
    "Nendaz-Veysonnaz": "vsf_hol",
    "Sörenberg": "lu_hol",
    "Titlis": "ow_hol",
}

# Main feeder cantons for day-trip demand.
FEEDER_FLAGS = ["zh_hol", "be_hol", "ag_hol", "lu_hol", "sg_hol", "zg_hol"]


# ---------------------------------------------------------------------------
# JOIN  (flags per ski_date -> price panel)
# ---------------------------------------------------------------------------

def add_school_holidays(df: pd.DataFrame, flags_path: str = FLAGS_PATH) -> pd.DataFrame:
    flags = pd.read_csv(flags_path, parse_dates=["date"])
    before = len(df)

    df = df.merge(flags, left_on="ski_date", right_on="date",
                  how="left", validate="many_to_one").drop(columns="date")

    assert len(df) == before, "school holiday join changed the number of rows"
    assert df["zh_hol"].notna().all(), "some ski_dates are outside the school holiday flags file"
    assert df["resort"].isin(RESORT_FLAG).all(), "resort without a canton in RESORT_FLAG"

    df["resort_hol"] = 0
    for resort, col in RESORT_FLAG.items():
        rows = df["resort"] == resort
        df.loc[rows, "resort_hol"] = df.loc[rows, col]

    df["holiday_exposure"] = df[FEEDER_FLAGS].mean(axis=1)
    df["any_feeder_hol"] = df[FEEDER_FLAGS].max(axis=1)
    return df
