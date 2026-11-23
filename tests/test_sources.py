from datetime import date

import pandas as pd
import pytest

from ieso_pipeline.sources import (
    ALL_SERIES,
    FUEL_SERIES,
    LONG_COLUMNS,
    find_latest_file,
    parse_demand_csv,
    parse_fuel_xml,
    synthetic_grid,
)


def test_synthetic_shape_and_columns():
    df = synthetic_grid(date(2025, 1, 1), days=2)
    assert list(df.columns) == LONG_COLUMNS
    assert len(df) == 2 * 24 * len(ALL_SERIES)
    assert set(df["series"]) == set(ALL_SERIES)
    assert set(df["source"]) == {"synthetic"}


def test_synthetic_is_deterministic():
    a = synthetic_grid(date(2025, 1, 1), days=1, seed=7)
    b = synthetic_grid(date(2025, 1, 1), days=1, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_synthetic_non_negative_and_gas_balances_demand():
    df = synthetic_grid(date(2025, 6, 1), days=3)
    assert (df["value_mw"] >= 0).all()

    wide = df.pivot_table(index=["report_date", "hour_ending"], columns="series", values="value_mw")
    generation = wide[FUEL_SERIES].sum(axis=1)
    diff = (generation - wide["demand"]).abs()
    assert (diff < 1.0).mean() > 0.95


def test_synthetic_solar_is_zero_at_night():
    df = synthetic_grid(date(2025, 6, 1), days=1)
    solar = df[df["series"] == "solar"].set_index("hour_ending")["value_mw"]
    assert solar.loc[1] == 0.0
    assert solar.loc[13] > 0.0


def test_synthetic_rejects_zero_days():
    with pytest.raises(ValueError):
        synthetic_grid(date(2025, 1, 1), days=0)


# Same layout as the real IESO file, with the first lines taken from PUB_Demand_2025_v396.csv.
DEMAND_SAMPLE = """\\Hourly Demand Report,,,
\\Created at 2026-01-31 07:30:13,,,
\\For 2025,,,
Date,Hour,Market Demand,Ontario Demand
2025-01-01,1,17247,13887
2025-01-01,2,17355,13722
2025-01-01,3,17638,
"""


def test_parse_demand_csv_real_layout_uses_ontario_demand():
    out = parse_demand_csv(DEMAND_SAMPLE)
    assert list(out.columns) == LONG_COLUMNS
    assert len(out) == 2  # blank Ontario Demand row is dropped
    assert set(out["series"]) == {"demand"}
    assert set(out["source"]) == {"ieso"}
    assert out["value_mw"].tolist() == [13887.0, 13722.0]


def test_parse_demand_csv_missing_header_raises():
    with pytest.raises(ValueError, match="Date,"):
        parse_demand_csv("no header here\n1,2,3\n")


def test_parse_demand_csv_missing_column_raises():
    bad = "Date,Hour,Something\n2025-01-01,1,5\n"
    with pytest.raises(ValueError, match="missing expected columns"):
        parse_demand_csv(bad)


# Same layout as PUB_GenOutputbyFuelHourly_2025_v364.xml, cut down to two hours.
FUEL_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<Document docID="GenOutputbyFuelHourly" xmlns="http://www.ieso.ca/schema">
<DocHeader>
<DocTitle>Generator Output by Fuel Type Hourly Report</DocTitle>
</DocHeader>
<DocBody>
<DeliveryYear>2025</DeliveryYear>
<DailyData>
<Day>2025-01-01</Day>
<HourlyData>
<Hour>1</Hour>
<FuelTotal><Fuel>NUCLEAR</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>10404</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>GAS</Fuel><EnergyValue><OutputQuality>-4</OutputQuality><Output>222</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>HYDRO</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>3783</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>WIND</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>2846</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>SOLAR</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>0</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>BIOFUEL</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>18</Output></EnergyValue></FuelTotal>
</HourlyData>
<HourlyData>
<Hour>2</Hour>
<FuelTotal><Fuel>NUCLEAR</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>10402</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>GAS</Fuel><EnergyValue><OutputQuality>-4</OutputQuality><Output>153</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>HYDRO</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>3872</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>WIND</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>2849</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>SOLAR</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>0</Output></EnergyValue></FuelTotal>
<FuelTotal><Fuel>BIOFUEL</Fuel><EnergyValue><OutputQuality>0</OutputQuality><Output>19</Output></EnergyValue></FuelTotal>
</HourlyData>
</DailyData>
</DocBody>
</Document>
"""


def test_parse_fuel_xml_real_layout():
    out = parse_fuel_xml(FUEL_SAMPLE)
    assert list(out.columns) == LONG_COLUMNS
    assert len(out) == 2 * 6
    assert set(out["series"]) == set(FUEL_SERIES)
    nuclear_h1 = out[(out["hour_ending"] == 1) & (out["series"] == "nuclear")]
    assert nuclear_h1["value_mw"].iloc[0] == 10404.0
    assert nuclear_h1["report_date"].iloc[0] == date(2025, 1, 1)


def test_parse_fuel_xml_hour_1_total_matches_market_demand():
    # Sum of hour-1 generation in the real file: 17,273 MW, close to Market Demand 17,247 MW.
    out = parse_fuel_xml(FUEL_SAMPLE)
    total_h1 = out[out["hour_ending"] == 1]["value_mw"].sum()
    assert total_h1 == 17273.0


def test_parse_fuel_xml_unknown_fuel_raises():
    bad = FUEL_SAMPLE.replace("<Fuel>SOLAR</Fuel>", "<Fuel>COAL</Fuel>", 1)
    with pytest.raises(ValueError, match="unknown IESO fuel 'COAL'"):
        parse_fuel_xml(bad)


DIRECTORY_HTML = """
<a href="PUB_Demand_2024_v395.csv">PUB_Demand_2024_v395.csv</a>
<a href="PUB_Demand_2025_v395.csv">PUB_Demand_2025_v395.csv</a>
<a href="PUB_Demand_2025_v396.csv">PUB_Demand_2025_v396.csv</a>
<a href="PUB_Demand_2025_v397.csv">PUB_Demand_2025_v397.csv</a>
"""


def test_find_latest_file_picks_highest_version_for_year():
    name = find_latest_file(DIRECTORY_HTML, "PUB_Demand", 2025, ".csv")
    assert name == "PUB_Demand_2025_v397.csv"


def test_find_latest_file_missing_year_raises():
    with pytest.raises(FileNotFoundError):
        find_latest_file(DIRECTORY_HTML, "PUB_Demand", 2030, ".csv")
