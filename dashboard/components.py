"""Streamlit UI building blocks — styled to match the reference layout."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from . import styles as S
from . import logos as _logos
from . import treemap as _treemap


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


def _pct_chip(pct: float) -> str:
    cls = "pos" if pct >= 0 else "neg"
    return f"<span class='delta {cls}'>{pct*100:+.2f}%</span>"


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


# ── heat map (table-style, matches reference) ──────────────────────────────
def _fmt_millions(x: float) -> str:
    ax = abs(x)
    if ax >= 1_000_000_000:
        return f"{x / 1e9:,.1f}B"
    if ax >= 1_000_000:
        return f"{x / 1e6:,.1f}M"
    if ax >= 1_000:
        return f"{x / 1e3:,.1f}K"
    return f"{x:,.0f}"


def exposure_heatmap(
    long_df: pd.DataFrame,
    value_col: str,
    spot: float,
    levels: Optional[dict] = None,
    strike_window: int = 20,
    title: str = "GAMMA EXPOSURE",
    asof: Optional[pd.Timestamp] = None,
) -> go.Figure:
    """Table-style GEX/DEX grid: rows = strikes, columns = days-to-expiry,
    each cell shows the numeric value with a color-coded background."""
    levels = levels or {}
    if long_df.empty:
        return go.Figure()

    strikes = pd.Series(sorted(long_df["strike"].unique()))
    step = float(strikes.diff().dropna().median()) if len(strikes) > 1 else 1.0
    lo, hi = spot - strike_window * step, spot + strike_window * step
    df = long_df[(long_df["strike"] >= lo) & (long_df["strike"] <= hi)].copy()
    if df.empty:
        return go.Figure()

    # Column key: days-to-expiry (0D, 1D, …) relative to `asof`.
    asof = asof or pd.Timestamp.now("UTC").tz_localize(None).normalize()
    exp_dates = pd.to_datetime(df["expiry"])
    df["dte"] = (exp_dates - asof).dt.days.clip(lower=0)
    df["dte_label"] = df["dte"].apply(lambda d: f"{d}D")

    dte_order = (
        df[["dte", "dte_label"]].drop_duplicates().sort_values("dte")["dte_label"].tolist()
    )
    grid = (
        df.pivot_table(index="strike", columns="dte_label", values=value_col, aggfunc="sum")
        .reindex(columns=dte_order)
        .sort_index(ascending=False)  # highest strike at top like the reference
    )
    z = grid.values
    zmax = float(np.nanmax(np.abs(z)) or 1.0)

    # Text per cell (only for finite values), muted for magnitudes < 0.5M
    text = np.empty_like(z, dtype=object)
    text_color = np.empty_like(z, dtype=object)
    for i in range(z.shape[0]):
        for j in range(z.shape[1]):
            v = z[i, j]
            if np.isnan(v):
                text[i, j] = ""
                text_color[i, j] = "rgba(0,0,0,0)"
            else:
                text[i, j] = _fmt_millions(v)
                text_color[i, j] = "rgba(226,232,240,0.95)"

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=grid.columns.tolist(),
            y=grid.index.tolist(),
            text=text,
            texttemplate="%{text}",
            textfont=dict(color=S.TEXT_STRONG, size=11, family="Inter, system-ui"),
            # Reference uses BLUE for +GEX and RED for -GEX (dealer sign),
            # with near-zero blending into the panel background.
            colorscale=[
                (0.0,  "#7f1d1d"),   # -zmax → deep red
                (0.30, "#ef4444"),   # red
                (0.48, "#0b1220"),   # near zero → panel bg
                (0.52, "#0b1220"),
                (0.70, "#3b82f6"),   # blue
                (1.0,  "#1e3a8a"),   # +zmax → deep blue
            ],
            zmid=0.0, zmin=-zmax, zmax=zmax,
            xgap=2, ygap=2,
            showscale=True,
            colorbar=dict(
                title=dict(text=value_col.upper(), font=dict(color=S.MUTED, size=10)),
                tickfont=dict(color=S.MUTED, size=9),
                outlinewidth=0, thickness=8, len=0.5,
                tickformat=".2s",
            ),
            hovertemplate=(
                "strike=%{y:$,.0f}<br>dte=%{x}<br>"
                + value_col + "=%{z:,.0f}<extra></extra>"
            ),
        )
    )
    row_h = 26
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=max(420, min(920, row_h * len(grid.index) + 100)),
        margin=dict(l=64, r=48, t=48, b=24),
        xaxis=dict(
            title="", side="top",
            tickfont=dict(color=S.MUTED, size=11, family="Inter, system-ui"),
            showgrid=False, showline=False, ticks="",
        ),
        yaxis=dict(
            title="", autorange="reversed",  # already sorted desc, but ensure
            tickformat="$,.0f",
            tickfont=dict(color=S.MUTED, size=11, family="Inter, system-ui"),
            showgrid=False, showline=False, ticks="",
        ),
        title=dict(text=title, x=0.005, y=0.995, xanchor="left", yanchor="top",
                   font=dict(color=S.MUTED, size=11, family="Inter, system-ui")),
        font=dict(color=S.TEXT, family="Inter, system-ui"),
    )
    # Spot row highlight: overlay a border rectangle at y == closest strike to spot.
    if len(grid.index) > 0:
        closest = min(grid.index.tolist(), key=lambda s: abs(s - spot))
        fig.add_shape(
            type="rect",
            xref="x", yref="y",
            x0=-0.5, x1=len(grid.columns) - 0.5,
            y0=closest - step / 2, y1=closest + step / 2,
            line=dict(color=S.YELLOW, width=1.5),
            fillcolor="rgba(250,204,21,0.06)",
            layer="above",
        )
        fig.add_annotation(
            xref="paper", yref="y",
            x=-0.01, y=closest, xanchor="right", yanchor="middle",
            text=f"<b>${closest:,.0f}</b> SPOT",
            showarrow=False,
            font=dict(color=S.YELLOW, size=10, family="Inter, system-ui"),
        )
    # Key-level markers on the y-axis
    for k, color, label in (
        ("call_wall", S.COLOR_CALL, "CW"),
        ("put_wall", S.COLOR_PUT, "PW"),
        ("gamma_flip", S.COLOR_GAMMA, "γ-FLIP"),
    ):
        v = levels.get(k)
        if v is None or not (grid.index.min() <= v <= grid.index.max()):
            continue
        fig.add_annotation(
            xref="paper", yref="y",
            x=1.01, y=v, xanchor="left", yanchor="middle",
            text=f"<b>{label}</b>",
            showarrow=False,
            font=dict(color=color, size=10, family="Inter, system-ui"),
        )
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


# ── OI heat map (calls vs puts) ────────────────────────────────────────────
def oi_heatmap(
    long_df: pd.DataFrame,
    spot: float,
    levels: Optional[dict] = None,
    strike_window: int = 20,
    mode: str = "net",             # "net" | "pct" | "total"
    asof: Optional[pd.Timestamp] = None,
) -> go.Figure:
    """Table-style OI heat map. `mode`:
      - "net"   → net OI (call − put), calls green / puts red
      - "pct"   → cell share of total OI (both signs)
      - "total" → total OI, single-hue"""
    levels = levels or {}
    if long_df.empty:
        return go.Figure()

    strikes = np.sort(long_df["strike"].unique())
    step = float(np.median(np.diff(strikes))) if len(strikes) > 1 else 1.0
    lo, hi = spot - strike_window * step, spot + strike_window * step
    df = long_df[(long_df["strike"] >= lo) & (long_df["strike"] <= hi)].copy()
    if df.empty:
        return go.Figure()

    asof = asof or pd.Timestamp.now("UTC").tz_localize(None).normalize()
    df["expiry"] = pd.to_datetime(df["expiry"])
    df["dte"] = (df["expiry"] - asof).dt.days.clip(lower=0)
    df["dte_label"] = df["dte"].apply(lambda d: f"{d}D")
    dte_order = df[["dte", "dte_label"]].drop_duplicates().sort_values("dte")["dte_label"].tolist()

    if mode == "pct":
        value_col, title, fmt = "pct_total_oi", "% OF TOTAL OI", "pct"
    elif mode == "total":
        value_col, title, fmt = "total_oi", "TOTAL OPEN INTEREST", "int"
    else:
        value_col, title, fmt = "net_oi", "NET OPEN INTEREST (CALLS − PUTS)", "int"

    grid = (
        df.pivot_table(index="strike", columns="dte_label", values=value_col, aggfunc="sum")
        .reindex(columns=dte_order).sort_index(ascending=False)
    )
    z = grid.values
    zmax = float(np.nanmax(np.abs(z)) or 1.0)

    def _fmt(v):
        if np.isnan(v):
            return ""
        if fmt == "pct":
            return f"{v*100:.1f}%"
        if fmt == "int":
            return _fmt_millions(v).rstrip("M") if abs(v) >= 1e6 else f"{v:,.0f}"
        return _fmt_millions(v)

    text = np.array([[_fmt(v) for v in row] for row in z], dtype=object)

    if mode == "total":
        colorscale = [(0.0, "#0b1220"), (1.0, "#3b82f6")]
        zmin, zmid = 0.0, None
    else:
        colorscale = [
            (0.0, "#7f1d1d"), (0.30, "#ef4444"),
            (0.48, "#0b1220"), (0.52, "#0b1220"),
            (0.70, S.GREEN), (1.0, "#14532d"),
        ]
        zmin, zmid = -zmax, 0.0

    fig = go.Figure(data=go.Heatmap(
        z=z, x=grid.columns.tolist(), y=grid.index.tolist(),
        text=text, texttemplate="%{text}",
        textfont=dict(color=S.TEXT_STRONG, size=11, family="Inter, system-ui"),
        colorscale=colorscale, zmid=zmid, zmin=zmin, zmax=zmax,
        xgap=2, ygap=2,
        colorbar=dict(title=dict(text=title, font=dict(color=S.MUTED, size=10)),
                      tickfont=dict(color=S.MUTED, size=9),
                      outlinewidth=0, thickness=8, len=0.5),
        hovertemplate=("strike=%{y:$,.0f}<br>dte=%{x}<br>value=%{z:,.0f}<extra></extra>"),
    ))
    row_h = 26
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=max(420, min(920, row_h * len(grid.index) + 100)),
        margin=dict(l=64, r=48, t=48, b=24),
        xaxis=dict(title="", side="top", showgrid=False, showline=False, ticks="",
                   tickfont=dict(color=S.MUTED, size=11, family="Inter, system-ui")),
        yaxis=dict(title="", autorange="reversed", tickformat="$,.0f",
                   showgrid=False, showline=False, ticks="",
                   tickfont=dict(color=S.MUTED, size=11, family="Inter, system-ui")),
        title=dict(text=title, x=0.005, y=0.995, xanchor="left", yanchor="top",
                   font=dict(color=S.MUTED, size=11, family="Inter, system-ui")),
        font=dict(color=S.TEXT, family="Inter, system-ui"),
    )
    # Spot row + wall/flip markers same as gamma heatmap
    if len(grid.index) > 0:
        closest = min(grid.index.tolist(), key=lambda s: abs(s - spot))
        fig.add_shape(type="rect", xref="x", yref="y",
                      x0=-0.5, x1=len(grid.columns) - 0.5,
                      y0=closest - step / 2, y1=closest + step / 2,
                      line=dict(color=S.YELLOW, width=1.5),
                      fillcolor="rgba(250,204,21,0.06)", layer="above")
        fig.add_annotation(xref="paper", yref="y",
                           x=-0.01, y=closest, xanchor="right", yanchor="middle",
                           text=f"<b>${closest:,.0f}</b> SPOT", showarrow=False,
                           font=dict(color=S.YELLOW, size=10, family="Inter, system-ui"))
    return fig


# ── net delta drift curve ──────────────────────────────────────────────────
def net_drift_chart(drift: pd.DataFrame, spot: float, levels: dict) -> go.Figure:
    """Dealer net-delta profile across a spot band. Slope = hedging pressure:
    upward = dampens (long γ), downward = amplifies (short γ)."""
    x = drift["spot"].to_numpy()
    y = drift["net_delta"].to_numpy()

    fig = go.Figure()
    # Zero baseline for reference
    fig.add_hline(y=0, line=dict(color=S.BORDER, width=1))
    # Fill between the curve and zero
    fill_above = np.where(y > 0, y, 0)
    fill_below = np.where(y < 0, y, 0)
    fig.add_trace(go.Scatter(x=x, y=fill_above, mode="lines",
                             line=dict(color=S.GREEN, width=0),
                             fill="tozeroy", fillcolor="rgba(34,197,94,0.22)",
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=fill_below, mode="lines",
                             line=dict(color=S.RED, width=0),
                             fill="tozeroy", fillcolor="rgba(239,68,68,0.22)",
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines",
        line=dict(color=S.TEXT_STRONG, width=2),
        name="Net Δ$",
        hovertemplate="spot=%{x:$,.2f}<br>net Δ$=%{y:,.0f}<extra></extra>",
    ))
    fig.add_vline(x=spot, line=dict(color=S.YELLOW, width=1, dash="dash"), opacity=0.7)
    for k, color, label in (("gamma_flip", S.COLOR_GAMMA, "γ-FLIP"),
                             ("call_wall", S.COLOR_CALL, "CW"),
                             ("put_wall", S.COLOR_PUT, "PW")):
        v = levels.get(k)
        if v is None or not (x.min() <= v <= x.max()):
            continue
        fig.add_vline(x=v, line=dict(color=color, width=1, dash="dot"), opacity=0.7)
        fig.add_annotation(x=v, y=y.max(), xanchor="left", yanchor="top",
                           text=f"<b>{label}</b>", showarrow=False,
                           font=dict(color=color, size=10, family="Inter, system-ui"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=560, margin=dict(l=48, r=48, t=40, b=40),
        xaxis=dict(title="Spot Price ($)", tickformat="$,.2f",
                   gridcolor=S.GRID, tickfont=dict(color=S.MUTED, size=10)),
        yaxis=dict(title="Dealer Net Delta ($)", tickformat=".2s",
                   gridcolor=S.GRID, tickfont=dict(color=S.MUTED, size=10)),
        font=dict(color=S.TEXT, family="Inter, system-ui"),
        title=dict(text="NET DELTA DRIFT", x=0.005, y=0.99, xanchor="left",
                   font=dict(color=S.MUTED, size=11, family="Inter, system-ui")),
    )
    return fig


# ── volatility drift (term structure) ──────────────────────────────────────
def vol_drift_chart(term: pd.DataFrame) -> go.Figure:
    """IV vs DTE term-structure plot with call/put split and skew."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.72, 0.28], vertical_spacing=0.04)
    fig.add_trace(go.Scatter(
        x=term["dte"], y=term["atm_iv"] * 100, mode="lines+markers",
        line=dict(color=S.YELLOW, width=2), marker=dict(size=7),
        name="ATM IV",
        hovertemplate="dte=%{x}<br>IV=%{y:.2f}%<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=term["dte"], y=term["call_iv"] * 100, mode="lines+markers",
        line=dict(color=S.GREEN, width=1.5, dash="dot"),
        marker=dict(size=5), name="Call IV",
        hovertemplate="dte=%{x}<br>Call IV=%{y:.2f}%<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=term["dte"], y=term["put_iv"] * 100, mode="lines+markers",
        line=dict(color=S.RED, width=1.5, dash="dot"),
        marker=dict(size=5), name="Put IV",
        hovertemplate="dte=%{x}<br>Put IV=%{y:.2f}%<extra></extra>",
    ), row=1, col=1)
    # Skew subplot (put IV − call IV)
    fig.add_trace(go.Bar(
        x=term["dte"], y=term["skew"] * 100,
        marker=dict(color=np.where(term["skew"] >= 0, S.RED_SOFT, S.GREEN_SOFT),
                    line=dict(width=0)),
        name="Put−Call skew",
        hovertemplate="dte=%{x}<br>skew=%{y:.2f}%<extra></extra>",
    ), row=2, col=1)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=560, margin=dict(l=48, r=48, t=40, b=40),
        font=dict(color=S.TEXT, family="Inter, system-ui"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color=S.MUTED, size=10)),
        title=dict(text="VOLATILITY DRIFT (TERM STRUCTURE)", x=0.005, y=0.99, xanchor="left",
                   font=dict(color=S.MUTED, size=11, family="Inter, system-ui")),
    )
    for r in (1, 2):
        fig.update_xaxes(gridcolor=S.GRID, showline=False,
                         tickfont=dict(color=S.MUTED, size=10), row=r, col=1)
        fig.update_yaxes(gridcolor=S.GRID, showline=False,
                         tickfont=dict(color=S.MUTED, size=10), row=r, col=1)
    fig.update_yaxes(title="IV (%)", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(title="Skew (%)", ticksuffix="%", row=2, col=1)
    fig.update_xaxes(title="Days to Expiry", row=2, col=1)
    return fig


# ── 3D volatility surface (strike × expiry × IV) ───────────────────────────
def vol_surface(iv_grid: pd.DataFrame, spot: float, asof: pd.Timestamp) -> go.Figure:
    """3D IV surface derived from the option chain."""
    grid = iv_grid.copy()
    grid["expiry"] = pd.to_datetime(grid["expiry"])
    grid["dte"] = (grid["expiry"] - asof).dt.days.clip(lower=1)
    wide = grid.pivot_table(index="dte", columns="strike", values="iv", aggfunc="median")
    wide = wide.sort_index().sort_index(axis=1)
    if wide.empty:
        return go.Figure()
    z = wide.values * 100  # %

    fig = go.Figure(data=go.Surface(
        x=wide.columns.tolist(), y=wide.index.tolist(), z=z,
        colorscale="Turbo",
        cmin=float(np.nanmin(z)), cmax=float(np.nanmax(z)),
        colorbar=dict(title=dict(text="IV (%)", font=dict(color=S.MUTED)),
                      tickfont=dict(color=S.MUTED, size=10),
                      outlinewidth=0, thickness=10, len=0.6),
        lighting=dict(ambient=0.55, diffuse=0.75, specular=0.15,
                      roughness=0.55, fresnel=0.15),
        hovertemplate="strike=$%{x:,.0f}<br>dte=%{y:.0f}<br>IV=%{z:.2f}%<extra></extra>",
    ))

    def _axis(title, **extra):
        base = dict(gridcolor="rgba(148,163,184,0.18)", color=S.MUTED,
                    showbackground=False,
                    title=dict(text=title, font=dict(color=S.MUTED,
                                                     family="Inter, system-ui")))
        base.update(extra)
        return base

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=680, margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(
            xaxis=_axis("Strike ($)", tickprefix="$", tickformat=",.0f"),
            yaxis=_axis("Days to Expiry"),
            zaxis=_axis("IV (%)", ticksuffix="%"),
            camera=dict(eye=dict(x=1.6, y=-1.6, z=1.0)),
            aspectmode="cube",
        ),
        font=dict(color=S.TEXT, family="Inter, system-ui"),
    )
    fig.add_annotation(
        x=0, y=1.02, xref="paper", yref="paper", xanchor="left", yanchor="bottom",
        text=f"<b>IV SURFACE</b> · spot ${spot:,.2f}", showarrow=False,
        font=dict(color=S.MUTED, size=11, family="Inter, system-ui"),
    )
    return fig


# ── candlestick chart with option-level overlays ───────────────────────────
_LEVEL_STYLE = {
    "call_wall":   (S.COLOR_CALL, "Call Wall"),
    "put_wall":    (S.COLOR_PUT, "Put Wall"),
    "gamma_flip":  (S.COLOR_GAMMA, "Gamma Flip"),
    "delta_flip":  (S.COLOR_DELTA, "Delta Flip"),
    "delta_wall":  (S.COLOR_DELTA, "Delta Wall"),
    "max_pain":    (S.COLOR_MAX_PAIN, "Max Pain"),
}


def price_chart(
    bars: pd.DataFrame,
    spot: float,
    levels: dict,
    ticker: str,
    *,
    show_levels: Optional[list[str]] = None,
    band_pct: float = 0.0006,  # half-thickness of the colored band around a level
    show_bands: bool = True,
) -> go.Figure:
    """Candlestick chart + volume subplot with gamma/delta level overlays."""
    show_levels = show_levels or list(_LEVEL_STYLE.keys())

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.78, 0.22], vertical_spacing=0.02,
    )
    fig.add_trace(
        go.Candlestick(
            x=bars["ts"], open=bars["open"], high=bars["high"],
            low=bars["low"], close=bars["close"],
            increasing_line_color=S.GREEN_SOFT, decreasing_line_color=S.RED_SOFT,
            increasing_fillcolor=S.GREEN_SOFT, decreasing_fillcolor=S.RED_SOFT,
            line=dict(width=1),
            showlegend=False,
            name=ticker,
        ),
        row=1, col=1,
    )
    # Volume bars — colored by candle direction
    up = bars["close"] >= bars["open"]
    vol_colors = np.where(up, S.GREEN_SOFT, S.RED_SOFT)
    fig.add_trace(
        go.Bar(
            x=bars["ts"], y=bars["volume"],
            marker=dict(color=vol_colors, line=dict(width=0)),
            showlegend=False, name="volume",
            hovertemplate="%{y:,.0f}<extra></extra>",
        ),
        row=2, col=1,
    )

    # Level overlays
    for key in show_levels:
        v = levels.get(key)
        if v is None or not np.isfinite(v):
            continue
        color, label = _LEVEL_STYLE[key]
        if show_bands:
            band = v * band_pct
            fig.add_hrect(
                y0=v - band, y1=v + band,
                fillcolor=color, opacity=0.18,
                line_width=0, row=1, col=1,
            )
        fig.add_hline(
            y=v, line=dict(color=color, width=1.2, dash="solid"),
            opacity=0.85, row=1, col=1,
        )
        # Left-side label (annotation) so it doesn't clash with the price axis.
        fig.add_annotation(
            xref="x domain", yref="y",
            x=0.01, y=v, xanchor="left", yanchor="bottom",
            text=f"<b>{label}</b> ${v:,.2f}",
            showarrow=False,
            font=dict(color=color, size=10, family="Inter, system-ui"),
        )

    # Spot dashed line
    fig.add_hline(
        y=spot, line=dict(color=S.YELLOW, width=1, dash="dash"),
        opacity=0.55, row=1, col=1,
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=720,
        margin=dict(l=48, r=48, t=40, b=30),
        xaxis_rangeslider_visible=False,
        bargap=0.1,
        font=dict(color=S.TEXT, family="Inter, system-ui"),
        hovermode="x unified",
    )
    for r in (1, 2):
        fig.update_xaxes(gridcolor=S.GRID, showline=False,
                         tickfont=dict(color=S.MUTED, size=10), row=r, col=1)
        fig.update_yaxes(gridcolor=S.GRID, showline=False,
                         tickfont=dict(color=S.MUTED, size=10), row=r, col=1)
    fig.update_yaxes(tickformat="$,.2f", row=1, col=1)
    fig.update_yaxes(tickformat=".2s", row=2, col=1)
    return fig


# ── delta surface (3D) ─────────────────────────────────────────────────────
def delta_surface(
    spot_axis, days_axis, delta_grid, *,
    ticker: str, strike: float, iv: float, spot: float, kind: str = "call",
) -> go.Figure:
    """Rainbow surface of Black-Scholes delta over (spot, days)."""
    fig = go.Figure(
        data=go.Surface(
            x=spot_axis, y=days_axis, z=delta_grid,
            colorscale="Jet",
            cmin=float(np.nanmin(delta_grid)),
            cmax=float(np.nanmax(delta_grid)),
            colorbar=dict(
                title=dict(text="Δ", font=dict(color=S.MUTED)),
                tickfont=dict(color=S.MUTED, size=10),
                outlinewidth=0, thickness=10, len=0.6,
            ),
            showscale=True,
            contours=dict(
                z=dict(show=False),
                x=dict(show=True, color="rgba(255,255,255,0.05)", width=1),
                y=dict(show=True, color="rgba(255,255,255,0.05)", width=1),
            ),
            lighting=dict(ambient=0.55, diffuse=0.75, specular=0.15,
                          roughness=0.55, fresnel=0.15),
            hovertemplate=(
                "spot=$%{x:,.2f}<br>days=%{y:.0f}<br>Δ=%{z:.3f}<extra></extra>"
            ),
        )
    )
    def _axis(title: str, **extra):
        base = dict(
            gridcolor="rgba(148,163,184,0.18)",
            zerolinecolor="rgba(148,163,184,0.3)",
            color=S.MUTED,
            showbackground=False,
            title=dict(text=title, font=dict(color=S.MUTED,
                                             family="Inter, system-ui")),
        )
        base.update(extra)
        return base

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=680,
        margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(
            xaxis=_axis("Spot Price ($)", tickprefix="$", tickformat=",.0f"),
            yaxis=_axis("Time to Maturity (Days)"),
            zaxis=_axis("Delta", tickformat=".2f"),
            camera=dict(eye=dict(x=1.5, y=-1.7, z=0.9)),
            aspectmode="cube",
        ),
        font=dict(color=S.TEXT, family="Inter, system-ui"),
    )
    fig.add_annotation(
        x=0, y=1.02, xref="paper", yref="paper", xanchor="left", yanchor="bottom",
        text=(f"<b>{ticker}</b> · {kind.upper()} DELTA SURFACE · "
              f"K=${strike:,.0f} · IV={iv*100:.1f}%"),
        showarrow=False,
        font=dict(color=S.MUTED, size=11, family="Inter, system-ui"),
    )
    fig.add_annotation(
        x=1, y=1.02, xref="paper", yref="paper", xanchor="right", yanchor="bottom",
        text=f"LIVE ATM IV {iv*100:.1f}% · K ${strike:,.2f}",
        showarrow=False,
        font=dict(color=S.MUTED, size=11, family="Inter, system-ui"),
    )
    return fig


# ── market heat map ────────────────────────────────────────────────────────
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    r = int(a[0] + (b[0] - a[0]) * t)
    g = int(a[1] + (b[1] - a[1]) * t)
    bl = int(a[2] + (b[2] - a[2]) * t)
    return f"rgb({r},{g},{bl})"


def _cell_color(pct: float, cap: float = 0.04) -> str:
    """Diverging red↔black↔green based on daily % change."""
    dark = _hex_to_rgb("#0b1220")
    green = _hex_to_rgb(S.GREEN)
    red = _hex_to_rgb(S.RED)
    t = max(-1.0, min(1.0, pct / cap))
    if t >= 0:
        return _lerp(dark, green, t)
    return _lerp(dark, red, -t)


def market_heatmap(df: pd.DataFrame,
                   total_w: float = 1600.0,
                   total_h: float = 780.0,
                   prefer_remote_logos: bool = False) -> go.Figure:
    """Custom squarified treemap with per-cell brand-logo chips.

    Renders on a normal Figure using paper/axis-referenced shapes,
    images and annotations — one axis unit == one pixel-ish — so we can
    pin logos to cells that `go.Treemap` cannot expose.
    """
    if df.empty:
        return go.Figure()

    boxes, cells = _treemap.layout_sectors(df, total_w=total_w, total_h=total_h)
    _prefer_remote_logos = prefer_remote_logos  # captured by the loop below

    fig = go.Figure()

    # Sector container (thin outline + header band with the sector name)
    for box in boxes:
        # Outer container border
        fig.add_shape(
            type="rect",
            x0=box.x, y0=box.y, x1=box.x + box.w, y1=box.y + box.h,
            line=dict(color=S.BORDER, width=1),
            fillcolor="rgba(0,0,0,0)",
            layer="below",
        )
        # Sector header strip
        fig.add_shape(
            type="rect",
            x0=box.x, y0=box.y,
            x1=box.x + box.w, y1=box.y + box.header_h,
            line=dict(color=S.BORDER, width=0),
            fillcolor="rgba(15,23,42,0.75)",
            layer="below",
        )
        fig.add_annotation(
            x=box.x + 8, y=box.y + box.header_h / 2,
            xref="x", yref="y",
            xanchor="left", yanchor="middle",
            text=f"<b>{box.sector}</b>",
            showarrow=False,
            font=dict(color=S.MUTED, size=11, family="Inter, system-ui"),
        )

    # Per-ticker cells (rect + logo + ticker + %/price with density budget)
    hover_x, hover_y, hover_text = [], [], []
    for c in cells:
        fill = _cell_color(c.pct)
        fig.add_shape(
            type="rect",
            x0=c.x + 1, y0=c.y + 1, x1=c.x + c.w - 1, y1=c.y + c.h - 1,
            line=dict(color="rgba(0,0,0,0.45)", width=1),
            fillcolor=fill,
            layer="below",
        )

        # Density budget — decide what fits inside this tile before drawing.
        small = min(c.w, c.h)
        show_logo = c.w >= 40 and c.h >= 55
        show_ticker = c.w >= 32 and c.h >= 28
        show_pct = c.h >= 62 and c.w >= 44
        show_price = c.h >= 100 and c.w >= 70

        # Vertically centered stack when we have room; when we don't, we
        # anchor to the top so labels never bleed past the tile bottom.
        cx = c.x + c.w / 2
        # Adaptive font sizes
        ticker_font = int(max(9, min(small * 0.22, 26)))
        pct_font = int(max(9, ticker_font - 4))
        price_font = int(max(8, ticker_font - 6))
        chip_size = float(max(18.0, min(small * 0.30, 44.0)))

        # Compute the composed block height and center it in the tile
        gap_a, gap_b = 6.0, 3.0
        block_h = 0.0
        if show_logo:
            block_h += chip_size + gap_a
        if show_ticker:
            block_h += ticker_font + gap_b
        if show_pct:
            block_h += pct_font + gap_b
        # Price line docks at the tile bottom, not in the centered block.

        cursor_y = c.y + max(4.0, (c.h - block_h - (price_font + 6 if show_price else 0)) / 2)

        if show_logo:
            chip_x = cx - chip_size / 2
            fig.add_layout_image(dict(
                source=_logos.logo_source(c.ticker, prefer_remote=_prefer_remote_logos),
                xref="x", yref="y",
                x=chip_x, y=cursor_y,
                sizex=chip_size, sizey=chip_size,
                xanchor="left", yanchor="top",
                sizing="contain", layer="above", opacity=1.0,
            ))
            cursor_y += chip_size + gap_a

        if show_ticker:
            fig.add_annotation(
                x=cx, y=cursor_y, xref="x", yref="y",
                xanchor="center", yanchor="top",
                text=f"<b>{c.ticker}</b>",
                showarrow=False,
                font=dict(color=S.TEXT_STRONG, size=ticker_font,
                          family="Inter, system-ui"),
            )
            cursor_y += ticker_font + gap_b

        if show_pct:
            pct_color = S.GREEN_SOFT if c.pct >= 0 else S.RED_SOFT
            fig.add_annotation(
                x=cx, y=cursor_y, xref="x", yref="y",
                xanchor="center", yanchor="top",
                text=f"{c.pct*100:+.2f}%",
                showarrow=False,
                font=dict(color=pct_color, size=pct_font,
                          family="Inter, system-ui"),
            )

        if show_price:
            fig.add_annotation(
                x=cx, y=c.y + c.h - 6, xref="x", yref="y",
                xanchor="center", yanchor="bottom",
                text=f"${c.price:,.2f}",
                showarrow=False,
                font=dict(color="rgba(226,232,240,0.55)", size=price_font,
                          family="Inter, system-ui"),
            )

        # Invisible scatter marker → gives us a real hover target per cell
        hover_x.append(c.x + c.w / 2)
        hover_y.append(c.y + c.h / 2)
        hover_text.append(
            f"<b>{c.ticker}</b> · {c.sector}<br>"
            f"change: {c.pct*100:+.2f}%<br>price: ${c.price:,.2f}"
        )

    fig.add_trace(go.Scatter(
        x=hover_x, y=hover_y, mode="markers",
        marker=dict(size=1, color="rgba(0,0,0,0)"),
        hoverinfo="text", hovertext=hover_text,
        showlegend=False,
    ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=6, r=6, t=6, b=6),
        height=780,
        xaxis=dict(range=[0, total_w], visible=False, fixedrange=True),
        yaxis=dict(range=[0, total_h], visible=False,
                   scaleanchor=None, autorange="reversed", fixedrange=True),
        font=dict(color=S.TEXT_STRONG, family="Inter, system-ui"),
        hoverlabel=dict(bgcolor=S.BG_ELEVATED, bordercolor=S.BORDER,
                        font=dict(color=S.TEXT_STRONG, family="Inter, system-ui")),
    )
    return fig


def market_heatmap_header(summary, ticker_count_hint: str = "") -> None:
    up = summary.n_up
    down = summary.n_down
    breadth = summary.breadth_pct
    best_tk, best_pct = summary.best
    worst_tk, worst_pct = summary.worst
    st.markdown(
        f"<div class='pl-title'>"
        f"<span class='tk'>Market Heat Map</span>"
        f"<span class='sub'>{summary.n_symbols} símbolos · pasa el mouse para detalle</span>"
        f"</div>"
        f"<div class='pl-ribbon'>"
        f"{_cell('spot','SYMBOLS', f'{summary.n_symbols}', ticker_count_hint)}"
        f"{_cell('call','ADVANCERS', str(up), f'{breadth*100:.0f}% breadth')}"
        f"{_cell('put','DECLINERS', str(down), f'{(1-breadth)*100:.0f}% breadth')}"
        f"{_cell('call','BEST', best_tk, _pct_chip(best_pct))}"
        f"{_cell('put','WORST', worst_tk, _pct_chip(worst_pct))}"
        f"</div>",
        unsafe_allow_html=True,
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
    st.dataframe(display, hide_index=True, width="stretch")

    cells = [
        _cell("spot",  "PORTFOLIO β",  f"{portfolio.portfolio_beta:.2f}"),
        _cell("call",  "β-DOLLARS",    _fmt_money(portfolio.beta_dollars)),
        _cell("spot",  "NET NOTIONAL", _fmt_money(portfolio.net_notional)),
        _cell("delta", "β-ADJ Δ $",    _fmt_money(portfolio.beta_adj_delta_dollars)),
    ]
    st.markdown(f"<div class='pl-ribbon'>{''.join(cells)}</div>", unsafe_allow_html=True)
