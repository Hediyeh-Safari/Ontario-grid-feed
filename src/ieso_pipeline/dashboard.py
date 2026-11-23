"""Streamlit dashboard: hourly demand vs generation by fuel, with a clickable day picker.

Run locally:  streamlit run src/ieso_pipeline/dashboard.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ieso_pipeline.config import load_settings
from ieso_pipeline.load import get_engine, read_grid
from ieso_pipeline.sources import FUEL_SERIES

st.set_page_config(page_title="Ontario grid: IESO hourly", layout="wide")
st.title("Ontario grid: hourly demand and generation by fuel")


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    engine = get_engine(load_settings().database_url)
    df = read_grid(engine)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Etc/GMT+5")
    return df


data = load_data()
if data.empty:
    st.warning("No data yet. Run the pipeline first: python -m ieso_pipeline.flow --offline")
    st.stop()

sources = ", ".join(sorted(data["source"].unique()))
st.caption(f"Data source(s): {sources}. Times are IESO EST (UTC-05:00, no daylight saving).")

days = sorted(data["ts"].dt.date.unique())
chosen = st.selectbox("Day", days, index=len(days) - 1, format_func=str)

day = data[data["ts"].dt.date == chosen]
wide = day.pivot(index="ts", columns="series", values="value_mw")

demand = wide["demand"]
generation = wide[FUEL_SERIES]

col1, col2, col3 = st.columns(3)
col1.metric("Peak demand (MW)", f"{demand.max():,.0f}", help=str(demand.idxmax()))
col2.metric("Average demand (MW)", f"{demand.mean():,.0f}")
share_non_gas = 1 - generation["gas"].sum() / generation.sum().sum()
col3.metric("Non-gas share of generation", f"{share_non_gas:.0%}")

st.subheader("Generation by fuel (MW)")
st.area_chart(generation)

st.subheader("Demand (MW)")
st.line_chart(demand)

with st.expander("Hourly table"):
    st.dataframe(wide.round(0), use_container_width=True)
