"""Build docs/data/feed.json: the last N days of Ontario grid data from IESO public reports.

Run daily (locally or by GitHub Actions). Uses the fetch_real_grid() function
already in the ieso_pipeline package. Writes one JSON file the website reads.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd

from ieso_pipeline.sources import FUEL_SERIES, fetch_real_grid

DAYS = int(os.getenv("FEED_DAYS", "30"))
DEMAND_DIR = os.getenv("IESO_DEMAND_DIR", "https://reports-public.ieso.ca/public/Demand/")
FUEL_DIR = os.getenv("IESO_FUEL_DIR", "https://reports-public.ieso.ca/public/GenOutputbyFuelHourly/")
TIMEOUT = int(os.getenv("IESO_HTTP_TIMEOUT_S", "60"))
OUT = Path(__file__).resolve().parents[1] / "docs" / "data" / "feed.json"

# Wind and solar are the non-dispatchable part; net load = demand - (wind + solar).
VARIABLE = ["wind", "solar"]


def load_long() -> pd.DataFrame:
    today = dt.date.today()
    frames = []
    for year in sorted({today.year - 1, today.year}):
        frames.append(fetch_real_grid(year, DEMAND_DIR, FUEL_DIR, TIMEOUT))
    df = pd.concat(frames, ignore_index=True)
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    return df


def build_day_record(day: dt.date, wide: pd.DataFrame) -> dict | None:
    rows = wide[wide["report_date"] == day].sort_values("hour_ending")
    if rows.empty or "demand" not in rows:
        return None
    rows = rows.copy()
    for col in FUEL_SERIES:
        if col not in rows:
            rows[col] = 0.0
    rows[FUEL_SERIES] = rows[FUEL_SERIES].fillna(0.0)
    rows["demand"] = rows["demand"].fillna(0.0)

    net = rows["demand"] - rows[VARIABLE].sum(axis=1)
    ramp = net.diff().dropna()
    gen_total = rows[FUEL_SERIES].sum(axis=1).sum()
    gas_share = float(rows["gas"].sum() / gen_total) if gen_total else 0.0

    return {
        "date": day.isoformat(),
        "hours": [int(h) for h in rows["hour_ending"]],
        "demand": [round(float(v), 1) for v in rows["demand"]],
        "net_load": [round(float(v), 1) for v in net],
        "gen": {f: [round(float(v), 1) for v in rows[f]] for f in FUEL_SERIES},
        "peak_demand_mw": round(float(rows["demand"].max()), 1),
        "min_net_load_mw": round(float(net.min()), 1),
        "max_hourly_ramp_mw": round(float(ramp.max()), 1) if len(ramp) else 0.0,
        "gas_share": round(gas_share, 4),
    }


def main() -> None:
    df = load_long()
    wide = (
        df.pivot_table(index=["report_date", "hour_ending"], columns="series",
                       values="value_mw", aggfunc="first")
        .reset_index()
    )
    wide.columns.name = None
    all_days = sorted(wide["report_date"].unique())[-DAYS:]

    days = [r for r in (build_day_record(d, wide) for d in all_days) if r]
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "IESO public reports (Ontario Demand, Generator Output by Fuel)",
        "note": "Net load = demand minus wind and solar. Market analysis cards are not yet based on Market Demand.",
        "days": days,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"wrote {len(days)} days to {OUT}")


if __name__ == "__main__":
    main()
