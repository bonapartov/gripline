"""Eligibility for ranked results; excluded entrants are not absentees."""
import pandas as pd


def ranked_rows(rows):
    """Keep classified finals (including classified DNF), never DNS/DQ/zero.

    Optional columns keep synthetic/legacy callers compatible. DataLoader always
    supplies final_status and only reads published events.
    """
    mask = pd.to_numeric(rows['position'], errors='coerce').gt(0)
    if 'final_status' in rows:
        mask &= rows['final_status'].fillna('').isin(['', 'DNF'])
    if 'live' in rows:
        mask &= rows['live'].eq(True)
    return rows.loc[mask].copy()
