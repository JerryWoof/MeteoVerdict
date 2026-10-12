"""Sunrise and sunset, computed (no request): the NOAA solar calculator (Meeus,
*Astronomical Algorithms*), with the sun's position taken at the rise or set itself.
Rise and set are when the top of the sun touches a flat horizon (sun's centre 0.833°
below it: refraction and radius), as in almanacs and weather apps; matches them to a
few seconds in Czechia."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta

ZENITH = 90.833
J2000 = 2451545.0
UNIX_JD = 2440587.5  # Julian day of 1970-01-01 00:00 UTC


def _position(jd: float) -> tuple[float, float]:
    """The sun's declination (radians) and the equation of time (minutes) at ``jd``."""
    rad = math.radians
    t = (jd - J2000) / 36525
    mean_long = rad((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    anomaly = rad(357.52911 + t * (35999.05029 - 0.0001537 * t))
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = (
        math.sin(anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * anomaly) * (0.019993 - 0.000101 * t)
        + math.sin(3 * anomaly) * 0.000289
    )
    omega = rad(125.04 - 1934.136 * t)
    apparent = rad(math.degrees(mean_long) + centre - 0.00569 - 0.00478 * math.sin(omega))
    seconds = 21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))
    obliquity = rad(23 + (26 + seconds / 60) / 60 + 0.00256 * math.cos(omega))
    declination = math.asin(math.sin(obliquity) * math.sin(apparent))
    y = math.tan(obliquity / 2) ** 2
    equation = 4 * math.degrees(
        y * math.sin(2 * mean_long)
        - 2 * ecc * math.sin(anomaly)
        + 4 * ecc * y * math.sin(anomaly) * math.cos(2 * mean_long)
        - 0.5 * y * y * math.sin(4 * mean_long)
        - 1.25 * ecc * ecc * math.sin(2 * anomaly)
    )
    return declination, equation


def sun_times(lat: float, lon: float, day: date) -> tuple[datetime | None, datetime | None]:
    """Sunrise and sunset in UTC on ``day`` at ``lat``, ``lon`` (degrees, east positive);
    ``None`` for both when the sun stays up or down all day."""
    midnight = datetime.combine(day, time(), UTC)
    start = midnight.timestamp() / 86400 + UNIX_JD
    times = []
    for side in (1, -1):  # rise: the sun east of the meridian (positive hour angle)
        minutes = 720.0
        for _ in range(3):
            declination, equation = _position(start + minutes / 1440)
            cos_hour = math.cos(math.radians(ZENITH)) / (
                math.cos(math.radians(lat)) * math.cos(declination)
            ) - math.tan(math.radians(lat)) * math.tan(declination)
            if not -1 <= cos_hour <= 1:
                return None, None
            hour = math.degrees(math.acos(cos_hour))
            minutes = 720 - 4 * (lon + side * hour) - equation
        times.append((midnight + timedelta(minutes=minutes)).replace(microsecond=0))
    return times[0], times[1]
