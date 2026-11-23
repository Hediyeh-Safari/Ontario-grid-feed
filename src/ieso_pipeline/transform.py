"""Time handling for IESO hourly reports.

IESO reports use "hour ending" convention: row H covers the interval
(H-1):00 to H:00 in Eastern Standard Time. EST is fixed at UTC-05:00 in these
reports (no daylight-saving shift), so we use a fixed offset and never
localize with a DST-aware timezone.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

IESO_TZ = timezone(timedelta(hours=-5), name="EST")
VALID_HOURS_ENDING = range(1, 25)


def hour_ending_to_start(report_date: date, hour_ending: int) -> datetime:
    """Return the interval start for an hour-ending row.

    Hour ending 1 on 2025-01-01 is 2025-01-01 00:00 EST.
    Hour ending 24 is 23:00 on the same date.
    """
    if hour_ending not in VALID_HOURS_ENDING:
        raise ValueError(f"hour_ending must be between 1 and 24, got {hour_ending}")
    midnight = datetime.combine(report_date, time(0), tzinfo=IESO_TZ)
    return midnight + timedelta(hours=hour_ending - 1)


def add_timestamps(long_df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``ts`` column from ``report_date`` and ``hour_ending``.

    Expects columns: report_date (date), hour_ending (int), series, value_mw, source.
    Returns the frame with the same columns, with ``ts`` and without the
    intermediate columns.
    """
    required = {"report_date", "hour_ending", "series", "value_mw", "source"}
    missing = required - set(long_df.columns)
    if missing:
        raise KeyError(f"missing columns: {sorted(missing)}")

    out = long_df.copy()
    out["ts"] = [
        hour_ending_to_start(d, int(h)) for d, h in zip(out["report_date"], out["hour_ending"])
    ]
    return out[["ts", "series", "value_mw", "source"]]
