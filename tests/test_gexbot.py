"""GexBot Classic client: normalization + config, with mocked HTTP.

No network / no API key needed — we stub the transport and feed a payload
shaped like the official OpenAPI spec (strikes = [strike, gex_vol, gex_oi,
priors]).
"""

import gzip
import io
import json
import zipfile

import pytest

from profitlab.data import gexbot


# A classic snapshot shaped like GET /{ticker}/classic/{category}.
_SNAP = {
    "timestamp": 1_700_000_000,
    "ticker": "SPX",
    "min_dte": 0,
    "spot": 6687.65,
    "zero_gamma": 6643.39,
    "major_pos_oi": 6685.0,
    "major_pos_vol": 6680.0,
    "major_neg_oi": 6580.0,
    "major_neg_vol": 6600.0,
    "sum_gex_oi": 24.8697,
    "sum_gex_vol": 1162.7758,
    "delta_risk_reversal": -0.12,
    # unsorted on purpose; priors is the 4th element
    "strikes": [
        [6700.0, 120.0, 95.0, [1, 2, 3, 4, 5]],
        [6650.0, -80.0, -60.0, [1, 2, 3, 4, 5]],
        [6685.0, 300.0, 250.0, [1, 2, 3, 4, 5]],
    ],
    "max_priors": [[6685.0, 300.0], [6685.0, 290.0]],
}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("GEXBOT_API_KEY", "test-key")


def test_is_configured(monkeypatch):
    monkeypatch.delenv("GEXBOT_API_KEY", raising=False)
    assert gexbot.is_configured() is False
    monkeypatch.setenv("GEXBOT_API_KEY", "x")
    assert gexbot.is_configured() is True


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEXBOT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEXBOT_API_KEY"):
        gexbot.classic("SPX")


def test_norm_category():
    assert gexbot._norm_category("zero") == "zero"
    assert gexbot._norm_category("GEX_FULL") == "gex_full"
    assert gexbot._norm_category("bogus") == "full"
    assert gexbot._norm_category("") == "full"


def test_classic_normalizes_and_sorts(key, monkeypatch):
    seen = {}

    def fake_get(path, _retries=2):
        seen["path"] = path
        return _SNAP

    monkeypatch.setattr(gexbot, "_get", fake_get)
    out = gexbot.classic("spx", "full")

    assert seen["path"] == "/SPX/classic/full"
    assert out["ticker"] == "SPX"
    assert out["spot"] == 6687.65
    assert out["zero_gamma"] == 6643.39
    assert out["major_pos_oi"] == 6685.0
    assert out["net_gex_oi"] == 24.8697
    # strikes sorted ascending, mapped to dicts with gex_oi / gex_vol
    ks = [r["strike"] for r in out["strikes"]]
    assert ks == [6650.0, 6685.0, 6700.0]
    row = next(r for r in out["strikes"] if r["strike"] == 6685.0)
    assert row["gex_vol"] == 300.0 and row["gex_oi"] == 250.0


def test_classic_skips_malformed_rows(key, monkeypatch):
    bad = dict(_SNAP)
    bad["strikes"] = [[6700.0, 1.0], ["x", 1, 2, []], [6650.0, 1.0, 2.0, []]]
    monkeypatch.setattr(gexbot, "_get", lambda path, _retries=2: bad)
    out = gexbot.classic("SPX")
    # only the one well-formed row survives
    assert [r["strike"] for r in out["strikes"]] == [6650.0]


def test_invalid_category_falls_back(key, monkeypatch):
    seen = {}
    monkeypatch.setattr(gexbot, "_get", lambda path, _retries=2: (seen.update(path=path) or _SNAP))
    gexbot.classic("SPX", "nonsense")
    assert seen["path"].endswith("/classic/full")


def test_classic_captures_priors(key, monkeypatch):
    monkeypatch.setattr(gexbot, "_get", lambda path, _retries=2: _SNAP)
    out = gexbot.classic("SPX", "full")
    row = next(r for r in out["strikes"] if r["strike"] == 6685.0)
    assert row["priors"] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_zip_category():
    assert gexbot._zip_category("full") == "gex_full"
    assert gexbot._zip_category("zero") == "gex_zero"
    assert gexbot._zip_category("one") == "gex_one"
    assert gexbot._zip_category("gex_full") == "gex_full"   # passthrough


def _make_eod_zip(ticker="SPX", category="gex_full", date="2026-10-23", n=120):
    """A ZIP shaped like /hist/eod: one gzipped JSON list under
    {ticker}/classic/{category}/{date}_{ticker}_classic_{category}.json.gz."""
    snaps = [
        {
            "timestamp": 1_700_000_000 + i,
            "spot": 100.0 + i * 0.1,
            "zero_gamma": 99.0 + i * 0.05,
            "major_pos_oi": 110.0, "major_neg_oi": 90.0,
            "major_pos_vol": 108.0, "major_neg_vol": 92.0,
            "sum_gex_oi": -50.0 + i, "sum_gex_vol": 10.0 * i,
        }
        for i in range(n)
    ]
    gz = gzip.compress(json.dumps(snaps).encode("utf-8"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        name = f"{ticker}/classic/{category}/{date}_{ticker}_classic_{category}.json.gz"
        zf.writestr(name, gz)
    return buf.getvalue()


def test_hist_eod_series_downsamples(key, monkeypatch):
    raw = _make_eod_zip(n=120)
    monkeypatch.setattr(gexbot, "_get_bytes", lambda path, timeout=120: raw)
    out = gexbot.hist_eod_series("spx", "full", target_points=20)
    assert out["ticker"] == "SPX"
    assert out["category"] == "gex_full"
    assert out["date"] == "2026-10-23"
    assert out["count_raw"] == 120
    # downsampled to ~20 points, and the LAST snapshot is always included
    assert 10 <= len(out["points"]) <= 25
    assert out["points"][-1]["t"] == 1_700_000_000 + 119
    p0 = out["points"][0]
    assert set(p0) >= {"t", "spot", "zero_gamma", "major_pos_oi", "net_gex_oi"}
    assert p0["net_gex_oi"] == -50.0   # mapped from sum_gex_oi


def test_hist_eod_series_missing_category(key, monkeypatch):
    raw = _make_eod_zip(category="gex_full")
    monkeypatch.setattr(gexbot, "_get_bytes", lambda path, timeout=120: raw)
    with pytest.raises(RuntimeError, match="categor"):
        gexbot.hist_eod_series("SPX", "zero")   # gex_zero not in the ZIP
