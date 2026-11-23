from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from ieso_pipeline.transform import IESO_TZ, add_timestamps, hour_ending_to_start


def test_hour_ending_1_is_midnight_est():
    ts = hour_ending_to_start(date(2025, 1, 1), 1)
    assert ts == datetime(2025, 1, 1, 0, 0, tzinfo=IESO_TZ)


def test_hour_ending_24_is_23h_same_day():
    ts = hour_ending_to_start(date(2025, 1, 1), 24)
    assert ts == datetime(2025, 1, 1, 23, 0, tzinfo=IESO_TZ)


@pytest.mark.parametrize("bad", [0, 25, -1])
def test_invalid_hour_ending_raises(bad):
    with pytest.raises(ValueError):
        hour_ending_to_start(date(2025, 1, 1), bad)


def test_offset_is_fixed_minus_five_in_summer_too():
    # July is daylight time in Toronto, but IESO reports stay at EST (UTC-05:00).
    ts = hour_ending_to_start(date(2025, 7, 1), 1)
    assert ts.utcoffset() == timedelta(hours=-5)
    assert ts.astimezone(timezone.utc) == datetime(2025, 7, 1, 5, 0, tzinfo=timezone.utc)


def test_add_timestamps_builds_ts_column():
    raw = pd.DataFrame(
        {
            "report_date": [date(2025, 3, 9)] * 2,
            "hour_ending": [1, 24],
            "series": ["demand", "demand"],
            "value_mw": [1000.0, 1100.0],
            "source": ["synthetic", "synthetic"],
        }
    )
    out = add_timestamps(raw)
    assert list(out.columns) == ["ts", "series", "value_mw", "source"]
    assert out["ts"].iloc[0] == datetime(2025, 3, 9, 0, 0, tzinfo=IESO_TZ)
    assert out["ts"].iloc[1] == datetime(2025, 3, 9, 23, 0, tzinfo=IESO_TZ)


def test_add_timestamps_rejects_missing_columns():
    with pytest.raises(KeyError):
        add_timestamps(pd.DataFrame({"report_date": [date(2025, 1, 1)]}))
