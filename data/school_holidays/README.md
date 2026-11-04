# School holiday calendar 

**Author:** Eucharia Ogo Oramalu 

## What this contributes
One row per day of the 2026/27 ski season (1 Nov 2026 – 1 May 2027) with a
0/1 school-holiday flag per canton (`zh_hol`, `ag_hol`, …). Valais is split into
`vso_hol` (Oberwallis) and `vsf_hol` (Valais romand).

## Files
- `src/cleaning/make_flags_final.py` – builds the flags (run from the repo root:
  `python src/cleaning/make_flags_final.py`)
- `holidays_raw.csv` – school holiday periods per canton, as collected
- `holidays_clean.csv` – the same table after corrections from official sources
- `school_holidays_flags_2026_27.csv` – the result: 182 days × one flag per canton
- `sources.md` – source and access date for each checked canton

## Method
1. Holiday periods per canton were collected and checked against the EDK
   (Schulferien 2026/2027) and municipal school calendars.
2. Periods starting on a Monday are extended back to the Saturday, and periods
   ending on a Friday forward to the Sunday.
3. Every season day is flagged 1 if it falls inside any period of that canton.

## Limitations
- Some cantons let municipalities set sport and spring holidays (AG, AR, BE, GR,
  SG, ZH). One representative municipality is used per canton (Stadt Bern,
  Stadt St. Gallen, Aarau, Chur, Herisau), so a flag is approximate for other
  municipalities.
- GR dates are verified against Stadtschule Chur and may differ at Laax/Flims.

