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

## Deploy to the web (Streamlit Community Cloud, free)

Fastest path — deploys from GitHub, redeploys on every push, free tier
handles this app comfortably.

1. Push your working branch to GitHub (already done by the workflow
   here — the branch is `claude/gamma-beta-exposure-dashboard-2dpjlg`,
   or merge to `main` first).
2. Sign in at <https://share.streamlit.io> with the GitHub account
   that owns the repo (`dexter1204`).
3. Click **New app** and fill in:
   - **Repository**: `dexter1204/profitlab_quant`
   - **Branch**: your branch name (or `main`)
   - **Main file path**: `dashboard/app.py`
   - **App URL**: pick a subdomain, e.g. `profitlab-quant`.
4. Click **Advanced settings → Secrets** and paste the content of
   `.streamlit/secrets.toml.example`, filling in any vendor keys you
   want the live app to use. When present, the app reads them into
   `os.environ` at boot so the sidebar controls are pre-populated.
5. Click **Deploy**. First build takes ~2–3 minutes.

The runtime is pinned to Python 3.11 via `runtime.txt`; system apt
packages (if ever needed) live in `packages.txt` (currently empty).

### Notes for the live deploy

- **yfinance can 403 from cloud IPs.** Yahoo periodically blocks
  data-center netblocks. If the deployed app throws 401/403/429 on
  chain fetches, switch the sidebar vendor to `demo` for a
  showcase-only mode, or wire a real vendor (Polygon direct is the
  easiest paid option; see below).
- **API keys never go into git.** `.streamlit/secrets.toml` is
  git-ignored. Commit only `.streamlit/secrets.toml.example` and
  paste the real values into the Streamlit Cloud UI.
- **Cold start**: free tier apps sleep after ~7 days idle; first hit
  after sleep takes ~30s to wake.

### Other targets

- **Hugging Face Spaces** — also free, same idea: point at the repo,
  set `dashboard/app.py` as the entry, add secrets in the Space
  settings.
- **Render / Railway / Fly.io** — need a `Procfile` line:
  `web: streamlit run dashboard/app.py --server.port $PORT
  --server.address 0.0.0.0`
- **Docker** — no Dockerfile shipped yet; the app runs cleanly on
  `python:3.11-slim` with `pip install -r requirements.txt` +
  `CMD ["streamlit", "run", "dashboard/app.py"]`.

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
