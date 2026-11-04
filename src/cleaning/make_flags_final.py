"""
make_flags_final.py  -  task 1a (school-holiday flags, ski season 2026/27)

Input : data/school_holidays/holidays_raw.csv   (canton, holiday_type, start_date, end_date)
Output: holidays_clean.csv              (the corrected holiday table)
        school_holidays_flags_2026_27.csv  (one row per day, one <canton>_hol column)

Steps: 1) load  2) apply corrections from official sources  3) extend to weekends
       4) build one 0/1 flag column per canton for every day of the season  5) save
"""
import io
from pathlib import Path
import pandas as pd

# Where the CSV files live. In the repo: data/school_holidays/ (script is in src/cleaning/).
# If that folder does not exist (e.g. running from your own Holidays folder), use the script's folder.
HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data" / "school_holidays"
if not DATA.exists():
    DATA = HERE

# ---------- 1. load -------------------------------------------------------
hol = pd.read_csv(DATA / "holidays_raw.csv", parse_dates=["start_date", "end_date"])
print("rows read:", hol.shape)

# ---------- 2. corrections (sources in comments) ---------------------------
# Remove the rows we replace (BE, SG, TI, VS completely; SZ Christmas; AR and OW sport)
hol = hol[~hol["canton"].isin(["BE", "SG", "TI", "VS"])]
hol = hol[~((hol["canton"] == "SZ") & (hol["holiday_type"] == "Weihnachten"))]
hol = hol[~((hol["canton"] == "AR") & (hol["holiday_type"] == "Sport"))]
hol = hol[~((hol["canton"] == "OW") & (hol["holiday_type"] == "Sport"))]

corrections = """canton,holiday_type,start_date,end_date
BE,Herbst,2026-09-19,2026-10-11
BE,Weihnachten,2026-12-24,2027-01-10
BE,Sport,2027-02-06,2027-02-14
BE,Frühling,2027-04-10,2027-04-25
BE,Sommer,2027-07-02,2027-08-15
SG,Herbst,2026-09-27,2026-10-18
SG,Weihnachten,2026-12-20,2027-01-03
SG,Sport,2027-01-31,2027-02-07
SG,Ostern,2027-03-26,2027-03-29
SG,Frühling,2027-04-11,2027-04-25
SG,Sommer,2027-07-11,2027-08-15
TI,Herbst,2026-10-31,2026-11-08
TI,Weihnachten,2026-12-24,2027-01-06
TI,Sport,2027-02-06,2027-02-14
TI,Ostern,2027-03-26,2027-04-04
OW,Sport,2027-02-04,2027-02-14
VSO,Weihnachten,2026-12-21,2027-01-01
VSO,Sport,2027-02-27,2027-03-07
VSO,Frühling,2027-04-24,2027-05-09
VSF,Weihnachten,2026-12-24,2027-01-10
VSF,Sport,2027-02-06,2027-02-14
VSF,Frühling,2027-03-26,2027-04-04
SZ,Weihnachten,2026-12-25,2027-01-06
AR,Sport,2027-02-01,2027-02-05
"""
# BE: Stadt Bern school calendar; SG: Stadt St. Gallen / EDK; TI: EDK
# OW: Engelberg (for Titlis); VSO/VSF: Oberwallis / Valais romand (EDK)
# SZ: EDK; AR: Herisau (schuleherisau.ch)
new = pd.read_csv(io.StringIO(corrections), parse_dates=["start_date", "end_date"])

hol = pd.concat([hol, new]).drop_duplicates()
hol = hol.sort_values(["canton", "start_date"]).reset_index(drop=True)
print("rows after corrections:", hol.shape)      # expect (89, 4)
hol.to_csv(DATA / "holidays_clean.csv", index=False)

# ---------- 3. extend to weekends -----------------------------------------
# Monday start -> include the weekend before; Friday end -> include the weekend after
hol.loc[hol["start_date"].dt.weekday == 0, "start_date"] -= pd.Timedelta(days=2)
hol.loc[hol["end_date"].dt.weekday == 4, "end_date"] += pd.Timedelta(days=2)

# ---------- 4. one flag column per canton ----------------------------------
days = pd.date_range("2026-11-01", "2027-05-01")      # the 2026/27 ski season
flags = pd.DataFrame({"date": days})
print("days in season:", flags.shape)               # expect (182, 1)

for canton in sorted(hol["canton"].unique()):
    col = canton.lower() + "_hol"                   # e.g. zh_hol
    flags[col] = 0
    for _, row in hol[hol["canton"] == canton].iterrows():
        inside = flags["date"].between(row["start_date"], row["end_date"])
        flags.loc[inside, col] = 1

# ---------- 5. check and save ----------------------------------------------
print("flags table:", flags.shape)
print(flags.drop(columns="date").sum())             # holiday days per canton
flags.to_csv(DATA / "school_holidays_flags_2026_27.csv", index=False)
print("saved school_holidays_flags_2026_27.csv")