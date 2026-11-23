"""Data sources: IESO downloads (online) and a seeded synthetic grid (offline).

Long format returned by every source:
    report_date (date), hour_ending (int 1..24), series (str), value_mw (float), source (str)

Series names: "demand", "nuclear", "gas", "hydro", "wind", "solar", "biofuel".
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

FUEL_SERIES = ["nuclear", "gas", "hydro", "wind", "solar", "biofuel"]
ALL_SERIES = ["demand", *FUEL_SERIES]

LONG_COLUMNS = ["report_date", "hour_ending", "series", "value_mw", "source"]

# IESO fuel names in the XML, mapped to our series names.
# Unknown fuel names raise an error on purpose: a silent drop would hide missing generation.
IESO_FUEL_MAP = {
    "NUCLEAR": "nuclear",
    "GAS": "gas",
    "HYDRO": "hydro",
    "WIND": "wind",
    "SOLAR": "solar",
    "BIOFUEL": "biofuel",
}

IESO_NS = "{http://www.ieso.ca/schema}"


def synthetic_grid(start: date, days: int, seed: int = 42) -> pd.DataFrame:
    """Generate a deterministic, physically plausible Ontario-like hourly grid.

    The output is for offline testing and demos only. It is labeled
    source="synthetic" so it can never be mistaken for IESO data.
    """
    if days < 1:
        raise ValueError("days must be >= 1")

    rng = np.random.default_rng(seed)
    rows = []
    for day_idx in range(days):
        d = start + timedelta(days=day_idx)
        # Winter has higher demand (heating); summer has a smaller afternoon AC peak.
        season = 1.0 + 0.12 * np.cos(2 * np.pi * (d.timetuple().tm_yday - 15) / 365)
        for he in range(1, 25):
            hour = he - 1  # interval start hour, 0..23
            demand = (
                17_000
                + 4_500 * np.exp(-((hour - 18) ** 2) / 18)
                + 1_500 * np.exp(-((hour - 8) ** 2) / 8)
            ) * season + rng.normal(0, 250)
            demand = max(demand, 10_000.0)

            solar = max(0.0, np.sin(np.pi * (hour - 6) / 12)) * 1_600 * (0.6 + 0.4 * rng.random())
            wind = max(0.0, 1_800 + 1_100 * np.sin(2 * np.pi * (day_idx * 24 + hour) / 53) + rng.normal(0, 300))
            hydro = 3_400 + 350 * np.cos(2 * np.pi * (hour - 19) / 24) + rng.normal(0, 60)
            nuclear = 9_300 + rng.normal(0, 120)  # baseload, with small maintenance noise
            biofuel = 150 + rng.normal(0, 10)

            # Gas is the dispatchable balance. If must-run supply exceeds demand
            # (common at night), curtail wind first, then hydro, as a proxy for exports.
            min_gas = 400.0
            surplus = nuclear + hydro + wind + solar + biofuel - (demand - min_gas)
            if surplus > 0:
                cut_wind = min(surplus, wind)
                wind -= cut_wind
                surplus -= cut_wind
                hydro -= min(surplus, hydro)
            non_gas = nuclear + hydro + wind + solar + biofuel
            gas = max(demand - non_gas, 0.0)

            values = {
                "demand": demand,
                "nuclear": nuclear,
                "gas": gas,
                "hydro": hydro,
                "wind": max(wind, 0.0),
                "solar": solar,
                "biofuel": biofuel,
            }
            for series, value in values.items():
                rows.append(
                    {
                        "report_date": d,
                        "hour_ending": he,
                        "series": series,
                        "value_mw": round(float(value), 1),
                        "source": "synthetic",
                    }
                )
    return pd.DataFrame(rows, columns=LONG_COLUMNS)


def fetch_text(url: str, timeout_s: float) -> str:
    """Download a text report. Raises for HTTP errors."""
    response = requests.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.text


def find_latest_file(directory_html: str, prefix: str, year: int, extension: str) -> str:
    """Pick the highest-version file for a year from an IESO directory listing.

    IESO names files like PUB_Demand_2025_v396.csv, and the version number changes.
    Matching on the version number would break every time IESO republishes,
    so we take the highest one that appears in the listing.
    """
    pattern = re.compile(rf"{re.escape(prefix)}_{year}_v(\d+){re.escape(extension)}")
    candidates = {int(m.group(1)): m.group(0) for m in pattern.finditer(directory_html)}
    if not candidates:
        raise FileNotFoundError(f"no {prefix}_{year}_v*{extension} in the IESO directory listing")
    return candidates[max(candidates)]


def parse_demand_csv(text: str) -> pd.DataFrame:
    """Parse an IESO hourly demand CSV into the long format.

    Real file layout (verified on PUB_Demand_2025_v396.csv):
        \\Hourly Demand Report,,,
        \\Created at ...,,,
        \\For 2025,,,
        Date,Hour,Market Demand,Ontario Demand
        2025-01-01,1,17247,13887
    Lines before the header are skipped. We store "Ontario Demand" as the demand series.
    "Market Demand" is not used yet; it is close to the sum of generation by fuel.
    """
    lines = text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("Date,")),
        None,
    )
    if header_idx is None:
        raise ValueError("could not find a header line starting with 'Date,' in the IESO demand file")

    frame = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    required = {"Date", "Hour", "Ontario Demand"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"IESO demand file is missing expected columns: {sorted(missing)}")

    out = pd.DataFrame(
        {
            "report_date": pd.to_datetime(frame["Date"]).dt.date,
            "hour_ending": frame["Hour"].astype(int),
            "series": "demand",
            "value_mw": pd.to_numeric(frame["Ontario Demand"], errors="coerce"),
            "source": "ieso",
        }
    )
    out = out.dropna(subset=["value_mw"])
    return out[LONG_COLUMNS].reset_index(drop=True)


def parse_fuel_xml(text: str) -> pd.DataFrame:
    """Parse IESO 'Generator Output by Fuel Type Hourly' XML into the long format.

    Structure (verified on PUB_GenOutputbyFuelHourly_2025_v364.xml):
        Document (namespace http://www.ieso.ca/schema)
          DailyData -> Day (YYYY-MM-DD)
            HourlyData -> Hour (1..24, hour ending)
              FuelTotal -> Fuel (e.g. NUCLEAR, GAS), EnergyValue -> Output (MW)
    OutputQuality is kept out of the output for now.
    Raises if a fuel name is not in IESO_FUEL_MAP.
    """
    root = ET.fromstring(text.encode("utf-8"))
    rows = []
    for daily in root.iter(f"{IESO_NS}DailyData"):
        day_text = daily.findtext(f"{IESO_NS}Day")
        if not day_text:
            raise ValueError("DailyData element without a Day value")
        report_date = date.fromisoformat(day_text.strip())

        for hourly in daily.findall(f"{IESO_NS}HourlyData"):
            hour_text = hourly.findtext(f"{IESO_NS}Hour")
            if hour_text is None:
                raise ValueError(f"HourlyData without Hour on {day_text}")
            hour_ending = int(hour_text)

            for total in hourly.findall(f"{IESO_NS}FuelTotal"):
                fuel = (total.findtext(f"{IESO_NS}Fuel") or "").strip().upper()
                if fuel not in IESO_FUEL_MAP:
                    raise ValueError(f"unknown IESO fuel {fuel!r} on {day_text} hour {hour_ending}")
                output_text = total.findtext(f"{IESO_NS}EnergyValue/{IESO_NS}Output")
                if output_text is None:
                    raise ValueError(f"missing Output for {fuel} on {day_text} hour {hour_ending}")
                rows.append(
                    {
                        "report_date": report_date,
                        "hour_ending": hour_ending,
                        "series": IESO_FUEL_MAP[fuel],
                        "value_mw": float(output_text),
                        "source": "ieso",
                    }
                )
    return pd.DataFrame(rows, columns=LONG_COLUMNS)


def fetch_real_grid(year: int, demand_dir: str, fuel_dir: str, timeout_s: float) -> pd.DataFrame:
    """Download demand and generation-by-fuel for one year from IESO's public directories."""
    demand_listing = fetch_text(demand_dir, timeout_s)
    demand_file = find_latest_file(demand_listing, "PUB_Demand", year, ".csv")
    demand_df = parse_demand_csv(fetch_text(demand_dir + demand_file, timeout_s))

    fuel_listing = fetch_text(fuel_dir, timeout_s)
    fuel_file = find_latest_file(fuel_listing, "PUB_GenOutputbyFuelHourly", year, ".xml")
    fuel_df = parse_fuel_xml(fetch_text(fuel_dir + fuel_file, timeout_s))

    return pd.concat([demand_df, fuel_df], ignore_index=True)
