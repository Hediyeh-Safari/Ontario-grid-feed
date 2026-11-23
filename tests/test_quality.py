from datetime import date

import pandas as pd
import pandera as pa
import pytest

from ieso_pipeline.quality import assert_complete, missing_hours, validate_grid
from ieso_pipeline.sources import synthetic_grid
from ieso_pipeline.transform import add_timestamps


@pytest.fixture
def good_frame():
    return add_timestamps(synthetic_grid(date(2025, 1, 1), days=1))


def test_valid_synthetic_passes(good_frame):
    validated = validate_grid(good_frame)
    assert len(validated) == len(good_frame)


def test_negative_value_fails(good_frame):
    bad = good_frame.copy()
    bad.loc[0, "value_mw"] = -5.0
    with pytest.raises(pa.errors.SchemaErrors):
        validate_grid(bad)


def test_unit_error_above_plausible_max_fails(good_frame):
    # A kW value mistaken for MW would look like this.
    bad = good_frame.copy()
    bad.loc[0, "value_mw"] = 18_000_000.0
    with pytest.raises(pa.errors.SchemaErrors):
        validate_grid(bad)


def test_unknown_series_fails(good_frame):
    bad = good_frame.copy()
    bad.loc[0, "series"] = "coal"
    with pytest.raises(pa.errors.SchemaErrors):
        validate_grid(bad)


def test_off_the_hour_timestamp_fails(good_frame):
    bad = good_frame.copy()
    bad.loc[0, "ts"] = bad.loc[0, "ts"] + pd.Timedelta(minutes=30)
    with pytest.raises(pa.errors.SchemaErrors):
        validate_grid(bad)


def test_duplicate_key_fails(good_frame):
    bad = pd.concat([good_frame, good_frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(pa.errors.SchemaErrors):
        validate_grid(bad)


def test_missing_hour_is_detected(good_frame):
    start, end = good_frame["ts"].min(), good_frame["ts"].max()
    dropped = good_frame[~((good_frame["ts"] == start) & (good_frame["series"] == "nuclear"))]
    gaps = missing_hours(dropped, start, end)
    assert len(gaps) == 1
    with pytest.raises(ValueError, match="missing"):
        assert_complete(dropped, start, end)


def test_complete_frame_has_no_gaps(good_frame):
    start, end = good_frame["ts"].min(), good_frame["ts"].max()
    assert missing_hours(good_frame, start, end).empty
    assert_complete(good_frame, start, end)
