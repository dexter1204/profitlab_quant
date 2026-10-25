"""_history_bars: multi-day intraday history for the GexBot chart."""

import pandas as pd

from api import main


def _fake_multiday_5m(days=4):
    """Several days of 5-minute bars spanning 06:00–17:00 (so some fall
    outside the 08:00–15:00 regular-hours window the helper keeps)."""
    rows = []
    for d in range(days):
        day = pd.Timestamp("2026-10-05") + pd.Timedelta(days=d)
        for ts in pd.date_range(day + pd.Timedelta(hours=6),
                                day + pd.Timedelta(hours=17), freq="5min"):
            rows.append({"ts": ts, "open": 100.0, "high": 101.0,
                         "low": 99.0, "close": 100.5, "volume": 10.0})
    return pd.DataFrame(rows)


def test_history_bars_trims_to_min_and_keeps_session(monkeypatch):
    frame = _fake_multiday_5m(days=4)
    monkeypatch.setattr(main, "_intraday_bars_fallback",
                        lambda ticker, interval="5m", period="1d": frame)

    out = main._history_bars("SPX", interval="5m", min_bars=100)
    assert out is not None
    # Enough history was available → trimmed to exactly the minimum requested.
    assert len(out) == 100
    # Only regular-hours bars survive (08:00–15:00 inclusive).
    mins = out["ts"].dt.hour * 60 + out["ts"].dt.minute
    assert mins.min() >= 8 * 60 and mins.max() <= 15 * 60
    # Ascending and the newest bars are kept (last row is the latest timestamp).
    assert out["ts"].is_monotonic_increasing
    assert out["ts"].iloc[-1] == frame["ts"].max() - pd.Timedelta(hours=2)  # 15:00 of last day


def test_history_bars_returns_all_when_fewer_than_min(monkeypatch):
    frame = _fake_multiday_5m(days=1)          # one day ≈ 85 session bars
    monkeypatch.setattr(main, "_intraday_bars_fallback",
                        lambda ticker, interval="5m", period="1d": frame)
    out = main._history_bars("SPX", interval="5m", min_bars=1000)
    assert out is not None
    assert 0 < len(out) < 1000                 # no padding beyond what exists


def test_history_bars_none_when_no_data(monkeypatch):
    monkeypatch.setattr(main, "_intraday_bars_fallback",
                        lambda ticker, interval="5m", period="1d": None)
    assert main._history_bars("SPX") is None
