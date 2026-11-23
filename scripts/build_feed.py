"""Build docs/data/feed.json from IESO public reports.

This file is self-contained: it does NOT import the ieso_pipeline package,
so it works even if the src folder in the repo is out of date.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

DAYS = int(os.getenv("FEED_DAYS", "30"))
DEMAND_DIR = os.getenv("IESO_DEMAND_DIR", "https://reports-public.ieso.ca/public/Demand/")
FUEL_DIR = os.getenv("IESO_FUEL_DIR", "https://reports-public.ieso.ca/public/GenOutputbyFuelHourly/")
TIMEOUT = int(os.getenv("IESO_HTTP_TIMEOUT_S", "60"))
OUT = Path(__file__).resolve().parents[1] / "docs" / "data" / "feed.json"

FUEL_MAP = {"NUCLEAR": "nuclear", "GAS": "gas", "HYDRO": "hydro", "WIND": "wind",
            "SOLAR": "solar", "BIOFUEL": "biofuel", "OTHER": "other"}
FUELS = list(FUEL_MAP.values())
VARIABLE = ["wind", "solar"]


def get(url: str) -> str:
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def latest_file(listing_url: str, prefix: str, year: int, ext: str) -> str:
    """Pick the file with the highest _vNNN version for the given year."""
    html = get(listing_url)
    pattern = re.compile(rf"({re.escape(prefix)}_{year}_v(\d+){re.escape(ext)})")
    matches = [(int(m.group(2)), m.group(1)) for m in pattern.finditer(html)]
    if not matches:
        raise FileNotFoundError(f"no {prefix} file for {year} in {listing_url}")
    return max(matches)[1]


def parse_demand(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("Date,"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df.columns = [c.strip() for c in df.columns]
    df = df[["Date", "Hour", "Ontario Demand"]].dropna()
    return pd.DataFrame({
        "date": pd.to_datetime(df["Date"]).dt.date,
        "hour": df["Hour"].astype(int),
        "demand": df["Ontario Demand"].astype(float),
    })


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name: str):
    for node in el.iter():
        if _local(node.tag) == name and node.text and node.text.strip():
            return node.text.strip()
    return None


def parse_fuel(text: str) -> pd.DataFrame:
    root = ET.fromstring(text)
    rows = []
    for daily in root.iter():
        if _local(daily.tag) != "DailyData":
            continue
        day = daily.get("Day") or daily.get("Date") or _child_text(daily, "Day") or _child_text(daily, "Date")
        for hourly in daily:
            if _local(hourly.tag) != "HourlyData":
                continue
            hour = (hourly.get("HourEnding") or hourly.get("Hour")
                    or _child_text(hourly, "HourEnding") or _child_text(hourly, "Hour"))
            if not day or not hour:
                continue
            for fuel_total in hourly:
                if _local(fuel_total.tag) != "FuelTotal":
                    continue
                fuel = _child_text(fuel_total, "Fuel")
                output = _child_text(fuel_total, "Output")
                if fuel is None or output is None:
                    continue  # no value in the report: skip, do not invent a zero
                if fuel not in FUEL_MAP:
                    print(f"skipping unknown fuel {fuel!r}")
                    continue
                rows.append({"date": pd.to_datetime(day).date(), "hour": int(float(hour)),
                             "fuel": FUEL_MAP[fuel], "output": float(output)})
    long = pd.DataFrame(rows)
    return long.pivot_table(index=["date", "hour"], columns="fuel", values="output", aggfunc="first").reset_index()


def load_wide(today: dt.date) -> pd.DataFrame:
    frames = []
    for year in sorted({today.year - 1, today.year}):
        demand_file = latest_file(DEMAND_DIR, "PUB_Demand", year, ".csv")
        fuel_file = latest_file(FUEL_DIR, "PUB_GenOutputbyFuelHourly", year, ".xml")
        d = parse_demand(get(DEMAND_DIR + demand_file))
        f = parse_fuel(get(FUEL_DIR + fuel_file))
        frames.append(d.merge(f, on=["date", "hour"], how="left"))
    wide = pd.concat(frames, ignore_index=True)
    return wide.sort_values(["date", "hour"]).drop_duplicates(["date", "hour"], keep="last")


def build_day(day: dt.date, wide: pd.DataFrame) -> dict | None:
    rows = wide[wide["date"] == day].copy()
    if rows.empty:
        return None
    for col in FUELS:
        if col not in rows:
            rows[col] = 0.0
    rows[FUELS] = rows[FUELS].fillna(0.0)
    net = rows["demand"] - rows[VARIABLE].sum(axis=1)
    ramp = net.diff().dropna()
    gen_total = rows[FUELS].sum(axis=1).sum()
    return {
        "date": day.isoformat(),
        "hours": [int(h) for h in rows["hour"]],
        "demand": [round(float(v), 1) for v in rows["demand"]],
        "net_load": [round(float(v), 1) for v in net],
        "gen": {f: [round(float(v), 1) for v in rows[f]] for f in FUELS},
        "peak_demand_mw": round(float(rows["demand"].max()), 1),
        "min_net_load_mw": round(float(net.min()), 1),
        "max_hourly_ramp_mw": round(float(ramp.max()), 1) if len(ramp) else 0.0,
        "gas_share": round(float(rows["gas"].sum() / gen_total), 4) if gen_total else 0.0,
    }


def main() -> None:
    wide = load_wide(dt.date.today())
    days_list = sorted(wide["date"].unique())[-DAYS:]
    days = [r for r in (build_day(d, wide) for d in days_list) if r]
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
