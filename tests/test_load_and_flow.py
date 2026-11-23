"""Database and end-to-end tests. They need a Postgres database.

Set TEST_DATABASE_URL (or DATABASE_URL). Without it, these tests are skipped.
The tests TRUNCATE grid_hourly, so do not point them at a database with real data.
"""

import os
from datetime import date

import pytest
from sqlalchemy import text

from ieso_pipeline.flow import ieso_pipeline
from ieso_pipeline.load import ensure_schema, get_engine, read_grid, upsert_grid
from ieso_pipeline.quality import validate_grid
from ieso_pipeline.sources import synthetic_grid
from ieso_pipeline.transform import add_timestamps

DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")

pytestmark = pytest.mark.skipif(not DB_URL, reason="set TEST_DATABASE_URL to run database tests")


@pytest.fixture
def engine():
    eng = get_engine(DB_URL)
    ensure_schema(eng)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE grid_hourly"))
    yield eng
    eng.dispose()


def test_upsert_is_idempotent(engine):
    df = validate_grid(add_timestamps(synthetic_grid(date(2025, 1, 1), days=1)))
    upsert_grid(engine, df)
    first = read_grid(engine)
    upsert_grid(engine, df)
    second = read_grid(engine)
    assert len(first) == len(second) == len(df)


def test_upsert_updates_changed_value(engine):
    df = validate_grid(add_timestamps(synthetic_grid(date(2025, 1, 1), days=1)))
    upsert_grid(engine, df)

    changed = df.copy()
    changed.loc[changed.index[0], "value_mw"] = 123.0
    upsert_grid(engine, changed)

    stored = read_grid(engine)
    assert len(stored) == len(df)
    row = stored[(stored["ts"] == changed.loc[changed.index[0], "ts"]) & (stored["series"] == changed.loc[changed.index[0], "series"])]
    assert float(row["value_mw"].iloc[0]) == 123.0


def test_check_constraint_rejects_negative_in_db(engine):
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO grid_hourly (ts, series, value_mw, source) VALUES (now(), 'demand', -1, 'x')")
            )


def test_offline_flow_end_to_end(engine):
    rows = ieso_pipeline(offline=True, start=date(2025, 1, 1), days=2, database_url=DB_URL)
    assert rows == 2 * 24 * 7
    stored = read_grid(engine)
    assert stored["series"].nunique() == 7
    assert set(stored["source"]) == {"synthetic"}
    # Running again must not duplicate rows.
    ieso_pipeline(offline=True, start=date(2025, 1, 1), days=2, database_url=DB_URL)
    assert len(read_grid(engine)) == rows
