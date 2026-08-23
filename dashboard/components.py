"""Streamlit UI building blocks — metric strips, GEX/DEX bar pair, IV panel."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_LONG_GAMMA_COLOR = "#22c55e"
_SHORT_GAMMA_COLOR = "#ef4444"
_MUTED = "#94a3b8"


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
    return "—" if x is None or pd.isna(x) else f"${x:,.2f}"


def metric_strip(spot: float, levels: dict, totals: dict) -> None:
    """Top-of-page ribbon: spot + key levels + aggregate greeks."""
    cols = st.columns(11)
    cols[0].metric("SPOT PRICE", f"${spot:,.2f}")
    cols[1].metric("CALL WALL", _fmt_level(levels.get("call_wall")))
    cols[2].metric("PUT WALL", _fmt_level(levels.get("put_wall")))
    cols[3].metric("GAMMA FLIP", _fmt_level(levels.get("gamma_flip")))
    cols[4].metric("MAX PAIN", _fmt_level(levels.get("max_pain")))
    cols[5].metric("DELTA WALL", _fmt_level(levels.get("delta_wall")))
    cols[6].metric("MAJOR NEG DELTA", _fmt_level(levels.get("major_neg_delta")))
    cols[7].metric("DELTA FLIP", _fmt_level(levels.get("delta_flip")))
    cols[8].metric("VANNA", f"{totals.get('vanna', 0):,.0f}")
    cols[9].metric("CHARM", f"{totals.get('charm', 0):,.0f}")
    cols[10].metric("GEX", _fmt_money(totals.get("gex")))


def gex_dex_pair(
    gex: pd.DataFrame,
    dex: pd.DataFrame,
    spot: float,
    levels: dict,
    strike_window: int = 20,
) -> go.Figure:
    """Side-by-side horizontal bar charts of GEX and DEX around spot."""
    step = float(gex["strike"].diff().dropna().median()) if len(gex) > 1 else 1.0
    lo = spot - strike_window * step
    hi = spot + strike_window * step

    g = gex[(gex["strike"] >= lo) & (gex["strike"] <= hi)].sort_values("strike")
    d = dex[(dex["strike"] >= lo) & (dex["strike"] <= hi)].sort_values("strike")

    call_wall = levels.get("call_wall")
    put_wall = levels.get("put_wall")

    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=640,
        margin=dict(l=40, r=40, t=40, b=40),
        showlegend=False,
        grid=dict(rows=1, columns=2, pattern="independent"),
    )
    fig.add_trace(go.Bar(
        y=g["strike"], x=g["gex"], orientation="h",
        marker_color=[_LONG_GAMMA_COLOR if v >= 0 else _SHORT_GAMMA_COLOR for v in g["gex"]],
        marker_line_width=0,
        name="GEX", xaxis="x", yaxis="y",
    ))
    fig.add_trace(go.Bar(
        y=d["strike"], x=d["dex"], orientation="h",
        marker_color=[_LONG_GAMMA_COLOR if v >= 0 else _SHORT_GAMMA_COLOR for v in d["dex"]],
        marker_line_width=0,
        name="DEX", xaxis="x2", yaxis="y2",
    ))
    for axis in ("xaxis", "xaxis2"):
        fig.layout[axis].update(gridcolor="#1f2937", zerolinecolor="#374151")
    for axis in ("yaxis", "yaxis2"):
        fig.layout[axis].update(gridcolor="#1f2937", tickformat="$,.0f")
    fig.layout.xaxis.domain = [0.0, 0.48]
    fig.layout.xaxis2.domain = [0.52, 1.0]
    fig.layout.yaxis.anchor = "x"
    fig.layout.yaxis2.anchor = "x2"
    fig.layout.annotations = [
        dict(text="GEX", x=0.24, y=1.05, xref="paper", yref="paper", showarrow=False, font=dict(color=_MUTED)),
        dict(text="DEX", x=0.76, y=1.05, xref="paper", yref="paper", showarrow=False, font=dict(color=_MUTED)),
    ]
    fig.add_hline(y=spot, line_dash="dot", line_color="#facc15", opacity=0.7)
    if call_wall:
        fig.add_hline(y=call_wall, line_dash="dash", line_color="#22c55e", opacity=0.5)
    if put_wall:
        fig.add_hline(y=put_wall, line_dash="dash", line_color="#ef4444", opacity=0.5)
    return fig


def exposure_heatmap(
    long_df: pd.DataFrame,
    value_col: str,
    spot: float,
    levels: Optional[dict] = None,
    strike_window: int = 20,
    title: str = "GEX heat map",
) -> go.Figure:
    """Strike × expiry heat map. `long_df` has columns [strike, expiry, <value_col>]."""
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
        .sort_index(ascending=True)
        .sort_index(axis=1)
    )

    zmax = float(max(abs(grid.min().min()), abs(grid.max().max())) or 1.0)
    fig = go.Figure(
        data=go.Heatmap(
            z=grid.values,
            x=grid.columns.tolist(),
            y=grid.index.tolist(),
            colorscale=[
                (0.0, _SHORT_GAMMA_COLOR),
                (0.5, "#0b1220"),
                (1.0, _LONG_GAMMA_COLOR),
            ],
            zmid=0.0,
            zmin=-zmax,
            zmax=zmax,
            colorbar=dict(title=value_col.upper(), tickfont=dict(color=_MUTED)),
            hovertemplate="strike=%{y}<br>expiry=%{x}<br>" + value_col + "=%{z:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=640,
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis=dict(title="Expiration", gridcolor="#1f2937"),
        yaxis=dict(title="Strike", gridcolor="#1f2937", tickformat="$,.0f"),
        title=dict(text=title, x=0.02, y=0.98, font=dict(color=_MUTED, size=13)),
    )
    fig.add_hline(y=spot, line_dash="dot", line_color="#facc15", opacity=0.7,
                  annotation_text=f"spot ${spot:,.2f}", annotation_position="top left",
                  annotation_font_color="#facc15")
    for key, color, label in (
        ("call_wall", "#22c55e", "call wall"),
        ("put_wall", "#ef4444", "put wall"),
        ("gamma_flip", "#facc15", "g-flip"),
    ):
        v = levels.get(key)
        if v is not None:
            fig.add_hline(y=v, line_dash="dash", line_color=color, opacity=0.5,
                          annotation_text=label, annotation_position="top right",
                          annotation_font_color=color)
    return fig


def regime_panel(regime, iv_snapshot, ticker: str, spot: float) -> None:
    """Right-hand column: gamma regime + IV premium block."""
    st.markdown(f"### GAMMA REGIME")
    st.markdown(f"# ${spot:,.2f}  \n<span style='color:{_MUTED}'>{ticker}</span>", unsafe_allow_html=True)

    color = _LONG_GAMMA_COLOR if regime.label == "LONG GAMMA" else _SHORT_GAMMA_COLOR
    st.markdown(
        f"<div style='background:{color}22;border:1px solid {color};padding:8px 12px;"
        f"border-radius:8px;color:{color};font-weight:600;text-align:center'>"
        f"● {regime.label}</div>",
        unsafe_allow_html=True,
    )
    st.caption(regime.reading)

    c1, c2 = st.columns(2)
    with c1:
        st.metric("G-FLIP", f"${regime.g_flip:,.2f}" if regime.g_flip else "—",
                  f"{regime.gap_pct*100:+.1f}%" if regime.gap_pct is not None else None)
    with c2:
        st.metric("VOL TRIGGER", f"${regime.g_flip:,.2f}" if regime.g_flip else "—",
                  f"{regime.gap_pct*100:+.1f}%" if regime.gap_pct is not None else None)

    st.markdown("---")
    st.markdown("### IV PREMIUM")
    prem = iv_snapshot.premium
    prem_color = _SHORT_GAMMA_COLOR if prem > 0 else _LONG_GAMMA_COLOR
    st.markdown(
        f"<h2 style='color:{prem_color};text-align:center;margin:0'>{prem*100:+.1f}%</h2>"
        f"<div style='text-align:center;color:{_MUTED}'>IV CARA</div>"
        f"<div style='text-align:center;color:{_MUTED};font-size:12px'>"
        f"Ratio IV/HV30: <b>{iv_snapshot.ratio_iv_hv30:.2f}×</b></div>",
        unsafe_allow_html=True,
    )
    df = pd.DataFrame({
        "": ["HV10", "HV30", "HV60", "IV ATM"],
        "value": [
            f"{iv_snapshot.hv10*100:.1f}%",
            f"{iv_snapshot.hv30*100:.1f}%",
            f"{iv_snapshot.hv60*100:.1f}%",
            f"{iv_snapshot.iv_atm*100:.1f}%",
        ],
    })
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.markdown(f"**Lectura:** {iv_snapshot.reading}")

    st.markdown("---")
    st.write({
        "ATM IV": f"{iv_snapshot.iv_atm*100:.2f}%",
        "IV PREMIUM": f"{prem*100:+.1f}%",
        "TERM STRUCTURE": iv_snapshot.term_structure,
    })


def beta_panel(portfolio) -> None:
    st.markdown("### PORTFOLIO BETA EXPOSURE")
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
    )[["ticker", "shares", "delta_shares", "price", "beta", "notional", "beta_dollars", "beta_adj_delta_dollars"]]
    st.dataframe(display, hide_index=True, use_container_width=True)
    cols = st.columns(4)
    cols[0].metric("PORTFOLIO β", f"{portfolio.portfolio_beta:.2f}")
    cols[1].metric("β-DOLLARS", _fmt_money(portfolio.beta_dollars))
    cols[2].metric("NET NOTIONAL", _fmt_money(portfolio.net_notional))
    cols[3].metric("β-ADJ DELTA $", _fmt_money(portfolio.beta_adj_delta_dollars))
