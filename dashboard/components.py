"""Streamlit UI building blocks — styled to match the reference layout."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from . import styles as S


# ── formatting helpers ─────────────────────────────────────────────────────
def _fmt_money(x: Optional[float]) -> str:
    if x is None or pd.isna(x):
        return "—"
    if abs(x) >= 1_000_000_000:
        return f"${x / 1e9:,.2f}B"
    if abs(x) >= 1_000_000:
        return f"${x / 1e6:,.2f}M"
    if abs(x) >= 1_000:
        return f"${x / 1e3:,.1f}K"
    return f"${x:,.2f}"


def _fmt_level(x: Optional[float]) -> str:
    return "—" if x is None or pd.isna(x) else f"${x:,.0f}"


def _pct_from_spot(level: Optional[float], spot: float) -> str:
    if level is None or pd.isna(level):
        return ""
    pct = (level - spot) / spot * 100
    color = "pos" if pct >= 0 else "neg"
    return f"<span class='delta {color}'>{pct:+.2f}%</span>"


# ── page title ─────────────────────────────────────────────────────────────
def page_title(ticker: str, is_demo: bool) -> None:
    badge = "<span class='badge demo'>DEMO DATA</span>" if is_demo \
            else "<span class='badge live'>● LIVE</span>"
    st.markdown(
        f"<div class='pl-title'><span class='tk'>{ticker}</span>"
        f"<span class='sub'>Gamma &amp; Beta Exposure</span>{badge}</div>",
        unsafe_allow_html=True,
    )


# ── metric ribbon ──────────────────────────────────────────────────────────
def _cell(cls: str, label: str, value: str, sub: str = "") -> str:
    sub_html = f"<div class='sub'>{sub}</div>" if sub else ""
    return (
        f"<div class='pl-cell {cls}'>"
        f"<div class='lbl'>{label}</div>"
        f"<div class='val'>{value}</div>"
        f"{sub_html}"
        f"</div>"
    )


def metric_strip(spot: float, levels: dict, totals: dict) -> None:
    def rel(k: str) -> str:
        return _pct_from_spot(levels.get(k), spot)

    def flip_sub(k: str) -> str:
        v = levels.get(k)
        if v is None:
            return ""
        return "Above Flip" if spot > v else "Below Flip"

    gex = totals.get("gex", 0.0)
    vanna_t = totals.get("vanna", 0.0)
    charm_t = totals.get("charm", 0.0)

    cells = [
        _cell("spot",  "SPOT PRICE",    f"${spot:,.2f}"),
        _cell("call",  "CALL WALL",     _fmt_level(levels.get("call_wall")),  rel("call_wall")),
        _cell("put",   "PUT WALL",      _fmt_level(levels.get("put_wall")),   rel("put_wall")),
        _cell("gamma", "GAMMA FLIP",    _fmt_level(levels.get("gamma_flip")), flip_sub("gamma_flip")),
        _cell("pain",  "MAX PAIN",      _fmt_level(levels.get("max_pain")),   rel("max_pain")),
        _cell("delta", "DELTA WALL",    _fmt_level(levels.get("delta_wall")), rel("delta_wall")),
        _cell("delta", "MAJOR NEG Δ",   _fmt_level(levels.get("major_neg_delta")), rel("major_neg_delta")),
        _cell("gamma", "DELTA FLIP",    _fmt_level(levels.get("delta_flip")),
              "Dealers Sell" if levels.get("delta_flip") and spot > levels["delta_flip"] else
              ("Dealers Buy" if levels.get("delta_flip") else "")),
        _cell("spot",  "GEX",           _fmt_money(gex),
              f"<span class='dot' style='color:{S.GREEN if gex >= 0 else S.RED}'></span>"
              f"{'Long γ' if gex >= 0 else 'Short γ'}"),
        _cell("spot",  "VANNA",         f"{vanna_t:,.2f}",
              f"<span class='dot' style='color:{S.GREEN if vanna_t >= 0 else S.RED}'></span>"
              f"{'Bullish' if vanna_t >= 0 else 'Bearish'}"),
        _cell("spot",  "CHARM",         f"{charm_t:,.2f}",
              f"<span class='dot' style='color:{S.MUTED}'></span>Neutral"),
    ]
    st.markdown(f"<div class='pl-ribbon'>{''.join(cells)}</div>", unsafe_allow_html=True)


# ── GEX + DEX bar pair ─────────────────────────────────────────────────────
def _bar_colors(values, spot_row_idx: Optional[int], positive_color: str, negative_color: str):
    colors, opacities, widths = [], [], []
    for i, v in enumerate(values):
        colors.append(positive_color if v >= 0 else negative_color)
        opacities.append(1.0 if i == spot_row_idx else 0.85)
        widths.append(2 if i == spot_row_idx else 0)
    return colors, opacities, widths


def gex_dex_pair(
    gex: pd.DataFrame,
    dex: pd.DataFrame,
    spot: float,
    levels: dict,
    strike_window: int = 20,
) -> go.Figure:
    step = float(gex["strike"].diff().dropna().median()) if len(gex) > 1 else 1.0
    lo, hi = spot - strike_window * step, spot + strike_window * step
    g = gex[(gex["strike"] >= lo) & (gex["strike"] <= hi)].sort_values("strike")
    d = dex[(dex["strike"] >= lo) & (dex["strike"] <= hi)].sort_values("strike")

    def _atm_idx(df):
        if df.empty:
            return None
        return int((df["strike"] - spot).abs().to_numpy().argmin())

    g_atm = _atm_idx(g)
    d_atm = _atm_idx(d)

    g_colors, g_opac, g_lw = _bar_colors(g["gex"].to_numpy(), g_atm, S.GREEN_SOFT, S.RED_SOFT)
    d_colors, d_opac, d_lw = _bar_colors(d["dex"].to_numpy(), d_atm, S.GREEN_SOFT, S.RED_SOFT)

    fig = make_subplots(
        rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.04,
        subplot_titles=("GEX", "DEX"),
    )
    fig.add_trace(
        go.Bar(
            y=g["strike"], x=g["gex"], orientation="h",
            marker=dict(color=g_colors, opacity=g_opac,
                        line=dict(color=S.TEXT_STRONG, width=g_lw)),
            name="GEX", showlegend=False,
            hovertemplate="strike=%{y:$,.0f}<br>gex=%{x:$,.0f}<extra></extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Bar(
            y=d["strike"], x=d["dex"], orientation="h",
            marker=dict(color=d_colors, opacity=d_opac,
                        line=dict(color=S.TEXT_STRONG, width=d_lw)),
            name="DEX", showlegend=False,
            hovertemplate="strike=%{y:$,.0f}<br>dex=%{x:$,.0f}<extra></extra>",
        ),
        row=1, col=2,
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=680,
        margin=dict(l=48, r=48, t=44, b=30),
        bargap=0.18,
        font=dict(color=S.TEXT, family="Inter, system-ui, sans-serif", size=11),
    )
    for col in (1, 2):
        fig.update_xaxes(
            gridcolor=S.GRID, zerolinecolor=S.BORDER, zerolinewidth=1,
            tickfont=dict(color=S.MUTED, size=10),
            showline=False, row=1, col=col,
        )
        fig.update_yaxes(
            gridcolor=S.GRID, tickformat="$,.0f",
            tickfont=dict(color=S.MUTED, size=10),
            showline=False, row=1, col=col,
        )
    # Subplot titles → muted, tracked out
    for ann in fig.layout.annotations:
        ann.font = dict(color=S.MUTED, size=11, family="Inter, system-ui")

    # Reference lines
    for c in (1, 2):
        fig.add_hline(y=spot, line_dash="dot", line_color=S.YELLOW,
                      opacity=0.55, line_width=1, row=1, col=c)
        if levels.get("call_wall"):
            fig.add_hline(y=levels["call_wall"], line_dash="dash",
                          line_color=S.COLOR_CALL, opacity=0.35, line_width=1, row=1, col=c)
        if levels.get("put_wall"):
            fig.add_hline(y=levels["put_wall"], line_dash="dash",
                          line_color=S.COLOR_PUT, opacity=0.35, line_width=1, row=1, col=c)
        if levels.get("gamma_flip"):
            fig.add_hline(y=levels["gamma_flip"], line_dash="dashdot",
                          line_color=S.COLOR_GAMMA, opacity=0.5, line_width=1, row=1, col=c)
    return fig


# ── heat map ───────────────────────────────────────────────────────────────
def exposure_heatmap(
    long_df: pd.DataFrame,
    value_col: str,
    spot: float,
    levels: Optional[dict] = None,
    strike_window: int = 20,
    title: str = "GEX heat map",
) -> go.Figure:
    levels = levels or {}
    if long_df.empty:
        return go.Figure()

    strikes = pd.Series(sorted(long_df["strike"].unique()))
    step = float(strikes.diff().dropna().median()) if len(strikes) > 1 else 1.0
    lo, hi = spot - strike_window * step, spot + strike_window * step
    df = long_df[(long_df["strike"] >= lo) & (long_df["strike"] <= hi)].copy()
    if df.empty:
        return go.Figure()

    df["expiry_label"] = pd.to_datetime(df["expiry"]).dt.strftime("%Y-%m-%d")
    grid = (
        df.pivot_table(index="strike", columns="expiry_label", values=value_col, aggfunc="sum")
        .sort_index()
        .sort_index(axis=1)
    )
    zmax = float(max(abs(grid.min().min()), abs(grid.max().max())) or 1.0)

    fig = go.Figure(
        data=go.Heatmap(
            z=grid.values,
            x=grid.columns.tolist(),
            y=grid.index.tolist(),
            colorscale=[
                (0.0,  S.RED),
                (0.35, "#3a0f14"),
                (0.5,  S.BG),
                (0.65, "#0f3a1a"),
                (1.0,  S.GREEN),
            ],
            zmid=0.0, zmin=-zmax, zmax=zmax,
            xgap=1, ygap=1,
            colorbar=dict(
                title=dict(text=value_col.upper(), font=dict(color=S.MUTED, size=10)),
                tickfont=dict(color=S.MUTED, size=9),
                outlinewidth=0, thickness=10,
            ),
            hovertemplate="strike=%{y:$,.0f}<br>expiry=%{x}<br>" + value_col + "=%{z:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=680, margin=dict(l=48, r=48, t=44, b=30),
        xaxis=dict(title="", gridcolor=S.GRID, tickfont=dict(color=S.MUTED, size=10)),
        yaxis=dict(title="", gridcolor=S.GRID, tickformat="$,.0f",
                   tickfont=dict(color=S.MUTED, size=10)),
        title=dict(text=title, x=0.02, y=0.98,
                   font=dict(color=S.MUTED, size=11, family="Inter, system-ui")),
        font=dict(color=S.TEXT),
    )
    fig.add_hline(y=spot, line_dash="dot", line_color=S.YELLOW, opacity=0.6, line_width=1)
    for k, color in (
        ("call_wall", S.COLOR_CALL),
        ("put_wall", S.COLOR_PUT),
        ("gamma_flip", S.COLOR_GAMMA),
    ):
        v = levels.get(k)
        if v is not None:
            fig.add_hline(y=v, line_dash="dash", line_color=color, opacity=0.4, line_width=1)
    return fig


# ── regime + IV panel ──────────────────────────────────────────────────────
def _regime_class(label: str) -> str:
    return {"LONG GAMMA": "long", "SHORT GAMMA": "short"}.get(label, "trans")


def _spectrum_bar(iv_snap) -> str:
    """Horizontal IV spectrum: HV10/HV30/HV60 anchor a range, IV ATM overlays."""
    values = {
        "hv10": iv_snap.hv10, "hv30": iv_snap.hv30,
        "hv60": iv_snap.hv60, "iv":   iv_snap.iv_atm,
    }
    finite = [v for v in values.values() if v is not None and np.isfinite(v)]
    if not finite:
        return ""
    lo, hi = min(finite), max(finite)
    span = max(hi - lo, 1e-6)
    # pad so extreme markers aren't glued to the edge
    lo -= span * 0.15
    hi += span * 0.15
    span = hi - lo

    def pos(v):
        return max(0.0, min(1.0, (v - lo) / span)) * 100

    markers = ""
    for key, label in (("hv10", "HV10"), ("hv30", "HV30"),
                       ("hv60", "HV60"), ("iv", "IV")):
        v = values[key]
        if v is None or not np.isfinite(v):
            continue
        markers += (
            f"<span class='marker {key}' style='left:{pos(v):.2f}%' "
            f"data-label='{label}' data-val='{v*100:.1f}%'></span>"
        )
    return f"<div class='pl-spectrum'>{markers}</div>"


def regime_panel(regime, iv_snap, ticker: str, spot: float) -> None:
    st.markdown(
        f"<div class='pl-panel'>"
        f"<h3>Gamma Regime</h3>"
        f"<div class='spot-line'><span class='price'>${spot:,.2f}</span>"
        f"<span class='tk'>{ticker}</span></div>"
        f"<div class='pl-regime {_regime_class(regime.label)}'>"
        f"<span class='dot'></span>{regime.label}</div>"
        f"<div class='reading'>{regime.reading}</div>"
        f"{_trigger_row('G-FLIP', regime.g_flip, regime.gap_pct)}"
        f"</div>",
        unsafe_allow_html=True,
    )

    prem = iv_snap.premium
    prem_class = "expensive" if prem > 0.10 else "cheap" if prem < -0.10 else "neutral"
    label = "IV CARA" if prem > 0 else "IV BARATA"
    ratio = iv_snap.ratio_iv_hv30 if iv_snap.ratio_iv_hv30 and np.isfinite(iv_snap.ratio_iv_hv30) else 1.0
    ts = iv_snap.term_structure
    ts_cls = "warn" if ts == "BACKWARDATION" else "pos" if ts == "CONTANGO" else ""

    st.markdown(
        f"<div class='pl-panel'>"
        f"<h3>IV Premium</h3>"
        f"<div class='pl-iv-hero {prem_class}'>"
        f"<div class='num'>{prem*100:+.1f}%</div>"
        f"<div class='lbl'>{label}</div>"
        f"<div class='ratio'>Ratio IV/HV30: <b>{ratio:.2f}×</b></div>"
        f"</div>"
        f"{_spectrum_bar(iv_snap)}"
        f"<div class='reading'>{iv_snap.reading}</div>"
        f"<div style='height:8px'></div>"
        f"{_statrow('ATM IV', f'{iv_snap.iv_atm*100:.2f}%')}"
        f"{_statrow('IV PREMIUM', f'{prem*100:+.1f}%', 'neg' if prem>0 else 'pos')}"
        f"{_statrow('TERM STRUCTURE', ts, ts_cls)}"
        f"{_statrow('HV10 / HV30 / HV60', f'{iv_snap.hv10*100:.1f}% · {iv_snap.hv30*100:.1f}% · {iv_snap.hv60*100:.1f}%')}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _trigger_row(label: str, val: Optional[float], gap_pct: Optional[float]) -> str:
    if val is None:
        return ""
    delta = ""
    if gap_pct is not None and np.isfinite(gap_pct):
        cls = "pos" if gap_pct >= 0 else "neg"
        delta = f"<div class='delta {cls}'>{gap_pct*100:+.2f}%</div>"
    return (
        f"<div class='pl-triggers'>"
        f"<div class='pl-trigger'><div class='lbl'>{label}</div>"
        f"<div class='val'>${val:,.2f}</div>{delta}</div>"
        f"<div class='pl-trigger'><div class='lbl'>VOL TRIGGER</div>"
        f"<div class='val'>${val:,.2f}</div>{delta}</div>"
        f"</div>"
    )


def _statrow(label: str, value: str, cls: str = "") -> str:
    return (
        f"<div class='pl-statrow'>"
        f"<span class='lbl'>{label}</span>"
        f"<span class='val {cls}'>{value}</span>"
        f"</div>"
    )


# ── beta panel ─────────────────────────────────────────────────────────────
def beta_panel(portfolio) -> None:
    st.markdown("<div class='pl-title'><span class='tk'>Portfolio</span>"
                "<span class='sub'>Beta Exposure vs SPY</span></div>",
                unsafe_allow_html=True)
    df = portfolio.as_frame()
    if df.empty:
        st.info("Add positions to see beta exposure.")
        return
    display = df.assign(
        notional=df["notional"].map(_fmt_money),
        beta_dollars=df["beta_dollars"].map(_fmt_money),
        beta_adj_delta_dollars=df["beta_adj_delta_dollars"].map(_fmt_money),
        beta=df["beta"].round(2),
        price=df["price"].round(2),
    )[["ticker", "shares", "delta_shares", "price", "beta",
       "notional", "beta_dollars", "beta_adj_delta_dollars"]]
    st.dataframe(display, hide_index=True, use_container_width=True)

    cells = [
        _cell("spot",  "PORTFOLIO β",  f"{portfolio.portfolio_beta:.2f}"),
        _cell("call",  "β-DOLLARS",    _fmt_money(portfolio.beta_dollars)),
        _cell("spot",  "NET NOTIONAL", _fmt_money(portfolio.net_notional)),
        _cell("delta", "β-ADJ Δ $",    _fmt_money(portfolio.beta_adj_delta_dollars)),
    ]
    st.markdown(f"<div class='pl-ribbon'>{''.join(cells)}</div>", unsafe_allow_html=True)
