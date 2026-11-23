"""Prefect flow: extract -> transform -> validate -> load, run hourly.

Examples
    python -m ieso_pipeline.flow --offline                 # one run, synthetic data
    python -m ieso_pipeline.flow --offline --serve         # run every hour (offline)
    python -m ieso_pipeline.flow --year 2025               # one run, real demand data
"""

from __future__ import annotations

import argparse
from datetime import date, datetime

import pandas as pd
from prefect import flow, get_run_logger, task

from .config import load_settings
from .load import ensure_schema, get_engine, upsert_grid
from .quality import assert_complete, validate_grid
from .sources import fetch_real_grid, synthetic_grid
from .transform import add_timestamps

DEFAULT_OFFLINE_START = date(2025, 1, 1)


@task(retries=2, retry_delay_seconds=60)
def extract(offline: bool, start: date, days: int, year: int | None) -> pd.DataFrame:
    logger = get_run_logger()
    if offline:
        logger.info("Generating synthetic grid: %s for %d day(s)", start, days)
        return synthetic_grid(start, days)

    settings = load_settings()
    target_year = year or start.year
    logger.info("Downloading IESO demand and generation by fuel for %s", target_year)
    return fetch_real_grid(target_year, settings.demand_dir, settings.fuel_dir, settings.http_timeout_s)


@task
def transform(raw: pd.DataFrame) -> pd.DataFrame:
    return add_timestamps(raw)


@task
def validate(df: pd.DataFrame) -> pd.DataFrame:
    validated = validate_grid(df)
    return validated


@task
def load(df: pd.DataFrame, database_url: str) -> int:
    logger = get_run_logger()
    engine = get_engine(database_url)
    ensure_schema(engine)
    written = upsert_grid(engine, df)
    logger.info("Upserted %d rows into grid_hourly", written)
    return written


@flow(name="ieso-hourly")
def ieso_pipeline(
    offline: bool = True,
    start: date = DEFAULT_OFFLINE_START,
    days: int = 2,
    year: int | None = None,
    database_url: str | None = None,
) -> int:
    settings = load_settings()
    url = database_url or settings.database_url

    raw = extract(offline, start, days, year)
    df = transform(raw)
    df = validate(df)

    if offline:
        # Offline data is complete by construction; checking it proves the check works.
        start_ts = df["ts"].min()
        end_ts = df["ts"].max()
        assert_complete(df, start_ts, end_ts)

    return load(df, url)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="IESO hourly pipeline")
    parser.add_argument("--offline", action="store_true", help="use synthetic data (no internet)")
    parser.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), default=DEFAULT_OFFLINE_START)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--year", type=int, default=None, help="IESO demand year (online mode)")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--serve", action="store_true", help="keep running, once per hour")
    args = parser.parse_args(argv)

    params = {
        "offline": args.offline,
        "start": args.start,
        "days": args.days,
        "year": args.year,
        "database_url": args.database_url,
    }
    if args.serve:
        ieso_pipeline.serve(name="ieso-hourly", interval=3600, parameters=params)
    else:
        rows = ieso_pipeline(**params)
        print(f"loaded {rows} rows")


if __name__ == "__main__":
    main()
