"""Weinstein stage engine.

Same rules as the Kite version of the Stage Checker:
weekly bars, 30-week SMA, 4-week MA slope (±1.5% = flat),
Mansfield RS vs a benchmark, and a stage state machine.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FLAT = 1.5  # % change of the 30-week MA over 4 weeks that still counts as flat
MIN_WEEKS = 34
NAMES = {1: "Basing", 2: "Advancing", 3: "Topping", 4: "Declining"}


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Daily OHLCV (DatetimeIndex) -> weekly bars ending Friday.

    The `date` column holds the last real trading day of each week.
    """
    df = daily.copy()
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    df["date"] = df.index
    w = df.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum", "date": "last"}
    )
    return w.dropna(subset=["Close"])


@dataclass
class Event:
    i: int
    date: pd.Timestamp
    frm: int
    to: int
    close: float
    vol_ratio: float | None
    level: float | None


@dataclass
class Analysis:
    w: pd.DataFrame
    ma: np.ndarray
    ma10: np.ndarray
    slope: np.ndarray
    vr: np.ndarray
    mrs: np.ndarray
    stage: list
    events: list = field(default_factory=list)


def _sma(a: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(a).rolling(n, min_periods=n).mean().to_numpy()


def analyse(w: pd.DataFrame, bench_w: pd.DataFrame | None) -> Analysis:
    c = w["Close"].to_numpy(float)
    h = w["High"].to_numpy(float)
    l = w["Low"].to_numpy(float)
    v = w["Volume"].to_numpy(float)
    n = len(c)

    ma = _sma(c, 30)
    ma10 = _sma(c, 10)
    slope = np.full(n, np.nan)
    slope[4:] = (ma[4:] / ma[:-4] - 1) * 100

    prev10 = pd.Series(v).shift(1).rolling(10, min_periods=10).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vr = np.where(prev10 > 0, v / prev10, np.nan)

    # Mansfield RS: (stock/bench) vs its own 52-week average
    if bench_w is not None and len(bench_w):
        b = bench_w["Close"].reindex(w.index).ffill()
        rs = (w["Close"] / b).to_numpy(float)
        rs_avg = pd.Series(rs).rolling(52, min_periods=20).mean().to_numpy()
        mrs = (rs / rs_avg - 1) * 100
    else:
        mrs = np.full(n, np.nan)

    stage: list = [None] * n
    events: list[Event] = []
    prev = None
    run_start = 0
    peak = -math.inf
    first_ma = next((x for x in ma if not np.isnan(x)), np.nan)

    for i in range(n):
        if np.isnan(ma[i]) or np.isnan(slope[i]):
            continue
        above = c[i] > ma[i]
        s = slope[i]
        b10 = a10 = 0
        for k in range(max(run_start, i - 9), i + 1):
            if np.isnan(ma[k]):
                continue
            if c[k] < ma[k]:
                b10 += 1
            else:
                a10 += 1
        if run_start < i:
            run_hi, run_lo = h[run_start:i].max(), l[run_start:i].min()
        else:
            run_hi, run_lo = h[max(0, i - 1)], l[max(0, i - 1)]

        if prev is None:
            if above and s > FLAT:
                cur = 2
            elif not above and s < -FLAT:
                cur = 4
            else:
                cur = 1 if ma[i] < first_ma else (3 if s >= 0 else 1)
        elif prev == 2:
            m10_falling = i >= 4 and not np.isnan(ma10[i - 4]) and ma10[i] < ma10[i - 4]
            if not above and s < -FLAT:
                cur = 4
            elif b10 >= 3 or (c[i] < ma10[i] and m10_falling and c[i] <= peak * 0.75):
                cur = 3
            else:
                cur = 2
        elif prev == 3:
            if not above and (s < -FLAT or c[i] < run_lo):
                cur = 4
            elif above and s > FLAT and c[i] > run_hi:
                cur = 2
            else:
                cur = 3
        elif prev == 4:
            cur = 1 if ((abs(s) <= FLAT and above) or a10 >= 3) else 4
        else:  # 1
            if above and s >= -0.25 and c[i] > run_hi:
                cur = 2
            elif not above and s < -FLAT and c[i] < run_lo:
                cur = 4
            else:
                cur = 1

        if cur != prev:
            if prev is not None:
                level = run_hi if cur == 2 else run_lo if cur == 4 else None
                events.append(Event(i, w["date"].iloc[i], prev, cur, c[i],
                                    None if np.isnan(vr[i]) else float(vr[i]), level))
            run_start = i
            peak = -math.inf
        if cur == 2:
            peak = max(peak, h[i])
        stage[i] = cur
        prev = cur

    return Analysis(w, ma, ma10, slope, vr, mrs, stage, events)


def evaluate(a: Analysis) -> dict:
    """Current stage, headline numbers, key levels and the Stage 2 checklist."""
    i = len(a.w) - 1
    c = float(a.w["Close"].iloc[i])
    ma, sl = float(a.ma[i]), float(a.slope[i])
    mrs = None if np.isnan(a.mrs[i]) else float(a.mrs[i])
    mrs4 = None if i < 4 or np.isnan(a.mrs[i - 4]) else float(a.mrs[i - 4])
    dist = (c / ma - 1) * 100
    s = a.stage[i]

    run_start = i
    while run_start > 0 and a.stage[run_start - 1] == s:
        run_start -= 1
    hi = a.w["High"].to_numpy(float)
    lo = a.w["Low"].to_numpy(float)
    r_hi, r_lo = hi[run_start:i + 1].max(), lo[run_start:i + 1].min()
    low10 = lo[-10:].min()

    last_up = next((e for e in reversed(a.events) if e.to == 2), None)
    recent_up = last_up if last_up and i - last_up.i <= 26 else None

    levels = []
    if s == 1:
        levels = [("Breakout above", r_hi), ("Base support", r_lo)]
    elif s == 2:
        if last_up and last_up.level is not None and np.isfinite(last_up.level):
            levels.append(("Breakout level", last_up.level))
        levels += [("10-week low", low10), ("30-week MA", ma)]
    elif s == 3:
        levels = [("Stage 4 below", r_lo), ("Back to Stage 2 above", r_hi)]
    elif s == 4:
        levels = [("30-week MA", ma), ("Recent low", low10)]

    def pct(x, d=1):
        return "–" if x is None else f"{x:+.{d}f}%"

    checks = [
        ("Close above 30-week MA", c > ma, f"₹{c:,.2f} vs ₹{ma:,.2f}"),
        ("30-week MA rising", sl > FLAT, f"{pct(sl, 2)} over 4 weeks"),
        ("Mansfield RS above zero", None if mrs is None else mrs > 0,
         "not enough benchmark data" if mrs is None else f"{mrs:.1f}"),
        ("RS improving", None if mrs is None or mrs4 is None else mrs > mrs4,
         "–" if mrs is None or mrs4 is None else f"{mrs4:.1f} → {mrs:.1f} in 4 weeks"),
        ("Breakout on 2× average volume",
         None if not recent_up else (recent_up.vol_ratio is not None and recent_up.vol_ratio >= 2),
         "no Stage 2 breakout in last 26 weeks" if not recent_up else
         f"{recent_up.vol_ratio:.1f}× in week of {recent_up.date:%d %b %Y}" if recent_up.vol_ratio else
         f"week of {recent_up.date:%d %b %Y}"),
        ("Not overextended (within 20% of MA)", True if 0 <= dist <= 20 else False if dist > 20 else None,
         f"{pct(dist)} from MA"),
    ]
    scored = [x for x in checks if x[1] is not None]
    return {
        "stage": s, "close": c, "ma": ma, "slope": sl, "mrs": mrs, "dist": dist,
        "weeks_in": i - run_start + 1, "levels": levels, "checks": checks,
        "passed": sum(1 for x in scored if x[1]), "total": len(scored),
        "hi52": hi[-52:].max(), "lo52": lo[-52:].min(), "date": a.w["date"].iloc[i],
    }
