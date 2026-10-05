# Deploy to your own website (SiteGround + Render)

This is the production path for running ProfitLab Quant **without Streamlit**,
so it lives on your own domain at
<https://profitlab-academy.com/quantsistem>.

SiteGround shared hosting cannot run Python (no "Python App" option), so the
system is split in two:

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  SiteGround (static files)  │  HTTPS │  Render (FastAPI backend)     │
│  profitlab-academy.com      │ ─────▶ │  quantsistem-api.onrender.com │
│  /quantsistem               │  fetch │  reads profitlab/ + Polygon    │
│  index.html · app.js · css  │ ◀───── │  returns JSON (GEX/DEX/levels) │
└─────────────────────────────┘  JSON  └──────────────────────────────┘
```

- **Frontend** (`web/`): plain HTML + JS + Plotly.js. No build step. Upload to
  SiteGround. **No secrets live here** — safe to be public.
- **Backend** (`api/`): FastAPI reusing the `profitlab/` library. Holds the
  **Polygon/Massive API key** server-side. Deploy to Render (free tier works).

Do these in order: **backend first** (you need its URL), then the frontend.

### Views / API endpoints

The frontend has five tabs, each backed by one endpoint:

| Tab | Endpoint | Shows |
|---|---|---|
| Gamma & Flow | `GET /api/analyze/{ticker}` | metric ribbon, GEX profile + DEX overlay, dealer regime |
| Chart | `GET /api/chart/{ticker}` | intraday candles with the GEX profile at the side + key level lines |
| GEX Heatmap | `GET /api/gex_heatmap/{ticker}` | GEX on a strike × expiry grid |
| OI / % OI | `GET /api/oi/{ticker}` | call/put open interest per strike (toggle absolute ↔ % of total) |
| Market Heatmap | `GET /api/market` | sector treemap colored by day change + breadth summary |

(`GET /api/iv/{ticker}` is also available for IV-vs-realized premium.)
Intraday candles are best-effort — if the vendor/plan doesn't serve them for
a symbol, the Chart tab still shows the GEX profile and levels.

---

## Part 1 — Backend on Render

1. Push this repo/branch to GitHub (the backend reads `render.yaml`, `api/`,
   and `profitlab/` straight from the repo).
2. Go to <https://render.com> → **New** → **Web Service** → connect the
   `dexter1204/profitlab_quant` repo.
3. Render detects `render.yaml` ("Blueprint"). Accept it. It sets:
   - **Build**: `pip install -r api/requirements.txt`
   - **Start**: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - Env vars `PROFITLAB_VENDOR=polygon`, `POLYGON_BASE_URL=https://api.massive.com`,
     `ALLOWED_ORIGINS=https://profitlab-academy.com`.
4. **Set the secret** — in the Render dashboard, open the service →
   **Environment** → add:
   - `POLYGON_API_KEY` = your Massive/Polygon REST key.

   This is the one value that is **never** in git. `render.yaml` declares it
   with `sync: false` precisely so Render prompts you for it instead of reading
   it from the repo.
5. Click **Deploy**. First build ~2–3 min. When it's live you get a URL like
   `https://quantsistem-api.onrender.com`.
6. Verify it works — open these in a browser:
   - `https://<your-render-url>/api/health` → `{"ok": true, "vendor": "polygon", ...}`
   - `https://<your-render-url>/api/analyze/QQQ` → a JSON blob with `spot`,
     `levels`, `gex`, …

> **Free-tier cold start.** Free Render services sleep after ~15 min idle;
> the next request takes ~30–50s to wake. Upgrade to the **Starter** plan
> (~$7/mo) in `render.yaml` (`plan: starter`) to keep it warm.

> **CORS.** The browser will only accept responses from the API if the page's
> origin is in `ALLOWED_ORIGINS`. It already lists `https://profitlab-academy.com`.
> If you serve the page from a different host (a `www.` prefix counts as
> different), add that origin too — comma-separated, no trailing slash.

---

## Part 2 — Frontend on SiteGround

1. **Point the frontend at your API.** Edit `web/config.js`:
   ```js
   window.PROFITLAB_API = "https://quantsistem-api.onrender.com"; // ← your Render URL
   ```
   Use the exact URL from Part 1, **no trailing slash**.
2. Upload the **contents of `web/`** (not the folder itself) to SiteGround so
   they land in `public_html/quantsistem/`:
   - `index.html`
   - `config.js`
   - `universe.js`
   - `app.js`

   Two ways:
   - **Site Tools → File Manager**: navigate to `public_html`, create a folder
     `quantsistem`, open it, **Upload** the four files.
   - **FTP** (FileZilla): connect with your SiteGround FTP credentials, drop the
     four files into `public_html/quantsistem/`.
3. Open <https://profitlab-academy.com/quantsistem/>. The page loads, the ticker
   search is populated (Options / Futures / Indices), and selecting a symbol
   fetches live analytics from Render.

That's it. To update later: change files in `web/`, re-upload the changed ones.
No rebuild, no restart.

---

## Updating

- **Frontend tweak** (colors, layout, add a ticker): edit the file in `web/`,
  re-upload it to SiteGround. Instant.
- **Backend logic** (new endpoint, metric fix): push to GitHub. Render
  auto-redeploys on push.
- **Rotate the API key**: change `POLYGON_API_KEY` in Render → Environment and
  redeploy. Nothing to touch on SiteGround.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Page says "API no configurada" | `config.js` still has the placeholder URL — set your Render URL. |
| "No se pudieron cargar los datos … HTTP 502" | Backend couldn't reach the data vendor. Check `POLYGON_API_KEY` is set in Render and the plan covers options snapshots. |
| Network/CORS error in browser console | The page's origin isn't in `ALLOWED_ORIGINS`. Add it in Render → Environment, redeploy. |
| First request very slow, then fine | Free-tier cold start. Upgrade to `plan: starter` to avoid it. |
| `/api/health` works but `/api/analyze/QQQ` 502s | Vendor/plan issue, not wiring. Try `PROFITLAB_VENDOR=yfinance` temporarily to confirm the pipeline, then switch back to `polygon`. |

## Local dev

Run the backend locally and point the frontend at it:

```bash
# backend
pip install -r api/requirements.txt
POLYGON_API_KEY=... PROFITLAB_VENDOR=polygon uvicorn api.main:app --reload --port 8000

# frontend — any static server from the web/ dir, e.g.:
cd web && python -m http.server 5500
```

Set `window.PROFITLAB_API = "http://localhost:8000"` in `web/config.js` while
developing (localhost origins are already in the backend's default
`ALLOWED_ORIGINS`). Revert it to the Render URL before uploading to SiteGround.
