"""Calendar and moon computations for day-level date candidates (pure Python, no dependency).

Reference: Jean Meeus, Astronomical Algorithms, 2nd ed. (Willmann-Bell, 1998):
chapter 7 (Julian day), chapter 49 (new moon). Delta T: polynomial of Espenak and Meeus
for the years -500 to +500 (NASA Five Millennium Canon of Solar Eclipses).

Nothing here is a source for a Bible fact: it only turns explicit hypotheses
(see data/calendar_rules.yml) into dates. Dates before 1582 use the Julian calendar.
"""
from __future__ import annotations

import math

# --- Julian day and Julian calendar (Meeus, chapter 7) ---

WEEKDAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def jd_from_julian_date(year: int, month: int, day: float) -> float:
    """Julian day of a Julian-calendar date (astronomical year: 1 BCE = 0). `day` may have a fraction."""
    if month <= 2:
        year, month = year - 1, month + 12
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day - 1524.5


def julian_date_from_jd(jd: float) -> tuple:
    """Julian day -> (year, month, day with fraction) in the Julian calendar."""
    z = math.floor(jd + 0.5)
    f = jd + 0.5 - z
    b = z + 1524
    c = math.floor((b - 122.1) / 365.25)
    d = math.floor(365.25 * c)
    e = math.floor((b - d) / 30.6001)
    day = b - d - math.floor(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    return year, month, day


def civil_day_number(year: int, month: int, day: int) -> int:
    """Whole-day counter of a Julian-calendar civil date (Julian day at noon of that date)."""
    return math.floor(jd_from_julian_date(year, month, day) + 0.5)


def date_from_day_number(n: int) -> tuple:
    y, m, d = julian_date_from_jd(n - 0.5 + 0.5)    # noon of civil day n
    return y, m, int(math.floor(d))


def weekday(n: int) -> str:
    """Weekday of the civil day number n (Meeus: (JD + 1.5) mod 7, 0 = Sunday)."""
    return WEEKDAYS[(n + 1) % 7]


def iso_date(n: int) -> str:
    """'0030-04-07' for the Julian civil day n (astronomical year, 4 digits, '-' for negative years)."""
    y, m, d = date_from_day_number(n)
    return f"{'-' if y < 0 else ''}{abs(y):04d}-{m:02d}-{d:02d}"


# --- Delta T (Espenak and Meeus), valid for -500..+500 ---

def delta_t_seconds(year: float) -> float:
    if not -500 <= year <= 500:
        raise ValueError("delta_t_seconds is only defined here for the years -500 to +500")
    u = year / 100.0
    return (10583.6 - 1014.41 * u + 33.78311 * u ** 2 - 5.952053 * u ** 3
            - 0.1798452 * u ** 4 + 0.022174192 * u ** 5 + 0.0090316521 * u ** 6)


# --- new moon (Meeus, chapter 49) ---

_NEW_MOON_TERMS = (   # (coefficient, E power, M, M', F, omega multipliers)
    (-0.40720, 0, 0, 1, 0, 0), (0.17241, 1, 1, 0, 0, 0), (0.01608, 0, 0, 2, 0, 0),
    (0.01039, 0, 0, 0, 2, 0), (0.00739, 1, -1, 1, 0, 0), (-0.00514, 1, 1, 1, 0, 0),
    (0.00208, 2, 2, 0, 0, 0), (-0.00111, 0, 0, 1, -2, 0), (-0.00057, 0, 0, 1, 2, 0),
    (0.00056, 1, 1, 2, 0, 0), (-0.00042, 0, 0, 3, 0, 0), (0.00042, 1, 1, 0, 2, 0),
    (0.00038, 1, 1, 0, -2, 0), (-0.00024, 1, -1, 2, 0, 0), (-0.00017, 0, 0, 0, 0, 1),
    (-0.00007, 0, 2, 1, 0, 0), (0.00004, 0, 0, 2, -2, 0), (0.00004, 0, 3, 0, 0, 0),
    (0.00003, 0, 1, 1, -2, 0), (0.00003, 0, 0, 2, 2, 0), (-0.00003, 0, 1, 1, 2, 0),
    (0.00003, 0, -1, 1, 2, 0), (-0.00002, 0, -1, 1, -2, 0), (-0.00002, 0, 1, 3, 0, 0),
    (0.00002, 0, 0, 4, 0, 0),
)
_PLANETARY = (   # (A0, A1 per k) of the additional arguments A1..A14 and their coefficients
    (299.77, 0.107408, 0.000325), (251.88, 0.016321, 0.000165), (251.83, 26.651886, 0.000164),
    (349.42, 36.412478, 0.000126), (84.66, 18.206239, 0.000110), (141.74, 53.303771, 0.000062),
    (207.14, 2.453732, 0.000060), (154.84, 7.306860, 0.000056), (34.52, 27.261239, 0.000047),
    (207.19, 0.121824, 0.000042), (291.34, 1.844379, 0.000040), (161.72, 24.198154, 0.000037),
    (239.56, 25.513099, 0.000035), (331.55, 3.592518, 0.000023),
)


def new_moon_jde(k: int) -> float:
    """Julian ephemeris day (dynamical time) of the new moon number k (k = 0: January 2000)."""
    t = k / 1236.85
    jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * t ** 2 - 0.000000150 * t ** 3 + 0.00000000073 * t ** 4
    e = 1 - 0.002516 * t - 0.0000074 * t ** 2
    m = math.radians((2.5534 + 29.10535670 * k - 0.0000014 * t ** 2 - 0.00000011 * t ** 3) % 360)
    mp = math.radians((201.5643 + 385.81693528 * k + 0.0107582 * t ** 2 + 0.00001238 * t ** 3
                       - 0.000000058 * t ** 4) % 360)
    f = math.radians((160.7108 + 390.67050284 * k - 0.0016118 * t ** 2 - 0.00000227 * t ** 3
                      + 0.000000011 * t ** 4) % 360)
    om = math.radians((124.7746 - 1.56375588 * k + 0.0020672 * t ** 2 + 0.00000215 * t ** 3) % 360)
    corr = 0.0
    for c, ep, a, b, g, o in _NEW_MOON_TERMS:
        corr += c * e ** ep * math.sin(a * m + b * mp + g * f + o * om)
    for a0, a1, c in _PLANETARY:
        corr += c * math.sin(math.radians((a0 + a1 * k - (0.009173 * t ** 2 if a0 == 299.77 else 0)) % 360))
    return jde + corr


def new_moon_ut(k: int) -> float:
    """Julian day (universal time) of the new moon k, using the Delta T polynomial (years -500..500)."""
    jde = new_moon_jde(k)
    year = julian_date_from_jd(jde)[0]
    return jde - delta_t_seconds(year + 0.5) / 86400.0


def new_moons_between(jd_start: float, jd_end: float) -> list:
    """[(k, JD in UT)] of the new moons with jd_start <= JD < jd_end."""
    k = math.floor((jd_start - 2451550.09766) / 29.530588861) - 2
    out = []
    while True:
        jd = new_moon_ut(k)
        if jd >= jd_end:
            return out
        if jd >= jd_start:
            out.append((k, jd))
        k += 1


# --- the Jewish month beginning (a hypothesis, parametrised) ---

def sunset_jd_ut(day_number: int, longitude_east_deg: float, local_hour: float = 18.0) -> float:
    """Julian day (UT) of sunset on the civil day `day_number`, taken at `local_hour` local mean time.

    A fixed local hour is an approximation (the true sunset in Jerusalem moves by about
    half an hour over the year); it is listed among the assumptions of every candidate.
    """
    return (day_number - 0.5) + (local_hour - longitude_east_deg / 15.0) / 24.0


def first_visible_evening(conjunction_jd: float, longitude_east_deg: float, min_age_hours: float,
                          local_hour: float = 18.0) -> int:
    """Civil day number of the first evening on which the moon is at least `min_age_hours` old at sunset.

    The month starts on that evening (days begin at sunset), so its first daylight is the next civil day.
    """
    n = math.floor(conjunction_jd + 0.5) - 1
    while True:
        if (sunset_jd_ut(n, longitude_east_deg, local_hour) - conjunction_jd) * 24.0 >= min_age_hours:
            return n
        n += 1
