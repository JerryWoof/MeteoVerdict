from datetime import UTC, date, datetime

import pytest

from meteoverdict.sun import sun_times

# reference: astral 3 (NOAA equations), Prague 50.08 N 14.42 E, in UTC
REFERENCE = [
    (date(2026, 10, 12), (5, 19, 35), (16, 17, 10)),
    (date(2026, 6, 21), (2, 52, 54), (19, 15, 21)),
    (date(2026, 12, 21), (6, 58, 53), (15, 1, 51)),
]


@pytest.mark.parametrize(("day", "rise", "set_"), REFERENCE)
def test_matches_the_almanac_within_half_a_minute(day, rise, set_):
    got_rise, got_set = sun_times(50.08, 14.42, day)
    for got, (h, m, s) in ((got_rise, rise), (got_set, set_)):
        expected = datetime(day.year, day.month, day.day, h, m, s, tzinfo=UTC)
        assert abs((got - expected).total_seconds()) < 30


def test_no_rise_or_set_in_polar_day_and_night():
    assert sun_times(80, 0, date(2026, 6, 21)) == (None, None)
    assert sun_times(80, 0, date(2026, 12, 21)) == (None, None)
