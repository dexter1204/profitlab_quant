"""ProfitLab Quant — Gamma & Beta Exposure Dashboard (Streamlit).

Run:
    streamlit run dashboard/app.py

Query params:
    ?ticker=QQQ   default ticker
    ?demo=1       force deterministic mock data (no network)
"""

from __future__ import annotations

import sys
from pathlib import Path

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


@st.cache_data(ttl=300, show_spinner=False)
def _load_chain(ticker: str, use_demo: bool) -> tuple[pd.DataFrame, float]:
    if use_demo:
        chain = demo.demo_chain(ticker)
        spot = demo.DEMO_SPOTS.get(ticker, 100.0)
        return chain, spot
    return data.option_chain(ticker), data.spot(ticker)


@st.cache_data(ttl=300, show_spinner=False)
def _load_prices(use_demo: bool) -> dict[str, pd.Series]:
    if use_demo:
        return demo.demo_prices()
    return {t: data.price_history(t, period="1y") for t in TICKERS + ["SPY"]}


@st.cache_data(ttl=300, show_spinner=False)
def _load_market(use_demo: bool) -> pd.DataFrame:
    if use_demo:
        return market.demo_heatmap()
    return market.live_heatmap()


def _sidebar_controls():
    st.sidebar.header("Controls")
    use_demo = st.sidebar.toggle("Demo data (no network)", value=True)
    tab_ticker = st.sidebar.selectbox("Ticker", TICKERS, index=0)
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
    return use_demo, tab_ticker, window, positions, remote_logos


def _render_gamma_flow(ticker: str, use_demo: bool, window: int, positions_df) -> None:
    chain, spot = _load_chain(ticker, use_demo)
    ctx = exposures.ChainContext(
        spot=spot, asof=pd.Timestamp.now("UTC").tz_localize(None).normalize()
    )
    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    totals = exposures.totals(chain, ctx)
    levels = metrics.key_levels(chain, gex, dex, spot).as_dict()

    components.page_title(ticker, is_demo=use_demo)
    components.metric_strip(spot, levels, totals)

    left, right = st.columns([3, 1])
    with left:
        tabs = st.tabs(["GEX + DEX", "Heat map GEX", "Heat map DEX",
                        "Delta surface", "OI"])
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
        with tabs[4]:
            by_strike = (
                chain.groupby(["strike", "type"], as_index=False)["oi"].sum()
                .pivot(index="strike", columns="type", values="oi").fillna(0)
            )
            st.dataframe(by_strike, width="stretch")

    with right:
        prices = _load_prices(use_demo)
        atm_iv = float(chain.iloc[(chain["strike"] - spot).abs().argsort()].head(2)["iv"].mean())
        exps = sorted(chain["expiry"].unique())
        front_iv = float(chain[chain["expiry"] == exps[0]]["iv"].median()) if exps else None
        back_iv = float(chain[chain["expiry"] == exps[-1]]["iv"].median()) if len(exps) > 1 else None
        iv_snap = iv.snapshot(atm_iv, prices[ticker], front_iv=front_iv, back_iv=back_iv)
        reg = regime.classify(spot, levels.get("gamma_flip"))
        components.regime_panel(reg, iv_snap, ticker, spot)

    st.markdown("---")

    positions = positions_df.dropna(subset=["ticker"]).to_dict(orient="records")
    if positions:
        try:
            portfolio = beta_mod.portfolio_beta_exposure(positions, prices, benchmark="SPY")
            components.beta_panel(portfolio)
        except KeyError as e:
            st.warning(f"Missing price data for {e}. Toggle demo data or extend `_load_prices`.")


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
    use_demo, ticker, window, positions_df, remote_logos = _sidebar_controls()

    view = st.radio(
        "view",
        options=["Gamma & Flow", "Market Heat Map"],
        horizontal=True,
        label_visibility="collapsed",
        key="view_selector",
    )
    if view == "Gamma & Flow":
        _render_gamma_flow(ticker, use_demo, window, positions_df)
    else:
        _render_market_heatmap(use_demo, remote_logos)


if __name__ == "__main__":
    main()
