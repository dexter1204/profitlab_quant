"""ProfitLab Quant — Gamma & Beta Exposure Dashboard (Streamlit).

Run:
    streamlit run dashboard/app.py

Query params:
    ?ticker=QQQ   default ticker
    ?demo=1       force deterministic mock data (no network)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_CRED_KEYS = (
    "PROFITLAB_VENDOR",
    "POLYGON_API_KEY", "POLYGON_BASE_URL",
    "POLYGON_MCP_URL", "POLYGON_MCP_KEY",
    "POLYGON_MCP_TOOL_SPOT", "POLYGON_MCP_TOOL_AGGS",
    "POLYGON_MCP_TOOL_OPTIONS_SNAPSHOT",
)


def _load_secrets_into_env() -> None:
    """Populate os.environ from — in this precedence order:
      1. Actual OS env vars (highest — untouched here)
      2. Streamlit Cloud secrets (.streamlit/secrets.toml)
      3. profitlab/_credentials.py CREDENTIALS dict (local hardcoded)

    The vendor dispatcher and MCP client both read env vars, so any
    field populated here is picked up transparently — no sidebar entry
    required.
    """
    # 2. Streamlit Cloud secrets
    try:
        import streamlit as _st
        for key in _CRED_KEYS:
            if key in _st.secrets and _st.secrets[key]:
                os.environ.setdefault(key, str(_st.secrets[key]))
    except Exception:
        pass

    # 3. Local credentials file
    try:
        from profitlab import _credentials  # type: ignore
        for key, val in getattr(_credentials, "CREDENTIALS", {}).items():
            if val and key in _CRED_KEYS:
                os.environ.setdefault(key, str(val))
    except ImportError:
        pass

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profitlab import beta as beta_mod
from profitlab import data, demo, exposures, iv, market, metrics, regime
from dashboard import components, styles


TICKERS = ["QQQ", "SPY", "GLD", "SLV", "NQ", "AAPL", "TSLA", "NVDA"]


st.set_page_config(
    page_title="ProfitLab Quant — Gamma & Beta",
    layout="wide",
    initial_sidebar_state="expanded",
)
styles.inject()
_load_secrets_into_env()


@st.cache_data(ttl=300, show_spinner=False)
def _load_chain(ticker: str, use_demo: bool) -> tuple[pd.DataFrame, float]:
    if use_demo:
        chain = demo.demo_chain(ticker)
        spot = demo.DEMO_SPOTS.get(ticker, 100.0)
        return chain, spot
    return data.option_chain(ticker), data.spot(ticker)


@st.cache_data(ttl=300, show_spinner="Fetching price history…")
def _load_prices(use_demo: bool) -> dict[str, pd.Series]:
    if use_demo:
        return demo.demo_prices()
    return data.price_history_batch(TICKERS + ["SPY"], period="1y")


@st.cache_data(ttl=300, show_spinner=False)
def _load_market(use_demo: bool) -> pd.DataFrame:
    if use_demo:
        return market.demo_heatmap()
    return market.live_heatmap()


@st.cache_data(ttl=60, show_spinner=False)
def _load_bars(ticker: str, use_demo: bool, interval: str, period: str) -> pd.DataFrame:
    if use_demo:
        # Map interval string → minutes for demo generator
        minutes = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "15m": 15, "1d": 60 * 24}[interval]
        n = 390 if interval.endswith("m") and minutes <= 15 else 60
        return demo.demo_bars(ticker, n=n, interval_min=minutes)
    return data.intraday_bars(ticker, interval=interval, period=period)


def _sidebar_controls():
    st.sidebar.header("Controls")
    use_demo = st.sidebar.toggle("Demo data (no network)", value=True)

    # Vendor + credentials are read-only at runtime — configured either in
    # profitlab/_credentials.py (local, git-ignored) or via env vars.
    vendor = os.environ.get("PROFITLAB_VENDOR", "yfinance").lower()
    st.sidebar.subheader("Live data vendor")
    st.sidebar.markdown(
        f"<div style='padding:8px 12px;border:1px solid #1f2937;border-radius:6px;"
        f"background:#0b1220'>"
        f"<div style='color:#64748b;font-size:10px;letter-spacing:0.14em;"
        f"text-transform:uppercase;font-weight:700'>Vendor</div>"
        f"<div style='color:#f8fafc;font-size:14px;font-weight:600'>{vendor}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.caption(
        "Change vendor / keys in `profitlab/_credentials.py` "
        "(copy from `_credentials.example.py`)."
    )

    if vendor == "polygon_mcp" and not use_demo:
        if st.sidebar.button("🔍 Test MCP connection"):
            try:
                from profitlab.data import polygon_mcp
                tools = polygon_mcp.list_available_tools()
                names = [t.get("name", "?") for t in tools]
                st.sidebar.success(f"Connected · {len(tools)} tools available")
                required = {
                    "options snapshot": any("snapshot" in n and "option" in n for n in names),
                    "aggregates (bars)": any("aggs" in n or "aggregates" in n for n in names),
                    "stock snapshot": any("snapshot" in n and ("ticker" in n or "stocks" in n) for n in names),
                }
                missing = [k for k, ok in required.items() if not ok]
                if missing:
                    st.sidebar.warning(
                        "This listing is missing: " + ", ".join(missing) +
                        ". The dashboard needs these — consider polygon.io direct "
                        "or a richer api.market listing."
                    )
                with st.sidebar.expander("See tool names"):
                    st.write(names)
            except Exception as e:
                st.sidebar.error(f"{e}")

    window = st.sidebar.slider("Strike window (steps)", 5, 40, 20)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Heat map")
    remote_logos = st.sidebar.toggle(
        "Real brand logos (requires internet)",
        value=False,
        help="Off: solid brand-color chip with the ticker initial (offline, no glitches). "
             "On: fetches the real logo PNG from FinancialModelingPrep — needs internet on "
             "the browser side and can leave a blank chip if the ticker isn't listed there.",
    )
    st.sidebar.markdown("---")
    st.sidebar.subheader("Portfolio")
    default_positions = pd.DataFrame(
        [
            {"ticker": "AAPL", "shares": 100, "delta_shares": 100},
            {"ticker": "TSLA", "shares": -50, "delta_shares": -50},
            {"ticker": "NVDA", "shares": 80, "delta_shares": 120},
            {"ticker": "QQQ", "shares": 200, "delta_shares": 200},
        ]
    )
    positions = st.sidebar.data_editor(
        default_positions, num_rows="dynamic", width="stretch", key="positions"
    )
    return use_demo, window, positions, remote_logos


def _vendor_data_error(err: Exception) -> None:
    """Render a friendly banner when the current vendor can't serve the
    data the dashboard needs (usually a limited api.market MCP listing
    that lacks options-chain snapshots or aggregates)."""
    vendor = data.vendor_name()
    st.error(
        f"**{vendor}** couldn't return the data this view needs.\n\n"
        f"```\n{err}\n```"
    )
    st.info(
        "Este listing / vendor no expone los endpoints que necesita el "
        "dashboard (chain snapshot + aggregates). Opciones:\n\n"
        "• **Reactivar demo data** en la sidebar (toggle arriba) — funciona "
        "todo con mock determinista.\n"
        "• Cambiar el **vendor** a `yfinance` (delayed pero gratis).\n"
        "• Suscribirse a **Polygon.io directo** (Starter $29/mo incluye "
        "options snapshots + aggregates) y elegir vendor `polygon`.\n"
        "• Buscar un listing más completo en api.market — este solo tiene "
        "28 tools (mayormente indicadores técnicos + daily open/close), "
        "no snapshot de chain."
    )


def _render_gamma_flow(ticker: str, use_demo: bool, window: int, positions_df) -> None:
    try:
        chain, spot = _load_chain(ticker, use_demo)
    except Exception as e:
        _vendor_data_error(e)
        return
    ctx = exposures.ChainContext(
        spot=spot, asof=pd.Timestamp.now("UTC").tz_localize(None).normalize()
    )
    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    totals = exposures.totals(chain, ctx)
    levels = metrics.key_levels(chain, gex, dex, spot).as_dict()

    components.page_title(ticker, is_demo=use_demo, vendor=data.vendor_name())
    components.metric_strip(spot, levels, totals)

    left, right = st.columns([3, 1])
    with left:
        tabs = st.tabs([
            "GEX + DEX", "Heat map GEX", "Heat map DEX", "OI heat map",
            "Net drift", "Delta surface", "Volatility drift",
            "Volatility surface", "OI", "% OI",
        ])
        with tabs[0]:
            st.plotly_chart(
                components.gex_dex_pair(gex, dex, spot, levels, strike_window=window),
                width="stretch",
            )
        with tabs[1]:
            gex_grid = exposures.gex_by_strike_expiry(chain, ctx)
            st.plotly_chart(
                components.exposure_heatmap(
                    gex_grid, "gex", spot, levels=levels,
                    strike_window=window, title="GAMMA EXPOSURE",
                    asof=ctx.asof,
                ),
                width="stretch",
            )
            with st.expander("Top strikes by |GEX|"):
                st.dataframe(
                    gex.sort_values("gex", key=abs, ascending=False).head(30),
                    hide_index=True, width="stretch",
                )
        with tabs[2]:
            dex_grid = exposures.dex_by_strike_expiry(chain, ctx)
            st.plotly_chart(
                components.exposure_heatmap(
                    dex_grid, "dex", spot, levels=levels,
                    strike_window=window, title="DELTA EXPOSURE",
                    asof=ctx.asof,
                ),
                width="stretch",
            )
            with st.expander("Top strikes by |DEX|"):
                st.dataframe(
                    dex.sort_values("dex", key=abs, ascending=False).head(30),
                    hide_index=True, width="stretch",
                )
        with tabs[3]:
            oi_grid = exposures.oi_by_strike_expiry(chain)
            st.plotly_chart(
                components.oi_heatmap(
                    oi_grid, spot, levels=levels, strike_window=window,
                    mode="net", asof=ctx.asof,
                ),
                width="stretch",
            )
            st.caption(
                "Net OI = call OI − put OI. Green = call-heavy strikes "
                "(potential ceilings). Red = put-heavy (potential floors)."
            )
        with tabs[4]:
            drift = exposures.net_drift(chain, ctx, spot_pct=0.05, n=81)
            st.plotly_chart(
                components.net_drift_chart(drift, spot, levels),
                width="stretch",
            )
            st.caption(
                "Dealer net delta ($) as spot varies ±5%. Upward slope means "
                "dealers must sell into rallies / buy into dips (long γ → dampens)."
            )
        with tabs[5]:
            atm_row = chain.iloc[(chain["strike"] - spot).abs().argsort()].head(1).iloc[0]
            atm_iv_val = float(atm_row["iv"]) if atm_row["iv"] > 0 else 0.22
            k = float(atm_row["strike"])
            days_max = st.slider("Time horizon (days)", 15, 120, 60, key="ds_days")
            kind = st.radio("Contract kind", ["call", "put"],
                            horizontal=True, key="ds_kind")
            sx, sy, sz = exposures.delta_surface(
                ctx, strike=k, iv=atm_iv_val, days_max=days_max, kind=kind,
            )
            st.plotly_chart(
                components.delta_surface(
                    sx, sy, sz, ticker=ticker, strike=k, iv=atm_iv_val,
                    spot=spot, kind=kind,
                ),
                width="stretch",
            )
            st.caption(
                "Model: Black-Scholes · Axes: Spot Price × Time to Maturity · "
                "IV taken from the ATM strike of the current chain."
            )
        with tabs[6]:
            term = exposures.iv_by_expiry(chain, spot)
            st.plotly_chart(components.vol_drift_chart(term), width="stretch")
            st.caption(
                "Top: ATM/call/put IV per expiry. Bottom: put−call skew "
                "(positive = puts richer → hedging demand)."
            )
        with tabs[7]:
            iv_grid = exposures.iv_surface(chain, spot, strike_window=window)
            st.plotly_chart(
                components.vol_surface(iv_grid, spot=spot, asof=ctx.asof),
                width="stretch",
            )
            st.caption(
                "Median IV per (strike × DTE) cell from the current chain."
            )
        with tabs[8]:
            n_strikes = int(chain["strike"].nunique())
            top_left, top_right = st.columns([1, 4])
            with top_left:
                st.markdown(
                    f"<div class='pl-title' style='margin:0'>"
                    f"<span class='tk' style='font-size:14px'>OI BY STRIKE</span>"
                    f"<span class='sub'>{n_strikes} strikes</span></div>",
                    unsafe_allow_html=True,
                )
            with top_right:
                st.caption("Put OI %  ←  →  Call OI %  by strike")

            tbl_col, dist_col = st.columns([1, 4])
            with tbl_col:
                tbl = components.oi_by_strike_table(
                    chain, spot, strike_window=window, normalize=True
                )
                styled = components.style_oi_table(tbl, spot)
                st.dataframe(styled, hide_index=True, width="stretch", height=560)
            with dist_col:
                st.plotly_chart(
                    components.oi_distribution(chain, spot, strike_window=window),
                    width="stretch",
                )
        with tabs[9]:
            pct_grid = exposures.pct_oi_by_strike_expiry(chain)
            st.plotly_chart(
                components.oi_heatmap(
                    pct_grid, spot, levels=levels, strike_window=window,
                    mode="pct", asof=ctx.asof,
                ),
                width="stretch",
            )
            st.caption("Cell value = share of total open interest in the whole chain.")

    with right:
        try:
            prices = _load_prices(use_demo)
        except Exception as e:
            st.warning(
                f"Price history unavailable from **{data.vendor_name()}**: {e}"
            )
            return
        atm_iv = float(chain.iloc[(chain["strike"] - spot).abs().argsort()].head(2)["iv"].mean())
        exps = sorted(chain["expiry"].unique())
        front_iv = float(chain[chain["expiry"] == exps[0]]["iv"].median()) if exps else None
        back_iv = float(chain[chain["expiry"] == exps[-1]]["iv"].median()) if len(exps) > 1 else None
        iv_snap = iv.snapshot(atm_iv, prices[ticker], front_iv=front_iv, back_iv=back_iv)
        reg = regime.classify(spot, levels.get("gamma_flip"),
                              total_gex=totals.get("gex"))
        components.regime_panel(reg, iv_snap, ticker, spot)

    st.markdown("---")

    positions = positions_df.dropna(subset=["ticker"]).to_dict(orient="records")
    if positions:
        try:
            portfolio = beta_mod.portfolio_beta_exposure(positions, prices, benchmark="SPY")
            components.beta_panel(portfolio)
        except KeyError as e:
            st.warning(f"Missing price data for {e}. Toggle demo data or extend `_load_prices`.")


def _render_market_heatmap_safe(use_demo: bool, remote_logos: bool) -> None:
    try:
        _render_market_heatmap(use_demo, remote_logos)
    except Exception as e:
        _vendor_data_error(e)


def _render_chart(ticker: str, use_demo: bool) -> None:
    ctrl_l, ctrl_r = st.columns([3, 2])
    with ctrl_l:
        interval = st.radio(
            "timeframe",
            options=["1m", "2m", "3m", "5m", "15m", "1d"],
            index=0, horizontal=True, label_visibility="collapsed",
            key="chart_interval",
        )
    with ctrl_r:
        show_levels = st.multiselect(
            "levels",
            options=list(components._LEVEL_STYLE.keys()),
            default=["call_wall", "put_wall", "gamma_flip", "delta_flip", "max_pain"],
            format_func=lambda k: components._LEVEL_STYLE[k][1],
            label_visibility="collapsed",
            key="chart_levels",
        )

    chain, spot = _load_chain(ticker, use_demo)
    ctx = exposures.ChainContext(
        spot=spot, asof=pd.Timestamp.now("UTC").tz_localize(None).normalize()
    )
    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    levels = metrics.key_levels(chain, gex, dex, spot).as_dict()

    period_for = {"1m": "1d", "2m": "1d", "3m": "1d", "5m": "5d",
                  "15m": "1mo", "1d": "6mo"}[interval]
    try:
        bars = _load_bars(ticker, use_demo, interval, period_for)
    except Exception as e:
        st.warning(f"Couldn't load bars for {ticker}: {e}")
        return

    components.page_title(ticker, is_demo=use_demo, vendor=data.vendor_name())
    st.plotly_chart(
        components.price_chart(bars, spot=spot, levels=levels,
                               ticker=ticker, show_levels=show_levels),
        width="stretch",
    )
    cap_bits = [
        f"Long γ" if levels.get("gamma_flip") and spot > levels["gamma_flip"] else "Short γ"
    ]
    if levels.get("gamma_flip"):
        cap_bits.append(f"Flip ${levels['gamma_flip']:,.2f}")
    st.caption(" · ".join(cap_bits))


def _render_market_heatmap(use_demo: bool, remote_logos: bool) -> None:
    df = _load_market(use_demo)
    summary = market.summarize(df)
    components.market_heatmap_header(summary, ticker_count_hint="click a cell to inspect")
    st.plotly_chart(
        components.market_heatmap(df, prefer_remote_logos=remote_logos),
        width="stretch",
    )

    with st.expander("Universe (sortable table)"):
        show = df.assign(
            change=(df["pct"] * 100).round(2),
            price=df["price"].round(2),
            weight_b=df["weight"].round(0),
        )[["ticker", "sector", "price", "change", "weight_b"]]
        show = show.sort_values("change", ascending=False)
        st.dataframe(show, hide_index=True, width="stretch")


def main() -> None:
    use_demo, window, positions_df, remote_logos = _sidebar_controls()

    top_l, top_r = st.columns([3, 2])
    with top_l:
        ticker = st.radio(
            "ticker",
            options=TICKERS,
            horizontal=True,
            label_visibility="collapsed",
            key="ticker_selector",
        )
    with top_r:
        view = st.radio(
            "view",
            options=["Gamma & Flow", "Chart", "Market Heat Map"],
            horizontal=True,
            label_visibility="collapsed",
            key="view_selector",
        )

    if view == "Gamma & Flow":
        _render_gamma_flow(ticker, use_demo, window, positions_df)
    elif view == "Chart":
        try:
            _render_chart(ticker, use_demo)
        except Exception as e:
            _vendor_data_error(e)
    else:
        _render_market_heatmap_safe(use_demo, remote_logos)


if __name__ == "__main__":
    main()
