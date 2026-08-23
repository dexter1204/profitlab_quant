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
from profitlab import data, demo, exposures, iv, metrics, regime
from dashboard import components


TICKERS = ["QQQ", "SPY", "GLD", "SLV", "NQ", "AAPL", "TSLA", "NVDA"]


st.set_page_config(page_title="ProfitLab Quant — Gamma & Beta", layout="wide")


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


def _sidebar_controls():
    st.sidebar.header("Controls")
    use_demo = st.sidebar.toggle("Demo data (no network)", value=True)
    tab_ticker = st.sidebar.selectbox("Ticker", TICKERS, index=0)
    window = st.sidebar.slider("Strike window (steps)", 5, 40, 20)
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
        default_positions, num_rows="dynamic", use_container_width=True, key="positions"
    )
    return use_demo, tab_ticker, window, positions


def main() -> None:
    use_demo, ticker, window, positions_df = _sidebar_controls()

    chain, spot = _load_chain(ticker, use_demo)
    ctx = exposures.ChainContext(spot=spot, asof=pd.Timestamp.now("UTC").tz_localize(None).normalize())
    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    totals = exposures.totals(chain, ctx)
    levels = metrics.key_levels(chain, gex, dex, spot).as_dict()

    # Header
    st.markdown(f"### **{ticker}**  ·  Gamma & Beta Exposure")
    components.metric_strip(spot, levels, totals)

    # Main body: chart + regime column
    left, right = st.columns([3, 1])
    with left:
        tabs = st.tabs(["GEX + DEX", "Heat map GEX", "Heat map DEX", "OI"])
        with tabs[0]:
            st.plotly_chart(
                components.gex_dex_pair(gex, dex, spot, levels, strike_window=window),
                use_container_width=True,
            )
        with tabs[1]:
            st.dataframe(gex.sort_values("gex", key=abs, ascending=False).head(30),
                         hide_index=True, use_container_width=True)
        with tabs[2]:
            st.dataframe(dex.sort_values("dex", key=abs, ascending=False).head(30),
                         hide_index=True, use_container_width=True)
        with tabs[3]:
            by_strike = (
                chain.groupby(["strike", "type"], as_index=False)["oi"].sum()
                .pivot(index="strike", columns="type", values="oi").fillna(0)
            )
            st.dataframe(by_strike, use_container_width=True)

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

    # Beta exposure
    positions = positions_df.dropna(subset=["ticker"]).to_dict(orient="records")
    if positions:
        try:
            portfolio = beta_mod.portfolio_beta_exposure(positions, prices, benchmark="SPY")
            components.beta_panel(portfolio)
        except KeyError as e:
            st.warning(f"Missing price data for {e}. Toggle demo data or extend `_load_prices`.")


if __name__ == "__main__":
    main()
