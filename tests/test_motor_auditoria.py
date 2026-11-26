"""Pruebas de la auditoría del motor cuantitativo (2026-11).

Datos FIJOS y reproducibles (sin aleatoriedad). Los "fakes" sustituyen al
proveedor solo dentro de las pruebas; en producción el proveedor demo está
bloqueado (ver test_demo_bloqueado_en_produccion).
"""
from __future__ import annotations

import math
import os
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from api import main
from profitlab import instruments, volume_profile as vp
from profitlab.data import polygon as poly

NY = "America/New_York"


# ── utilidades de datos fijos ────────────────────────────────────────────────
def _future(days: int) -> pd.Timestamp:
    return pd.Timestamp.now(tz=NY).tz_localize(None).normalize() + pd.Timedelta(days=days)


def _chain(spot: float, oi_scale: float = 1.0, iv: float = 0.20, n_exp: int = 3,
           step: float | None = None) -> pd.DataFrame:
    """Cadena determinista alrededor de `spot`: calls con más OI arriba del
    spot y puts con más OI abajo (perfil típico)."""
    step = step or round(spot * 0.01, 2)
    rows = []
    for e in range(n_exp):
        exp = _future(7 * (e + 1))
        for k in range(-10, 11):
            strike = round(spot + k * step, 2)
            for typ in ("call", "put"):
                base = max(1000 + 200 * k if typ == "call" else 1000 - 200 * k, 50.0)
                rows.append({"strike": strike, "expiry": exp, "type": typ,
                             "oi": base * oi_scale, "iv": iv, "bid": 1.0, "ask": 1.2,
                             "last": 1.1, "volume": 10.0 * (e + 1)})
    df = pd.DataFrame(rows)
    df["iv_imputed"] = False
    return df


def _session(date: str, closes, vols=None, start="09:30") -> pd.DataFrame:
    ts = pd.date_range(f"{date} {start}", periods=len(closes), freq="1min")
    c = np.asarray(closes, dtype=float)
    v = np.asarray(vols if vols is not None else [1000.0] * len(c), dtype=float)
    return pd.DataFrame({"ts": ts, "open": c, "high": c + 0.05, "low": c - 0.05,
                         "close": c, "volume": v})


@pytest.fixture(autouse=True)
def _limpia_cache():
    main._CACHE.clear()
    yield
    main._CACHE.clear()


def _fake_options(spots: dict, chains: dict):
    def fake(symbol, max_expiries=4, strike_pct=None):
        inst = instruments.resolve(symbol)
        und = inst.options
        m = main._META.get()
        if m is not None:
            m["instrument"] = inst.to_dict()
            m["options_underlying"] = und
            m["spot"] = spots[und]
            m["spot_source"] = "aggregates"
        return main.OptCtx(inst, und, chains[und].copy(), spots[und], "aggregates", {"ok": True})
    return fake


# ── 1. Identificación de instrumentos ────────────────────────────────────────
@pytest.mark.parametrize("sym,opt,bars", [
    ("XAUUSD", "GLD", "GLD"), ("NAS100", "NDX", "QQQ"), ("US30", "DIA", "DIA"),
    ("SPX500", "SPX", "SPY"), ("WTI", "USO", "USO"),
])
def test_cfd_mapean_a_subyacentes_y_se_declaran_proxy(sym, opt, bars):
    i = instruments.resolve(sym)
    assert (i.options, i.bars, i.proxy, i.kind) == (opt, bars, True, "cfd")
    assert i.note


def test_indice_usa_etf_para_volumen_y_acciones_son_directas():
    assert instruments.resolve("SPX").bars == "SPY"
    assert instruments.resolve("spx").options == "SPX"
    q = instruments.resolve("QQQ")
    assert (q.options, q.bars, q.proxy) == ("QQQ", "QQQ", False)
    es = instruments.resolve("ES")
    assert (es.options, es.fallback, es.bars) == ("SPX", "SPY", "SPY")


# ── 2. Zona horaria y cadena de opciones del proveedor ───────────────────────
def test_barras_polygon_se_convierten_a_hora_de_nueva_york():
    # 2026-11-24 14:30 UTC = 09:30 en Nueva York (horario estándar, UTC−5)
    ms = int(pd.Timestamp("2026-11-24 14:30", tz="UTC").timestamp() * 1000)
    assert poly._ms_to_ny([ms])[0] == pd.Timestamp("2026-11-24 09:30")
    # 2026-07-01 13:30 UTC = 09:30 en verano (UTC−4)
    ms = int(pd.Timestamp("2026-07-01 13:30", tz="UTC").timestamp() * 1000)
    assert poly._ms_to_ny([ms])[0] == pd.Timestamp("2026-07-01 09:30")


def _opt(strike, exp, kind, iv=0.2, oi=100):
    return {"details": {"strike_price": strike, "expiration_date": exp, "contract_type": kind},
            "open_interest": oi, "implied_volatility": iv, "greeks": {},
            "last_quote": {"bid": 1.0, "ask": 1.1}, "day": {"close": 1.05, "volume": 5}}


def test_cadena_pide_vigentes_ordenadas_y_ventana_de_strikes():
    e1 = _future(1).strftime("%Y-%m-%d")
    captured = {}

    def fake_get(path, params=None):
        captured.update(params or {})
        return {"results": [_opt(100, e1, "call"), _opt(100, e1, "put")], "next_url": None}

    with patch.dict(os.environ, {"POLYGON_API_KEY": "k"}), patch.object(poly, "_get", fake_get):
        df = poly.option_chain("QQQ", max_expiries=4, spot=100.0, strike_pct=0.10)
    assert captured["expiration_date.gte"] == pd.Timestamp.now(tz=NY).date().isoformat()
    assert captured["sort"] == "expiration_date" and captured["order"] == "asc"
    assert captured["strike_price.gte"] == 90.0 and captured["strike_price.lte"] == 110.0
    assert len(df) == 2


def test_cadena_descarta_el_vencimiento_incompleto_y_para_de_paginar():
    exps = [_future(d).strftime("%Y-%m-%d") for d in (1, 2, 3)]
    pages = [
        {"results": [_opt(100, exps[0], "call"), _opt(100, exps[0], "put"),
                     _opt(100, exps[1], "call")], "next_url": "http://x/2"},
        {"results": [_opt(100, exps[1], "put"), _opt(100, exps[2], "call")], "next_url": "http://x/3"},
        {"results": [_opt(100, exps[2], "put")], "next_url": None},
    ]
    calls = []

    def fake_get(path, params=None):
        calls.append(path)
        return pages[len(calls) - 1]

    with patch.dict(os.environ, {"POLYGON_API_KEY": "k"}), patch.object(poly, "_get", fake_get):
        df = poly.option_chain("QQQ", max_expiries=2)
    assert len(calls) == 2                                # no pidió la 3.ª página
    assert sorted(df["expiry"].dt.strftime("%Y-%m-%d").unique()) == exps[:2]


def test_cadena_solo_vencida_falla_en_vez_de_usarse():
    past = (pd.Timestamp.now(tz=NY).normalize() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    with patch.dict(os.environ, {"POLYGON_API_KEY": "k"}), \
            patch.object(poly, "_get", return_value={"results": [_opt(100, past, "call")], "next_url": None}):
        with pytest.raises(RuntimeError, match="vencimientos pasados"):
            poly.option_chain("SPX")


def test_sin_iv_real_no_se_inventa_una_constante():
    e1 = _future(3).strftime("%Y-%m-%d")
    res = {"results": [_opt(100, e1, "call", iv=None), _opt(100, e1, "put", iv=None)], "next_url": None}
    with patch.dict(os.environ, {"POLYGON_API_KEY": "k"}), patch.object(poly, "_get", return_value=res):
        df = poly.option_chain("QQQ")
    assert df.attrs["iv_missing"] is True
    assert df["iv"].isna().all()                          # antes: 0.22 fijo


def test_iv_faltante_se_rellena_con_la_mediana_del_mismo_vencimiento():
    e1, e2 = _future(3).strftime("%Y-%m-%d"), _future(10).strftime("%Y-%m-%d")
    res = {"results": [_opt(100, e1, "call", iv=0.30), _opt(101, e1, "call", iv=None),
                       _opt(100, e2, "call", iv=0.50), _opt(101, e2, "call", iv=None)],
           "next_url": None}
    with patch.dict(os.environ, {"POLYGON_API_KEY": "k"}), patch.object(poly, "_get", return_value=res):
        df = poly.option_chain("QQQ")
    by = df.groupby(df["expiry"].dt.strftime("%Y-%m-%d"))["iv"].apply(list).to_dict()
    assert by[e1] == [0.30, 0.30] and by[e2] == [0.50, 0.50]


def test_atm_iv_devuelve_none_y_no_veinte_por_ciento():
    assert main._atm_iv(pd.DataFrame({"x": []}), 100.0) is None


def test_demo_bloqueado_en_produccion():
    from profitlab import data as pdata
    with patch.dict(os.environ, {"PROFITLAB_VENDOR": "demo", "RENDER": "true"}):
        with pytest.raises(RuntimeError, match="bloqueado"):
            pdata.spot("QQQ")


# ── 3. Sesión regular y frescura ─────────────────────────────────────────────
def test_sesion_regular_y_ultimo_dia_sin_duplicados(monkeypatch):
    d1 = _session("2026-11-23", [100] * 400, start="08:00")       # premercado + sesión
    d2 = _session("2026-11-24", [101] * 400, start="09:00")
    dup = d2.iloc[[50]]
    raw = pd.concat([d1, d2, dup]).sample(frac=1.0, random_state=1)  # desordenado + duplicado
    monkeypatch.setattr(main, "_intraday_bars_fallback", lambda *a, **k: raw)
    token = main._META.set({"warnings": []})
    try:
        out = main._session_bars("SPX500")
        meta = main._META.get()
    finally:
        main._META.reset(token)
    assert out["ts"].dt.date.nunique() == 1 and str(out["ts"].dt.date.iloc[0]) == "2026-11-24"
    mins = out["ts"].dt.hour * 60 + out["ts"].dt.minute
    assert mins.min() >= 570 and mins.max() < 960
    assert out["ts"].is_unique and out["ts"].is_monotonic_increasing
    assert meta["bars_symbol"] == "SPY"                    # SPX500 → volumen de SPY
    assert any("duplicad" in w for w in meta["warnings"])


# ── 4. Aislamiento entre instrumentos y metadatos ────────────────────────────
def test_cache_y_meta_no_se_mezclan_entre_activos(monkeypatch):
    spots = {"QQQ": 600.0, "GLD": 250.0}
    chains = {"QQQ": _chain(600.0, oi_scale=3.0, iv=0.18), "GLD": _chain(250.0, oi_scale=1.0, iv=0.30)}
    monkeypatch.setattr(main, "_options", _fake_options(spots, chains))
    a = main.delta_surface("QQQ", kind="net", exp=3, window=10)
    b = main.delta_surface("XAUUSD", kind="net", exp=3, window=10)
    assert a["meta"]["options_underlying"] == "QQQ" and b["meta"]["options_underlying"] == "GLD"
    assert a["spot"] == 600.0 and b["spot"] == 250.0
    assert a["strikes"] != b["strikes"]
    assert a["meta"]["calc_version"] == main.CALC_VERSION
    assert b["meta"]["instrument"]["proxy"] is True
    assert main.delta_surface("QQQ", kind="net", exp=3, window=10) is a   # caché por activo


# ── 5. Delta Surface = exposición real ───────────────────────────────────────
def test_delta_surface_cambia_con_el_open_interest_y_sigue_la_formula(monkeypatch):
    spots = {"QQQ": 600.0, "GLD": 250.0}
    chains = {"QQQ": _chain(600.0, oi_scale=2.0), "GLD": _chain(250.0, oi_scale=2.0)}
    monkeypatch.setattr(main, "_options", _fake_options(spots, chains))
    d = main.delta_surface("QQQ", kind="net", exp=3, window=10)

    # Recalcula a mano una celda: Σ signo × delta_BS × OI × 100 × spot
    from profitlab import exposures, greeks
    ch = chains["QQQ"]
    k, e = d["strikes"][5], pd.Timestamp(d["expiries"][1])
    asof = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    t = max((e - asof).total_seconds() / 86400.0, 1.0) / 365.0
    exp_val = 0.0
    for r in ch[(ch["strike"] == k) & (ch["expiry"] == e)].itertuples():
        dl = greeks.delta(600.0, k, t, 0.045, r.iv, 0.0, r.type)
        exp_val += (-1.0 if r.type == "call" else 1.0) * dl * r.oi * 100.0 * 600.0
    assert d["z"][5][1] == pytest.approx(exp_val, rel=1e-9)

    # Duplicar el OI duplica la superficie (es exposición, no un delta teórico)
    main._CACHE.clear()
    chains["QQQ"] = _chain(600.0, oi_scale=4.0)
    d2 = main.delta_surface("QQQ", kind="net", exp=3, window=10)
    assert d2["z"][5][1] == pytest.approx(2 * d["z"][5][1], rel=1e-9)


def test_delta_surface_sin_open_interest_no_inventa(monkeypatch):
    ch = _chain(600.0)
    ch["oi"] = 0.0
    monkeypatch.setattr(main, "_options", _fake_options({"QQQ": 600.0}, {"QQQ": ch}))
    with pytest.raises(Exception, match="open interest"):
        main.delta_surface("QQQ", kind="net", exp=3, window=10)


# ── 6. Volume Profile ────────────────────────────────────────────────────────
def test_nodos_hvn_lvn_en_perfil_bimodal_conocido():
    price = list(range(100, 120))
    vol = [0, 5, 50, 90, 50, 5, 1, 1, 1, 5, 40, 100, 40, 5, 0, 0, 0, 0, 0, 0]
    n = vp.nodes(price, vol)
    assert 103 in n["hvn"] and 111 in n["hvn"]
    assert any(106 <= x <= 108 for x in n["lvn"])
    assert all(x < 114 for x in n["lvn"])                  # bordes vacíos no son LVN


def test_volume_profile_api_declara_estimacion_y_niveles(monkeypatch):
    closes = [100 + 0.01 * i for i in range(120)] + [101.2] * 60
    bars = _session("2026-11-24", closes, vols=[100.0] * 120 + [5000.0] * 60)
    monkeypatch.setattr(main, "_intraday_bars_fallback", lambda *a, **k: bars)
    r = main.volume_profile("QQQ", bins=24, sessions=1, value_area=0.7)
    assert abs(r["poc"] - 101.2) < 0.1                     # donde se concentró el volumen
    assert r["val"] <= r["poc"] <= r["vah"]
    assert sum(r["volume"]) == pytest.approx(100.0 * 120 + 5000.0 * 60)
    assert "volume_by_price" in r["meta"]["estimated"]
    assert r["meta"]["bars_symbol"] == "QQQ"


def test_volume_profile_sin_volumen_es_error_claro(monkeypatch):
    bars = _session("2026-11-24", [100.0] * 50, vols=[0.0] * 50)
    monkeypatch.setattr(main, "_intraday_bars_fallback", lambda *a, **k: bars)
    with pytest.raises(Exception, match="volumen"):
        main.volume_profile("QQQ", bins=24, sessions=1, value_area=0.7)


# ── 7. Volatility Drift ──────────────────────────────────────────────────────
def test_volatility_drift_reproduce_la_formula_y_no_inventa_iv(monkeypatch):
    closes = [100 * math.exp(0.001 * ((-1) ** i) * (1 + (i % 7) / 7)) for i in range(60)]
    bars = _session("2026-11-24", closes)
    monkeypatch.setattr(main, "_intraday_bars_fallback", lambda *a, **k: bars)

    def no_chain(*a, **k):
        raise RuntimeError("sin cadena")
    monkeypatch.setattr(main, "_options", no_chain)

    r = main.volatility_drift("QQQ", window=10)
    s = pd.Series(closes)
    exp = (np.log(s / s.shift(1)).rolling(10).std(ddof=1) * math.sqrt(252 * 390) * 100).iloc[-1]
    assert r["arv"][-1] == pytest.approx(exp, rel=1e-12)
    assert r["iv"] is None                                 # antes: 20 % fijo
    assert r["summary"]["direction"] in ("up", "down", "flat")
    assert any("IV" in w for w in r["meta"]["warnings"])


def test_volatility_drift_datos_insuficientes(monkeypatch):
    bars = _session("2026-11-24", [100.0, 100.1, 100.2])
    monkeypatch.setattr(main, "_intraday_bars_fallback", lambda *a, **k: bars)
    with pytest.raises(Exception, match="insuficientes"):
        main.volatility_drift("QQQ", window=20)


# ── 8. Net Drift ─────────────────────────────────────────────────────────────
def test_net_drift_totales_reales_y_curva_estimada(monkeypatch):
    ch = _chain(600.0)
    monkeypatch.setattr(main, "_options", _fake_options({"QQQ": 600.0}, {"QQQ": ch}))
    closes = [600 + (1 if i % 3 else -1) * 0.1 * i for i in range(90)]
    monkeypatch.setattr(main, "_intraday_bars_fallback",
                        lambda *a, **k: _session("2026-11-24", closes))
    r = main.net_drift("QQQ", exp=3)
    mid = (ch["bid"] + ch["ask"]) / 2
    notional = ch["volume"] * mid * 100
    call_tot = float(notional[ch["type"] == "call"].sum())
    put_tot = float(notional[ch["type"] == "put"].sum())
    assert r["totals"]["call_drift"] == pytest.approx(call_tot)
    assert r["totals"]["put_drift"] == pytest.approx(-put_tot)
    assert r["call_drift"][-1] == pytest.approx(call_tot)  # la curva acaba en el total real
    assert np.all(np.diff(r["call_drift"]) >= -1e-9)        # acumulada, no decrece
    assert "curve" in r["meta"]["estimated"]


# ── 9. Agrupación de strikes (sin inventar datos) ────────────────────────────
def test_agrupar_strikes_conserva_la_exposicion_total():
    exp = _future(7)
    ks = np.arange(6900, 7400, 5.0)                       # 100 strikes de 5 pts
    grid = pd.DataFrame({"strike": ks, "expiry": exp,
                         "dex": np.where(ks % 25 == 0, 1000.0, 10.0)})
    w = main._bucket_width(grid["strike"], max_rows=40)
    assert w == 12.5                                       # 5 → 10 → 12.5 (primer ancho ≥ 495/40)
    out = main._bucket(grid, "dex", w)
    assert out["strike"].nunique() <= 41
    assert out["dex"].sum() == pytest.approx(grid["dex"].sum())


def test_sin_agrupar_cuando_hay_pocos_strikes():
    assert main._bucket_width(np.arange(100, 130, 1.0), max_rows=40) is None
