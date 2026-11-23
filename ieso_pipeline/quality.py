"""Data-quality checks with pandera.

Two layers:
1. Schema checks (types, ranges, allowed series, no duplicate keys).
2. Completeness check (no missing hours for any series).
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

from .sources import ALL_SERIES

# Sanity bounds. Ontario's peak demand is in the tens of GW, so 60 GW is a
# generous ceiling that still catches unit errors (kW vs MW).
MAX_PLAUSIBLE_MW = 60_000.0


def _on_the_hour(s: pd.Series) -> pd.Series:
    return (s.dt.minute == 0) & (s.dt.second == 0)


grid_schema = DataFrameSchema(
    columns={
        "ts": Column(nullable=False, checks=Check(_on_the_hour, element_wise=False, error="ts must be on the hour")),
        "series": Column(str, nullable=False, checks=Check.isin(ALL_SERIES)),
        "value_mw": Column(
            float,
            nullable=False,
            checks=[
                Check.ge(0.0, error="value_mw must be non-negative"),
                Check.le(MAX_PLAUSIBLE_MW, error="value_mw above plausible maximum (unit error?)"),
            ],
        ),
        "source": Column(str, nullable=False),
    },
    unique=["ts", "series"],
    strict=False,
    coerce=True,
)


def validate_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Return the validated frame or raise pandera.errors.SchemaError."""
    return grid_schema.validate(df, lazy=True)


def missing_hours(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """List (series, ts) pairs that are absent between start and end, inclusive.

    The expected grid is every hour for every series in ALL_SERIES.
    """
    expected_index = pd.date_range(start=start, end=end, freq="h")
    present = set(zip(df["ts"], df["series"]))
    rows = [
        {"ts": ts, "series": series}
        for series in ALL_SERIES
        for ts in expected_index
        if (ts, series) not in present
    ]
    return pd.DataFrame(rows, columns=["ts", "series"])


def assert_complete(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> None:
    gaps = missing_hours(df, start, end)
    if not gaps.empty:
        raise ValueError(f"{len(gaps)} missing (ts, series) pairs; first: {gaps.iloc[0].to_dict()}")

