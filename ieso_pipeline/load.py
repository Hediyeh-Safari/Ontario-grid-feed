"""Load validated grid data into Postgres with idempotent upserts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

INIT_SQL = Path(__file__).resolve().parents[2] / "db" / "init.sql"

UPSERT_SQL = text(
    """
    INSERT INTO grid_hourly (ts, series, value_mw, source)
    VALUES (:ts, :series, :value_mw, :source)
    ON CONFLICT (ts, series) DO UPDATE
    SET value_mw = EXCLUDED.value_mw,
        source = EXCLUDED.source,
        loaded_at = now()
    """
)


def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True, pool_pre_ping=True)


def ensure_schema(engine: Engine) -> None:
    ddl = INIT_SQL.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(ddl)


def upsert_grid(engine: Engine, df: pd.DataFrame) -> int:
    """Insert or update rows keyed by (ts, series). Returns the number of rows sent.

    Running the same input twice leaves the table unchanged.
    """
    if df.empty:
        return 0
    rows = [
        {
            "ts": ts.to_pydatetime(),
            "series": series,
            "value_mw": float(value),
            "source": source,
        }
        for ts, series, value, source in zip(df["ts"], df["series"], df["value_mw"], df["source"])
    ]
    with engine.begin() as conn:
        conn.execute(UPSERT_SQL, rows)
    return len(rows)


def read_grid(engine: Engine) -> pd.DataFrame:
    return pd.read_sql(
        text("SELECT ts, series, value_mw, source FROM grid_hourly ORDER BY ts, series"),
        engine,
    )
