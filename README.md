# ProfitLab Quant — Gamma & Beta Exposure Dashboard

Analytics library and dashboard for **options dealer exposures** (GEX, DEX,
vanna, charm) and **portfolio beta exposure** against a market benchmark.

## What it computes

- **GEX** — Gamma Exposure per strike (long-gamma vs short-gamma regime).
- **DEX** — Delta Exposure per strike.
- **Vanna / Charm** — second-order dealer greeks.
- **Key levels** — call wall, put wall, gamma flip, delta flip, delta wall,
  max pain, major negative delta.
- **Regime** — long/short gamma classification with the spot / g-flip gap.
- **IV premium** — ATM IV vs HV10/HV30/HV60, ratio and read.
- **Beta exposure** — per-position and aggregate portfolio beta versus a
  chosen benchmark (SPY/QQQ/…): dollar beta, beta-adjusted delta, and
  contribution by ticker.

## Layout

```
profitlab/
  greeks.py       Black-Scholes greeks (call/put, dividend-adjusted)
  exposures.py    GEX / DEX / VEX / vanna / charm from an option chain
  metrics.py      call wall, put wall, gamma flip, delta flip, max pain, …
  regime.py       gamma regime classifier (long / short / transition)
  iv.py           realized vol (HV) and IV-premium metrics
  beta.py         rolling beta and portfolio beta exposure
  data.py         yfinance loaders for spot, chain, and price history
  demo.py         deterministic mock chain matching the reference layout
dashboard/
  app.py          Streamlit dashboard
  components.py   metric strip, GEX/DEX bar pair, IV premium panel
tests/
  test_greeks.py  reference-value sanity checks
```

## Install

```bash
pip install -r requirements.txt
```

## Run the dashboard

```bash
streamlit run dashboard/app.py
```

Add `?demo=1` to force the deterministic demo chain (no network).

## Programmatic use

```python
from profitlab import exposures, metrics, beta

chain = exposures.load_chain("QQQ")        # or exposures.demo_chain("QQQ")
gex   = exposures.gex_by_strike(chain)
dex   = exposures.dex_by_strike(chain)

levels = metrics.key_levels(chain, gex, dex)
# → call_wall, put_wall, gamma_flip, delta_flip, delta_wall,
#   major_neg_delta, max_pain

positions = [
    {"ticker": "AAPL", "shares":  100, "delta_shares":  100},
    {"ticker": "TSLA", "shares": -50,  "delta_shares":  -50},
    {"ticker": "SPY",  "shares":  200, "delta_shares":  200},
]
port_beta = beta.portfolio_beta_exposure(positions, benchmark="SPY")
```

## Notes on data

The chain loader uses `yfinance`, which serves delayed retail data. For
production replace `profitlab.data` with your own market-data adapter — the
rest of the library only depends on a normalized chain DataFrame
(`strike, expiry, type, oi, iv, bid, ask`).
