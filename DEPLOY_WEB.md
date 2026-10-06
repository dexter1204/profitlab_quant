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

### Accounts, coupons & payment

The dashboard has its **own login** (`/quantsistem/login.html`) with its own
session (localStorage `plq_token`, independent from the Aula). Users sign in
with their **Aula credentials** (same email + password) — the quant validates
them against the Aula accounts via `POST /api/auth/login`. Access to the
dashboard is then granted by a **coupon** or a **payment** (Mercado Pago), both
handled by the Aula's PHP API against its own database.

How it works:
1. Visitor opens `/quantsistem/` with no session → the quant's own
   `login.html`. They enter their Aula email + password → the quant stores a
   token under `plq_token` (not the Aula's `pl_token`).
2. The frontend asks the Aula `GET /api/quant/me`. If the user has active
   access → dashboard loads.
3. If not → a **paywall**: redeem a coupon, or **pay** to unlock (opens
   Mercado Pago; on approval the Aula webhook grants access automatically).
4. You create coupons and see who has access from the quant **admin page**
   (`/quantsistem/admin.html`, visible only to Aula admins), which talks to the
   Aula API.

The quant backend (Render) keeps **no users and no database** — on each data
request it asks the Aula `GET /api/quant/me` whether the caller has access, so
Render never connects to MySQL (no remote-MySQL headache). The coupon/access
data lives in **your Aula's database**.

**One-time setup in the Aula** (this repo ships the PHP changes in
`aulavirtual---profitlab`):
1. In phpMyAdmin of your Aula database, run **`api/migracion_quant.sql`**
   (creates `quant_access`, `quant_coupons`, `quant_redemptions`).
2. In `api/config.php` add the quant settings (price / currency / days —
   all editable): e.g. `'quant_price' => 75, 'quant_currency' => 'USD',
   'quant_days' => 30`. Make sure `mp_access_token` is set for payments.
3. Upload the updated `api/` to `public_html/api/`.

Quant backend env var (set in Render → Environment):

| Key | Value |
|---|---|
| `AULA_API_BASE` | `https://profitlab-academy.com/aulavirtual/api` |

Front-end URLs live in `web/config.js` under `window.PROFITLAB_AULA`
(`apiBase`, `signupUrl`, `adminUrl`) — adjust if your Aula paths differ.

### Views / API endpoints

The frontend has five tabs, each backed by one endpoint:

| Tab | Endpoint | Shows |
|---|---|---|
| Gamma & Flow | `GET /api/analyze/{ticker}` | metric ribbon, GEX profile + DEX overlay, dealer regime |
| Chart | `GET /api/chart/{ticker}` | intraday candles with the GEX profile at the side + key level lines |
| GEX Heatmap | `GET /api/gex_heatmap/{ticker}` | GEX on a strike × expiry grid |
| OI / % OI | `GET /api/oi/{ticker}` | call/put open interest per strike (toggle absolute ↔ % of total) |
| Delta Surface | `GET /api/delta_surface/{ticker}` | 3-D B-S delta across spot × time-to-expiry (call/put toggle) |
| Net Drift | `GET /api/net_drift/{ticker}` | dealer net dollar-delta profile across a ±5% spot range |
| Volatility | `GET /api/vol_drift/{ticker}`, `GET /api/vol_surface/{ticker}` | IV term structure (ATM/call/put by DTE) + 3-D IV surface (toggle) |

(`GET /api/iv/{ticker}` is also available for IV-vs-realized premium.
`GET /api/access` reports the Aula session + course access. All data
endpoints require a valid Aula token enrolled in the ProfitLab Quant course.)
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
2. Upload **all of `web/`** (the files, not the folder itself) to SiteGround so
   they land in `public_html/quantsistem/`:
   - `index.html` · `login.html` · `admin.html`
   - `config.js` · `auth.js` · `universe.js` · `app.js`
   - `plotly.min.js` (the charting library, served locally — no CDN)

   Two ways:
   - **Site Tools → File Manager**: navigate to `public_html`, create a folder
     `quantsistem`, open it, **Upload** all the files.
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
