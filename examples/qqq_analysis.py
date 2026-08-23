"""End-to-end example: compute GEX/DEX, key levels, and a mixed portfolio's beta.

Runs against the deterministic demo chain so it works without a network.
Swap `demo.demo_chain(...)` / `demo.demo_prices()` for `data.option_chain(...)` /
`data.price_history(...)` for live data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from profitlab import beta, demo, exposures, iv, metrics, regime


def main() -> None:
    ticker = "QQQ"
    chain = demo.demo_chain(ticker)
    spot = demo.DEMO_SPOTS[ticker]
    ctx = exposures.ChainContext(spot=spot, asof=pd.Timestamp.now("UTC").tz_localize(None).normalize())

    gex = exposures.gex_by_strike(chain, ctx)
    dex = exposures.dex_by_strike(chain, ctx)
    totals = exposures.totals(chain, ctx)
    lv = metrics.key_levels(chain, gex, dex, spot).as_dict()
    reg = regime.classify(spot, lv["gamma_flip"])

    print(f"\n== {ticker} @ ${spot:,.2f} ==")
    print(f"  regime       : {reg.label}   ({reg.reading})")
    print(f"  gamma_flip   : {lv['gamma_flip']}")
    print(f"  call_wall    : {lv['call_wall']}")
    print(f"  put_wall     : {lv['put_wall']}")
    print(f"  delta_flip   : {lv['delta_flip']}")
    print(f"  delta_wall   : {lv['delta_wall']}")
    print(f"  max_pain     : {lv['max_pain']}")
    print(f"  TOTAL GEX    : ${totals['gex']:,.0f}")
    print(f"  TOTAL DEX    : ${totals['dex']:,.0f}")

    prices = demo.demo_prices()
    atm_iv = float(chain.iloc[(chain["strike"] - spot).abs().argsort()].head(2)["iv"].mean())
    snap = iv.snapshot(atm_iv, prices[ticker])
    print(f"\n== IV premium ==")
    print(f"  IV ATM       : {snap.iv_atm*100:.2f}%")
    print(f"  HV30         : {snap.hv30*100:.2f}%")
    print(f"  premium      : {snap.premium*100:+.1f}%")
    print(f"  reading      : {snap.reading}")

    positions = [
        {"ticker": "AAPL", "shares": 100, "delta_shares": 100},
        {"ticker": "TSLA", "shares": -50, "delta_shares": -50},
        {"ticker": "NVDA", "shares": 80, "delta_shares": 120},
        {"ticker": "QQQ", "shares": 200, "delta_shares": 200},
    ]
    port = beta.portfolio_beta_exposure(positions, prices, benchmark="SPY")
    print(f"\n== Portfolio (benchmark SPY) ==")
    print(port.as_frame().to_string(index=False))
    print(f"\n  portfolio beta   : {port.portfolio_beta:.2f}")
    print(f"  beta $-exposure  : ${port.beta_dollars:,.0f}")
    print(f"  beta-adj delta $ : ${port.beta_adj_delta_dollars:,.0f}")


if __name__ == "__main__":
    main()
