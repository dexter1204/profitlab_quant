// ProfitLab Quant — frontend logic (multi-view).
// Tabs: Gamma & Flow · Chart · GEX Heatmap · OI / % OI · Delta Surface ·
// Net Drift · Volatility.
// All data comes from the FastAPI backend (window.PROFITLAB_API); the
// browser only renders. Pure Plotly.js, no build step.

(function () {
  const U = window.PROFITLAB_UNIVERSE;
  const API = (window.PROFITLAB_API || "").replace(/\/+$/, "");
  const el = (id) => document.getElementById(id);
  const DEFAULT_TICKER = "QQQ";

  // Palette mirrors theme.css tokens and is refreshed from window.PLQ_THEME
  // (set by theme.js) on boot and on every theme change. Render functions read
  // C.* at draw time, so re-rendering after a theme change recolors everything.
  const C = {
    bg: "#1c1c1e", panel: "#1c1c1e", grid: "rgba(255,255,255,.10)", border: "rgba(255,255,255,.16)",
    zero: "rgba(255,255,255,.28)", text: "#f5f5f7", muted: "#a1a1a6", lime: "#C7F94C",
    green: "#30d073", red: "#ff5247", purple: "#b483ff",
    cyan: "#40c8ef", amber: "#ffa418", yellow: "#ffd60a", blue: "#4f8cff", white: "#e8eef7",
    sceneBg: "rgba(0,0,0,0)", sceneGrid: "rgba(255,255,255,.14)",
  };
  const FONT = { color: C.muted, family: "-apple-system, 'Inter', system-ui, sans-serif", size: 11 };
  function syncPalette() {
    const p = window.PLQ_THEME; if (!p) return;
    C.bg = p.panel; C.panel = p.panel; C.grid = p.grid; C.border = p.border; C.zero = p.zero;
    C.text = p.text; C.muted = p.muted; C.lime = p.accent;
    C.green = p.green; C.red = p.red; C.purple = p.purple; C.cyan = p.cyan;
    C.amber = p.amber; C.yellow = p.yellow; C.blue = p.blue; C.white = p.white;
    C.sceneBg = p.scene_bg; C.sceneGrid = p.scene_grid;
    C.tagBg = (window.PLQTheme && window.PLQTheme.get() === "light") ? "rgba(255,255,255,.82)" : "rgba(10,10,12,.72)";
    FONT.color = p.muted;
  }
  syncPalette();
  // dragmode "pan" = drag to move, wheel to zoom (TradingView-style); no
  // rubber-band box zoom. scrollZoom in CONFIG enables the wheel.
  const BASE_LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: FONT, dragmode: "pan",
  };
  const CONFIG = { responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: "reset" };

  // Desktop-only build (PC). No mobile layout branching anymore.
  const isNarrow = () => false;

  // Config para las vistas 3D: scrollZoom permite acercar/alejar con la rueda
  // en PC y con el gesto de dos dedos (pinch) en celular. La rotación es con
  // un dedo (turntable). El CSS touch-action:none del lienzo evita que el
  // navegador se "robe" el pinch para hacer zoom de la página.
  const CONFIG3D = { responsive: true, displayModeBar: false, scrollZoom: true };

  // chart timeframes → (interval, period) for the bars loader
  const TF = {
    "1m":  { interval: "1m",  period: "1d" },
    "5m":  { interval: "5m",  period: "5d" },
    "15m": { interval: "15m", period: "1mo" },
    "1h":  { interval: "60m", period: "3mo" },
    "1D":  { interval: "1d",  period: "1y" },
  };

  // ── state ────────────────────────────────────────────────────────────────
  const state = {
    view: "gamma",
    pick: DEFAULT_TICKER,          // what the user selected (may be a future)
    symbol: DEFAULT_TICKER,        // resolved symbol the API loads
    oiMode: "oi",
    heatMode: "gex",               // GEX/DEX heatmap table: gex | dex
    spectrumMode: "gex",           // Espectro 3D surface: gex | dex
    regimeMode: "gex",             // Gamma&Flow right column: gex | dex
    deltaKind: "call",             // delta surface: call | put
    volMode: "drift",              // volatility: drift | surface
    surf3d: true,                  // surfaces: 3D (default) | 2D heatmap
    timeframe: "5m",               // chart timeframe
    loaded: new Set(),             // "view:symbol[:sub]" already fetched+rendered
  };

  // ── formatting ─────────────────────────────────────────────────────────
  const fmtPrice = (v) => (v == null || !isFinite(v)) ? "—"
    : Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtLevel = (v) => (v == null || !isFinite(v)) ? "—"
    : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
  function fmtBig(v) {
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v), sign = v < 0 ? "-" : "";
    if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
    if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}K`;
    return `${sign}$${a.toFixed(0)}`;
  }
  const fmtPct = (v) => (v == null || !isFinite(v)) ? "—" : `${(v * 100).toFixed(2)}%`;
  const fmtInt = (v) => (v == null || !isFinite(v)) ? "—"
    : Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });

  // ── networking ───────────────────────────────────────────────────────────
  function setError(msg) {
    el("err").innerHTML = msg ? `<div class="error">${msg}</div>` : "";
  }
  async function fetchJSON(path) {
    if (!API) throw new Error("API no configurada. Edita config.js con la URL de tu backend (Render).");
    const res = await fetch(`${API}${path}`, { headers: window.PLAuth.authHeaders() });
    if (res.status === 401) { window.PLAuth.clearToken(); window.PLAuth.goLogin(); throw new Error("Sesión expirada"); }
    if (res.status === 403) { location.reload(); throw new Error("Acceso no activo"); }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }
  function levelShapes(d, L) {
    const shapes = [], anns = [];
    const add = (val, color, label) => {
      if (val == null || !isFinite(val)) return;
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: val, y1: val,
        line: { color, width: 1.4, dash: "dot" } });
      anns.push({ xref: "paper", x: 1, xanchor: "right", yref: "y", y: val, yanchor: "bottom",
        text: label, showarrow: false, font: { size: 9, color }, bgcolor: C.tagBg });
    };
    add(d.spot, C.text, `SPOT ${fmtLevel(d.spot)}`);
    add(L.call_wall, C.green, "CALL WALL");
    add(L.put_wall, C.red, "PUT WALL");
    add(L.gamma_flip, C.purple, "γ FLIP");
    return { shapes, anns };
  }

  // Build a moving ticker tape from metric cells. Content is duplicated so the
  // marquee loops seamlessly (the track animates translateX 0 → -50%).
  function tapeHTML(cells) {
    const chip = (x) => `<span class="chip ${x.c}"><b>${x.lbl}</b>` +
      `<span class="cv">${x.v}</span>${x.s ? `<span class="cs ${x.sc || ""}">${x.s}</span>` : ""}</span>`;
    const row = cells.map(chip).join("");
    return `<div class="tape-track">${row}${row}</div>`;
  }

  // ── Reference bar: Call/Put walls (top-3) + key levels ────────────────────
  // Persistent reference under the buscador, visible on every tab. Call walls
  // = largest positive-GEX strikes, put walls = largest negative, both from
  // the live /analyze payload. Vol Trigger mirrors the gamma flip (SpotGamma).
  function renderReference(d) {
    const box = el("refbar");
    if (!box || !d) return;
    const L = d.levels || {}, spot = d.spot;
    const pairs = (d.strikes || []).map((k, i) => ({ k: Number(k), v: Number((d.gex || [])[i]) || 0 }))
      .filter((p) => isFinite(p.k));
    const calls = pairs.filter((p) => p.v > 0).sort((a, b) => b.v - a.v).slice(0, 3);
    const puts = pairs.filter((p) => p.v < 0).sort((a, b) => a.v - b.v).slice(0, 3);

    const pct = (lvl) => (lvl == null || spot == null || !isFinite(lvl) || !spot) ? null : ((lvl - spot) / spot) * 100;
    const pctTag = (lvl) => {
      const p = pct(lvl); if (p == null) return "";
      const cls = p >= 0 ? "pos" : "neg";
      return `<span class="rtag ${cls}">${p >= 0 ? "+" : ""}${p.toFixed(2)}%</span>`;
    };
    const wall = (arr, cls) => arr.length
      ? arr.map((p) => `<div class="refrow"><span class="rk">$${fmtLevel(p.k)}</span><span class="rv ${cls}">${fmtBig(Math.abs(p.v))}</span></div>`).join("")
      : `<div class="refrow"><span class="rlbl">—</span></div>`;

    const flipTag = (spot != null && L.gamma_flip != null && isFinite(L.gamma_flip))
      ? `<span class="rtag ${spot < L.gamma_flip ? "neg" : "pos"}">${spot < L.gamma_flip ? "Below" : "Above"}</span>`
      : "";
    const keyRows = [
      ["Gamma Flip", L.gamma_flip, flipTag],
      ["Vol Trigger", L.gamma_flip, pctTag(L.gamma_flip)],
      ["Max Pain", L.max_pain, pctTag(L.max_pain)],
      ["Delta Wall", L.delta_wall, pctTag(L.delta_wall)],
      ["Major Neg Δ", L.major_neg_delta, pctTag(L.major_neg_delta)],
    ].map(([lbl, v, tag]) => `<div class="refkey"><span class="kk">${lbl}</span>
        <span class="kv">${v == null || !isFinite(v) ? "—" : "$" + fmtLevel(v)}${tag}</span></div>`).join("");

    box.innerHTML = `
      <div class="refcol"><div class="rx"><span class="dot call"></span>Call Walls</div>${wall(calls, "call")}</div>
      <div class="refcol"><div class="rx"><span class="dot put"></span>Put Walls</div>${wall(puts, "put")}</div>
      <div class="refcol"><div class="rx"><span class="dot key"></span>Key Levels</div><div class="refkeys">${keyRows}</div></div>`;
  }

  // Fetch /analyze for the reference bar with a WIDE strike window so the top
  // call/put walls reflect the whole chain (not just the ±24 steps the Gamma
  // view draws). Independent of the active view, cached server-side.
  async function loadReference() {
    try { renderReference(await fetchJSON(`/api/analyze/${state.symbol}?window=60`)); }
    catch (_) { /* non-fatal — keep whatever the bar already shows */ }
  }

  // Surface a data-quality problem instead of drawing an empty/garbage chart.
  function healthBanner(d) {
    const h = d && d.health;
    if (!h || h.ok) { if (h && h.warnings && h.warnings.length) setError(""); return false; }
    const msg = (h.issues || []).join(" ") || "Datos insuficientes de la fuente.";
    setError(`⚠️ Datos no disponibles para ${d.ticker || "este símbolo"}: ${msg}`);
    return true;
  }

  // ── view 1: GAMMA & FLOW ──────────────────────────────────────────────────
  function renderGamma(d) {
    const L = d.levels || {}, T = d.totals || {};
    // Empty / unhealthy feed → clear message, don't draw a blank chart.
    if (healthBanner(d) || !(d.strikes && d.strikes.length)) {
      renderReference(d);
      el("gammaChart").innerHTML =
        '<div class="loading">Sin datos de la cadena para graficar. ' +
        'Revisa el proveedor/plan o reintenta en un momento.</div>';
      renderRegime(d);
      return;
    }
    const cells = [
      { c: "", lbl: "Spot", v: fmtPrice(d.spot), s: `as of ${(d.asof || "").slice(0, 10)}`, sc: "" },
      { c: "call", lbl: "Call Wall", v: fmtLevel(L.call_wall), s: "resistance", sc: "pos" },
      { c: "put", lbl: "Put Wall", v: fmtLevel(L.put_wall), s: "support", sc: "neg" },
      { c: "gamma", lbl: "Gamma Flip", v: fmtLevel(L.gamma_flip), s: "regime pivot", sc: "" },
      { c: "pain", lbl: "Max Pain", v: fmtLevel(L.max_pain), s: "pin target", sc: "" },
      { c: "gamma", lbl: "Total GEX", v: fmtBig(T.gex), s: T.gex >= 0 ? "net long" : "net short", sc: T.gex >= 0 ? "pos" : "neg" },
      { c: "delta", lbl: "Total DEX", v: fmtBig(T.dex), s: T.dex >= 0 ? "net long" : "net short", sc: T.dex >= 0 ? "pos" : "neg" },
    ];
    const rib = el("ribbon"); rib.className = "tape"; rib.innerHTML = tapeHTML(cells);

    const strikesG = d.strikes || [];
    const gexV = d.gex || [];
    const gexColors = gexV.map((v) => (v >= 0 ? C.green : C.red));
    // relief sizing: bar thickness + a drop-shadow sliver below each bar
    const stepG = strikesG.length > 1 ? Math.abs(strikesG[1] - strikesG[0]) : 1;
    const barW = stepG * 0.66;
    const maxAbs = gexV.reduce((m, v) => Math.max(m, Math.abs(Number(v) || 0)), 0) || 1;
    // $ labels only on the meaningful bars so the chart doesn't get noisy
    const gexText = gexV.map((v) => (Math.abs(v) >= 0.16 * maxAbs ? fmtBig(v) : ""));
    const isLight = window.PLQTheme && window.PLQTheme.get() === "light";

    // shadow trace (drawn first → behind): a dark translucent copy shifted down
    // a sliver so each bar appears lifted off the surface (fake 3-D depth).
    const gexShadow = { type: "bar", orientation: "h", x: gexV, y: strikesG.map((s) => s - stepG * 0.16),
      width: barW, marker: { color: isLight ? "rgba(0,0,0,.16)" : "rgba(0,0,0,.42)", line: { width: 0 } },
      hoverinfo: "skip", showlegend: false, xaxis: "x", yaxis: "y", cliponaxis: false };

    const gexBars = { type: "bar", orientation: "h", x: gexV, y: strikesG, width: barW,
      marker: { color: gexColors, cornerradius: 5,
        line: { color: isLight ? "rgba(255,255,255,.55)" : "rgba(255,255,255,.22)", width: 1 } },
      name: "GEX", text: gexText, textposition: "outside", cliponaxis: false,
      textfont: { size: 9.5, color: gexColors, family: FONT.family },
      hovertemplate: "Strike %{y}<br>GEX %{x:$,.0f}<extra></extra>", xaxis: "x", yaxis: "y" };
    const dexLine = { type: "scatter", mode: "lines+markers", x: d.dex || [], y: d.dex_strikes || [],
      line: { color: C.cyan, width: 2 }, marker: { size: 4, color: C.cyan }, name: "DEX",
      hovertemplate: "Strike %{y}<br>DEX %{x:$,.0f}<extra></extra>", xaxis: "x2", yaxis: "y" };
    const { shapes, anns } = levelShapes(d, L);
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 66, r: 96, t: 28, b: 36 }, barmode: "overlay", bargap: 0.18,
      showlegend: true, legend: { orientation: "h", x: 0, y: isNarrow() ? 1.16 : 1.08, font: { color: C.text } },
      shapes, annotations: anns,
      xaxis: { title: { text: "Gamma Exposure ($)", font: { size: 10 } }, zeroline: true,
        zerolinecolor: C.border, gridcolor: C.grid, domain: [0, 1] },
      xaxis2: { overlaying: "x", side: "top", showgrid: false, zeroline: false,
        // En móvil quitamos el título del eje DEX (la leyenda ya lo indica) para que no se encime.
        title: { text: isNarrow() ? "" : "Delta Exposure ($)", font: { size: 10, color: C.cyan } },
        tickfont: { color: C.cyan, size: 9 } },
      yaxis: { title: { text: "Strike", font: { size: 10 } }, gridcolor: C.grid, zeroline: false,
        tickfont: { size: 10 }, fixedrange: false },
    });
    Plotly.react(el("gammaChart"), [gexShadow, gexBars, dexLine], layout, CONFIG);
    renderRegime(d);
  }
  // Right-column exposure panel — ranks the live chain by absolute GEX (or
  // DEX), SpotGamma-style: a GEX|DEX toggle, stat tiles, a put/call split
  // bar, and a ranked list of strikes with signed $ magnitude bars.
  let _regimeData = null;
  function renderRegime(d) {
    if (d) _regimeData = d;
    d = _regimeData;
    if (!d) return;
    const mode = state.regimeMode === "dex" ? "dex" : "gex";
    const T = d.totals || {};
    const strikes = (mode === "dex" ? d.dex_strikes : d.strikes) || [];
    const vals = (mode === "dex" ? d.dex : d.gex) || [];
    const net = mode === "dex" ? T.dex : T.gex;

    const pairs = strikes
      .map((k, i) => ({ k: Number(k), v: Number(vals[i]) || 0 }))
      .filter((p) => isFinite(p.k));
    let grossPos = 0, grossNeg = 0;
    pairs.forEach((p) => { if (p.v >= 0) grossPos += p.v; else grossNeg += -p.v; });
    const gross = grossPos + grossNeg || 1;
    const callPct = grossPos / gross, putPct = grossNeg / gross;
    const putHeavy = grossNeg >= grossPos;
    const biasPct = Math.round((putHeavy ? putPct : callPct) * 100);

    const callZone = pairs.filter((p) => p.v > 0).sort((a, b) => b.v - a.v)[0];
    const putZone = pairs.filter((p) => p.v < 0).sort((a, b) => a.v - b.v)[0];
    const ranked = pairs.slice().sort((a, b) => Math.abs(b.v) - Math.abs(a.v));
    const major = ranked[0];
    const maxAbs = ranked.length ? Math.abs(ranked[0].v) || 1 : 1;

    const netSign = net >= 0 ? "pos" : "neg";
    const M = mode.toUpperCase();
    const tiles = `
      <div class="rp-tiles">
        <div class="rp-tile"><span class="t">Net ${M}</span>
          <span class="vv ${netSign}">${fmtBig(net)}</span>
          <span class="ss">${net >= 0 ? "net long" : "net short"}</span></div>
        <div class="rp-tile"><span class="t">${mode === "dex" ? "Pos Zone" : "Call Zone"}</span>
          <span class="vv">${callZone ? "$" + fmtLevel(callZone.k) : "—"}</span>
          <span class="ss">${callZone ? fmtBig(callZone.v) : "—"}</span></div>
        <div class="rp-tile"><span class="t">${mode === "dex" ? "Neg Zone" : "Put Zone"}</span>
          <span class="vv">${putZone ? "$" + fmtLevel(putZone.k) : "—"}</span>
          <span class="ss">${putZone ? fmtBig(putZone.v) : "—"}</span></div>
        <div class="rp-tile"><span class="t">Bias</span>
          <span class="vv ${putHeavy ? "neg" : "pos"}">${putHeavy ? "PUT HEAVY" : "CALL HEAVY"}</span>
          <span class="ss">${biasPct}% of gross exp.</span></div>
        <div class="rp-tile wide"><span class="t">Major Zone</span>
          <span class="vv ${major && major.v < 0 ? "neg" : "pos"}">${major ? "$" + fmtLevel(major.k) : "—"}</span>
          <span class="ss">${major ? fmtBig(major.v) + " abs. exposure" : "—"}</span></div>
      </div>`;

    const split = `
      <div class="rp-split">
        <div class="put" style="width:${(putPct * 100).toFixed(1)}%">PUT ${Math.round(putPct * 100)}%</div>
        <div class="call">CALL ${Math.round(callPct * 100)}%</div>
      </div>`;

    const rows = ranked.slice(0, 14).map((p) => {
      const pos = p.v >= 0;
      const w = Math.max(3, (Math.abs(p.v) / maxAbs) * 100);
      return `<div class="rp-row">
        <span class="rp-k">$${fmtLevel(p.k)}</span>
        <span class="rp-track"><span class="rp-fill ${pos ? "pos" : "neg"}" style="width:${w.toFixed(1)}%"></span></span>
        <span class="rp-amt ${pos ? "pos" : "neg"}">${fmtBig(p.v)}</span>
      </div>`;
    }).join("");

    el("regimePanel").innerHTML = `
      <div class="rp-seg seg" id="regimeSeg">
        <button data-rmode="gex" class="${mode === "gex" ? "active" : ""}">GEX</button>
        <button data-rmode="dex" class="${mode === "dex" ? "active" : ""}">DEX</button>
      </div>
      ${tiles}
      ${split}
      <div class="rp-rank">${rows || '<div class="reading">Sin datos</div>'}</div>
      <div class="rp-foot">Current chain snapshot · ranked by absolute ${M}</div>`;

    el("regimePanel").querySelectorAll("[data-rmode]").forEach((b) => {
      b.onclick = () => { state.regimeMode = b.dataset.rmode; renderRegime(); };
    });
  }

  // ── view 2: CHART (candles + GEX profile sharing the price axis) ──────────
  function renderChart(d) {
    const L = d.levels || {};
    const bars = d.bars || [];
    const traces = [];
    if (bars.length) {
      traces.push({
        type: "candlestick",
        x: bars.map((b) => b.t),
        open: bars.map((b) => b.o), high: bars.map((b) => b.h),
        low: bars.map((b) => b.l), close: bars.map((b) => b.c),
        increasing: { line: { color: C.green } }, decreasing: { line: { color: C.red } },
        name: d.ticker, xaxis: "x", yaxis: "y",
      });
    }
    // GEX profile column on the right, same price (y) scale
    const gexColors = (d.gex || []).map((v) => (v >= 0 ? C.green : C.red));
    traces.push({
      type: "bar", orientation: "h", x: d.gex || [], y: d.strikes || [],
      marker: { color: gexColors, line: { width: 0 } }, name: "GEX", opacity: 0.85,
      hovertemplate: "Strike %{y}<br>GEX %{x:$,.0f}<extra></extra>",
      xaxis: "x2", yaxis: "y2",
    });

    const { shapes, anns } = levelShapes(d, L);
    const hasBars = bars.length > 0;
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 58, r: 60, t: 30, b: 34 },
      showlegend: false, shapes, annotations: anns,
      xaxis: { domain: [0, 0.80], anchor: "y", rangeslider: { visible: false },
        gridcolor: C.grid, tickfont: { size: 10 }, type: "date" },
      yaxis: { domain: [0, 1], anchor: "x", side: "right", gridcolor: C.grid,
        tickfont: { size: 10 }, title: { text: "Price", font: { size: 10 } },
        fixedrange: false },
      xaxis2: { domain: [0.82, 1], anchor: "y2", showgrid: false, zeroline: true,
        zerolinecolor: C.border, title: { text: "GEX", font: { size: 9 } },
        tickfont: { size: 8 } },
      yaxis2: { domain: [0, 1], anchor: "x2", matches: "y", showticklabels: false,
        showgrid: false },
    });
    if (!hasBars) {
      anns.push({ xref: "paper", yref: "paper", x: 0.4, y: 0.5, showarrow: false,
        text: "Intraday bars no disponibles para este símbolo/plan —<br>mostrando perfil GEX y niveles.",
        font: { size: 12, color: C.muted }, align: "center" });
    }
    Plotly.react(el("priceChart"), traces, layout, CONFIG);
  }

  // ── view 3: GEX / DEX HEATMAP (strike × DTE table, SpotGamma-style) ───────
  // Compact value label without a currency sign: 40.2M, -128.3M, 973.6K…
  function fmtHeat(v) {
    if (v == null || !isFinite(v)) return "";
    const a = Math.abs(v), s = v < 0 ? "-" : "";
    if (a >= 1e9) return `${s}${(a / 1e9).toFixed(1)}B`;
    if (a >= 1e6) return `${s}${(a / 1e6).toFixed(1)}M`;
    if (a >= 1e3) return `${s}${Math.round(a / 1e3)}K`;
    return `${s}${a.toFixed(0)}`;
  }
  // Diverging cell background: blue for positive, red for negative, intensity
  // by magnitude relative to the grid max (gamma sqrt so small cells still show).
  function heatColor(v, amax) {
    if (v == null || !isFinite(v) || v === 0) return "rgba(255,255,255,.02)";
    const t = Math.min(Math.abs(v) / amax, 1);
    const alpha = 0.14 + 0.80 * Math.pow(t, 0.55);
    return v > 0 ? `rgba(37,99,235,${alpha.toFixed(3)})`   // blue  #2563eb
                 : `rgba(220,38,38,${alpha.toFixed(3)})`;  // red   #dc2626
  }
  let _heatData = null;
  function renderGexHeat(d) {
    if (d) _heatData = d;
    d = _heatData;
    if (!d) return;
    const mode = state.heatMode === "dex" ? "dex" : "gex";
    const strikes = d.strikes || [];
    const Z = (mode === "dex" ? d.z_dex : d.z_gex) || d.z || [];
    const labels = (d.dte && d.dte.length)
      ? d.dte.map((x) => `${x}D`)
      : (d.expiries || []).map((e) => (e || "").slice(5));

    let amax = 1;
    for (const row of Z) for (const v of (row || []))
      if (v != null && isFinite(v)) amax = Math.max(amax, Math.abs(v));

    // nearest strike to spot → SPOT row
    let spotIdx = -1, best = Infinity;
    strikes.forEach((s, i) => { const g = Math.abs(s - (d.spot || 0)); if (g < best) { best = g; spotIdx = i; } });
    // rows top-to-bottom = highest strike first
    const order = strikes.map((_, i) => i).sort((a, b) => strikes[b] - strikes[a]);

    const title = mode === "dex" ? "DELTA EXPOSURE" : "GAMMA EXPOSURE";
    const head = `<tr><th class="hc sk">STRIKE</th>` +
      labels.map((l, j) => `<th class="hc${j === 0 ? " c0" : ""}">${l}</th>`).join("") + `</tr>`;
    const body = order.map((i) => {
      const spot = i === spotIdx;
      const cells = (Z[i] || []).map((v) =>
        `<td style="background:${heatColor(v, amax)}">${fmtHeat(v)}</td>`).join("");
      return `<tr class="${spot ? "spotrow" : ""}">` +
        `<th class="sk">$${fmtLevel(strikes[i])}${spot ? "<i>SPOT</i>" : ""}</th>${cells}</tr>`;
    }).join("");

    el("gexHeat").innerHTML = `
      <div class="heat-top"><span class="ht-title">${title}</span><span class="ht-sub">Strike × Expiry</span></div>
      <div class="heat-scroll"><table class="heat"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
  }

  // ── view 3b: ESPECTRO 3D (GEX/DEX Net surface over strike × expiry) ───────
  // Diverging surface centered at zero: green ridges = positive Net (C−P)
  // exposure, red valleys = negative — the "spectrum" look.
  const SPECTRUM_SCALE = [
    [0.0, "#ef4444"], [0.28, "rgba(239,68,68,.78)"], [0.47, "rgba(120,30,40,.25)"],
    [0.5, "rgba(20,26,43,.10)"], [0.53, "rgba(30,90,55,.25)"],
    [0.72, "rgba(34,197,94,.78)"], [1.0, "#22c55e"],
  ];
  // signed power-compression of the surface height so secondary ridges rise
  // relative to the tallest spike (true $ value stays in the hover/colour).
  const specComp = (v) => (v < 0 ? -1 : 1) * Math.pow(Math.abs(v), 0.80);
  function _pctAbs(flat, p) {
    const a = flat.filter((v) => v && isFinite(v)).map(Math.abs).sort((x, y) => x - y);
    if (!a.length) return 1;
    return a[Math.min(a.length - 1, Math.floor(p * a.length))] || a[a.length - 1] || 1;
  }
  let _spectrumData = null;
  function renderSpectrum(d) {
    if (d) _spectrumData = d;
    d = _spectrumData;
    if (!d) return;
    const mode = state.spectrumMode === "dex" ? "dex" : "gex";
    const strikes = d.strikes || [];
    const dte = (d.dte && d.dte.length) ? d.dte : (d.expiries || []).map((_, i) => i);
    const Z = (mode === "dex" ? d.z_dex : d.z_gex) || d.z || [];   // [strike][dte]
    const M = mode.toUpperCase();

    // header above the plot
    const tEl = el("spectrumTitle"), sEl = el("spectrumSub");
    if (tEl) tEl.textContent = `VISTA ESPECTRO · ${d.ticker || ""} · Spot $${fmtLevel(d.spot)}`;
    if (sEl) sEl.textContent = `${M} NET (C−P)`;

    // transpose to [dte][strike] so x = strike (front axis), y = DTE (depth)
    const Zt = dte.map((_, j) => strikes.map((_, i) => {
      const v = (Z[i] || [])[j];
      return (v == null || !isFinite(v)) ? 0 : v;
    }));
    const flat = Zt.flat();
    // robust colour scale (88th percentile) so more of the surface gets colour
    const cScale = _pctAbs(flat, 0.88) * 1.05;
    // robust HEIGHT scale: real chains have one huge ATM/0DTE cell that would
    // otherwise dominate the z-axis and flatten everything else to the base.
    // tanh(z / R) saturates that outlier and gives the whole terrain relief.
    // Higher percentile → gentler saturation → the big peaks tower over the
    // base instead of all flattening to the same height (more dramatic spikes).
    const R = _pctAbs(flat, 0.88) || 1;         // robust height scale (tanh)
    const disp = (v) => Math.tanh((Number(v) || 0) / R);   // bounded ~[-1,1]
    const use3d = state.surf3d && webglOK();

    if (use3d) {
      // REAL 3-D terrain, read as DISTINCT expiry ROWS across a WIDE strike
      // axis. Expiries are placed on an EVEN depth grid (by index, labelled
      // with their real DTE) so near-dated expiries still separate into their
      // own rows instead of collapsing into one column. Strikes stay crisp so
      // each level is legible; tanh height tames the ATM/0DTE outlier.
      const nS = strikes.length, nD = dte.length;
      // y = expiry index (even spacing) → clearly separated rows
      const yIdx = dte.map((_, j) => j);
      // raw tanh height (no smoothing) so each strike keeps its sharp peak
      const Zh = Zt.map((row) => row.map((v) => disp(v)));
      const txt = Zt.map((row) => row.map((v) => fmtBig(v)));

      const surf = {
        type: "surface", z: Zh, x: strikes, y: yIdx, surfacecolor: Zt,
        colorscale: SPECTRUM_SCALE, cmid: 0, cmin: -cScale, cmax: cScale, opacity: 0.97,
        contours: {
          x: { show: true, color: "rgba(255,255,255,.08)", width: 1 },      // strike grid lines
          y: { show: true, color: "rgba(255,255,255,.15)", width: 1 },      // row dividers
          z: { show: false },
        },
        lighting: { ambient: 0.78, diffuse: 0.6, specular: 0.12, roughness: 0.75 },
        colorbar: { title: { text: M, side: "right", font: { size: 9 } }, tickfont: { size: 8 },
          thickness: 10, len: 0.7, tickformat: "$~s" },
        text: txt, customdata: dte.map((dd) => strikes.map(() => dd)),
        hovertemplate: "Strike %{x:,.0f}<br>%{customdata}D<br>" + M + " %{text}<extra></extra>",
      };
      const traces = [surf];
      // SPOT marker: a vertical cyan line at the spot strike across all rows
      if (d.spot != null && isFinite(d.spot)) {
        traces.push({
          type: "scatter3d", mode: "lines", x: [d.spot, d.spot], y: [0, nD - 1], z: [0, 0],
          line: { color: C.cyan, width: 5 }, showlegend: false,
          hovertemplate: `SPOT $${fmtLevel(d.spot)}<extra></extra>`,
        });
      }
      // nice strike tick step (~10 labels), rounded to 5/10/25…
      const span = (strikes[nS - 1] - strikes[0]) || 1;
      const raw = span / 9, pow = Math.pow(10, Math.floor(Math.log10(raw)));
      const dtick = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) || pow * 10;
      const layout = Object.assign({}, BASE_LAYOUT, {
        margin: { l: 0, r: 0, t: 0, b: 0 }, showlegend: false,
        scene: {
          dragmode: "turntable", bgcolor: "rgba(0,0,0,0)",
          xaxis: Object.assign(SCENE_AX("Strike"), { tickfont: { size: 10 }, dtick,
            tick0: Math.ceil(strikes[0] / dtick) * dtick }),
          yaxis: Object.assign(SCENE_AX("Vencimiento"), { tickfont: { size: 9 },
            tickmode: "array", tickvals: yIdx, ticktext: dte.map((dd) => `${dd}D`) }),
          zaxis: Object.assign(SCENE_AX(`Net ${M} (relativo)`), { showticklabels: false }),
          // En móvil usamos la misma proporción/cámara compacta que Delta
          // Surface, para que el Espectro 3D se vea del mismo tamaño pequeño
          // y quepa completo (en PC se mantiene como estaba).
          camera: { eye: isNarrow() ? { x: 1.6, y: -1.5, z: 0.9 } : { x: 0.85, y: -1.85, z: 0.6 },
            center: { x: 0, y: 0, z: isNarrow() ? 0 : -0.04 } },
          aspectratio: isNarrow() ? { x: 1.3, y: 1.0, z: 0.7 } : { x: 2.4, y: 1.0, z: 1.25 },
        },
      });
      Plotly.react(el("spectrum"), traces, layout, CONFIG3D);
      return;
    }
    // 2-D fallback heatmap
    const heat = {
      type: "heatmap", z: Zt, x: strikes, y: dte, zmid: 0, zmin: -cScale, zmax: cScale,
      colorscale: [[0, C.red], [0.5, C.panel], [1, C.green]],
      colorbar: { title: { text: M, side: "right", font: { size: 9 } }, tickfont: { size: 8 },
        thickness: 10, tickformat: "$~s" },
      hovertemplate: "Strike %{x:,.0f}<br>%{y}D<br>" + M + " %{z:$,.0f}<extra></extra>",
    };
    const shapes = [];
    if (d.spot != null && isFinite(d.spot)) {
      shapes.push({ type: "line", xref: "x", x0: d.spot, x1: d.spot, yref: "paper", y0: 0, y1: 1,
        line: { color: C.cyan, width: 1.4, dash: "dot" } });
    }
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 50, r: 20, t: 16, b: 44 }, shapes,
      xaxis: { title: { text: "Strike", font: { size: 10 } }, gridcolor: C.grid, tickfont: { size: 9 } },
      yaxis: { title: { text: "Días a vencimiento", font: { size: 10 } }, gridcolor: C.grid, tickfont: { size: 9 } },
    });
    Plotly.react(el("spectrum"), [heat], layout, CONFIG);
  }

  // ── view 4: OI / % OI ──────────────────────────────────────────────────────
  let _oiData = null;
  function renderOI(d) {
    _oiData = d;
    drawOI();
  }
  function drawOI() {
    const d = _oiData; if (!d) return;
    const pct = state.oiMode === "pct";
    const call = pct ? d.call_pct : d.call_oi;
    const put = pct ? d.put_pct : d.put_oi;
    const fmt = pct ? "%{x:.2%}" : "%{x:,.0f}";
    const callT = { type: "bar", orientation: "h", y: d.strikes, x: call, name: "Calls",
      marker: { color: C.green }, hovertemplate: `Strike %{y}<br>Call ${fmt}<extra></extra>` };
    // puts drawn to the left (negative) for a mirrored profile
    const putT = { type: "bar", orientation: "h", y: d.strikes, x: put.map((v) => -v), name: "Puts",
      marker: { color: C.red },
      customdata: put, hovertemplate: `Strike %{y}<br>Put ${pct ? "%{customdata:.2%}" : "%{customdata:,.0f}"}<extra></extra>` };
    const shapes = [];
    if (d.spot != null && isFinite(d.spot)) {
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: d.spot, y1: d.spot,
        line: { color: C.text, width: 1.2, dash: "dot" } });
    }
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 62, r: 20, t: 30, b: 40 }, barmode: "overlay", bargap: 0.12, shapes,
      showlegend: true, legend: { orientation: "h", x: 0, y: 1.06, font: { color: C.text } },
      xaxis: { title: { text: pct ? "Share of total OI  (puts ◄ | ► calls)" : "Open Interest  (puts ◄ | ► calls)", font: { size: 10 } },
        gridcolor: C.grid, zeroline: true, zerolinecolor: C.border,
        tickformat: pct ? ".1%" : ",", tickfont: { size: 9 } },
      yaxis: { title: { text: "Strike", font: { size: 10 } }, tickfont: { size: 10 } },
    });
    Plotly.react(el("oiChart"), [putT, callT], layout, CONFIG);
  }

  // ── view: BIG TRADES (traded $ notional per level, call vs put) ───────────
  function renderFlow(d) {
    const rows = (d.rows || []).slice().reverse();   // largest at top
    const y = rows.map((r) => `$${fmtLevel(r.strike)}`);
    const callT = {
      type: "bar", orientation: "h", y, x: rows.map((r) => r.call_notional || 0),
      name: "Call $", marker: { color: C.green },
      customdata: rows.map((r) => [r.call_vol || 0]),
      hovertemplate: "Strike %{y}<br>Call $%{x:,.0f}<br>Vol %{customdata[0]:,.0f}<extra></extra>",
    };
    const putT = {
      type: "bar", orientation: "h", y, x: rows.map((r) => r.put_notional || 0),
      name: "Put $", marker: { color: C.red },
      customdata: rows.map((r) => [r.put_vol || 0]),
      hovertemplate: "Strike %{y}<br>Put $%{x:,.0f}<br>Vol %{customdata[0]:,.0f}<extra></extra>",
    };
    const anns = [];
    rows.forEach((r, i) => {
      if (r.vol_oi && r.vol_oi > 1) anns.push({
        xref: "paper", x: 1, xanchor: "right", yref: "y", y: y[i], yanchor: "middle",
        text: "● NUEVO", showarrow: false, font: { size: 9, color: C.amber } });
    });
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 72, r: 76, t: 28, b: 40 }, barmode: "stack", annotations: anns,
      showlegend: true, legend: { orientation: "h", x: 0, y: 1.06, font: { color: C.text } },
      xaxis: { title: { text: "$ nocional negociado hoy", font: { size: 10 } },
        gridcolor: C.grid, tickprefix: "$", tickformat: ".2s", tickfont: { size: 9 } },
      yaxis: { type: "category", automargin: true, tickfont: { size: 10 } },
    });
    Plotly.react(el("flowChart"), [callT, putT], layout, CONFIG);

    const t = d.totals || {};
    const callHeavy = (t.call_notional || 0) >= (t.put_notional || 0);
    const cells = [
      { c: "call", lbl: "Call $ hoy", v: fmtBig(t.call_notional), s: "flujo comprador", sc: "pos" },
      { c: "put", lbl: "Put $ hoy", v: fmtBig(t.put_notional), s: "flujo comprador", sc: "neg" },
      { c: callHeavy ? "call" : "put", lbl: "Sesgo", v: callHeavy ? "CALL HEAVY" : "PUT HEAVY", s: "del flujo $", sc: callHeavy ? "pos" : "neg" },
      { c: "gamma", lbl: "Nivel top", v: t.top_strike != null ? `$${fmtLevel(t.top_strike)}` : "—", s: "más $ hoy", sc: "" },
    ];
    const frib = el("flowRibbon"); frib.className = "tape"; frib.innerHTML = tapeHTML(cells);
  }

  // WebGL available? (true even for software WebGL; false only if truly absent)
  let _webgl = null;
  function webglOK() {
    if (_webgl !== null) return _webgl;
    try {
      const c = document.createElement("canvas");
      _webgl = !!(window.WebGLRenderingContext && (c.getContext("webgl") || c.getContext("experimental-webgl")));
    } catch (_) { _webgl = false; }
    return _webgl;
  }
  const SCENE_AX = (text) => ({ title: { text }, gridcolor: C.sceneGrid, color: C.muted,
    backgroundcolor: C.sceneBg, showbackground: true });

  // ── view 6: DELTA SURFACE (3-D surface, 2-D heatmap fallback/toggle) ──────
  // diverging scale centered on the panel colour (adapts to light/dark)
  const surfScale = () => [[0, C.red], [0.5, C.panel], [1, C.green]];
  let _dsurfData = null;
  function renderDeltaSurface(d) {
    _dsurfData = d;
    const use3d = state.surf3d && webglOK();
    if (use3d) {
      const surf = {
        type: "surface", z: d.z || [], x: d.spot_axis || [], y: d.days_axis || [],
        colorscale: surfScale(), cmid: d.kind === "put" ? -0.5 : 0.5,
        colorbar: { title: { text: "Δ", side: "right", font: { size: 9 } }, tickfont: { size: 8 }, thickness: 10 },
        hovertemplate: "Spot %{x:,.0f}<br>Días %{y:.0f}<br>Δ %{z:.3f}<extra></extra>",
      };
      const layout = Object.assign({}, BASE_LAYOUT, {
        margin: { l: 0, r: 0, t: 10, b: 0 },
        scene: {
          dragmode: "turntable",   // arrastrar = rotar (no pan)
          xaxis: SCENE_AX("Spot"), yaxis: SCENE_AX("Días a vencimiento"),
          zaxis: SCENE_AX(`${d.kind === "put" ? "Put" : "Call"} Δ`),
          camera: { eye: { x: 1.6, y: -1.5, z: 0.9 } }, aspectratio: { x: 1.3, y: 1, z: 0.7 },
        },
      });
      Plotly.react(el("deltaSurf"), [surf], layout, CONFIG3D);
      return;
    }
    const heat = {
      type: "heatmap", z: d.z || [], x: d.spot_axis || [], y: d.days_axis || [],
      colorscale: surfScale(), zmid: d.kind === "put" ? -0.5 : 0.5,
      colorbar: { title: { text: "Δ", side: "right", font: { size: 9 } }, tickfont: { size: 8 }, thickness: 10 },
      hovertemplate: "Spot %{x:,.0f}<br>Días %{y:.0f}<br>Δ %{z:.3f}<extra></extra>",
    };
    const shapes = [];
    if (d.spot != null && isFinite(d.spot)) {
      shapes.push({ type: "line", xref: "x", x0: d.spot, x1: d.spot, yref: "paper", y0: 0, y1: 1,
        line: { color: C.text, width: 1.3, dash: "dot" } });
    }
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 60, r: 20, t: 30, b: 44 }, shapes,
      xaxis: { title: { text: `Spot  ·  ${d.kind === "put" ? "Put" : "Call"} Δ`, font: { size: 10 } },
        gridcolor: C.grid, tickfont: { size: 10 } },
      yaxis: { title: { text: "Días a vencimiento", font: { size: 10 } }, gridcolor: C.grid, tickfont: { size: 10 } },
    });
    Plotly.react(el("deltaSurf"), [heat], layout, CONFIG);
  }

  // ── view 7: NET DRIFT (intraday premium drift + price) ────────────────────
  function renderNetDrift(d) {
    const t = d.t || [], T = d.totals || {};
    const BLUE = C.blue, WHITE = C.white;
    const callT = {
      type: "scatter", mode: "lines", x: t, y: d.call_drift || [], yaxis: "y",
      name: `Call Drift (${fmtBig(T.call_drift)})`, line: { color: C.red, width: 1.6 },
      fill: "tozeroy", fillcolor: "rgba(239,68,68,.16)",
      hovertemplate: "%{x}<br>Call drift %{y:$,.3s}<extra></extra>",
    };
    const putT = {
      type: "scatter", mode: "lines", x: t, y: d.put_drift || [], yaxis: "y",
      name: `Put Drift (${fmtBig(T.put_drift)})`, line: { color: BLUE, width: 1.6 },
      fill: "tozeroy", fillcolor: "rgba(59,130,246,.16)",
      hovertemplate: "%{x}<br>Put drift %{y:$,.3s}<extra></extra>",
    };
    const priceT = {
      type: "scatter", mode: "lines", x: t, y: d.price || [], yaxis: "y2",
      name: `${d.ticker || ""} (${fmtPrice(T.last)})`, line: { color: WHITE, width: 1.4 },
      hovertemplate: `%{x}<br>${d.ticker || ""} $%{y:,.2f}<extra></extra>`,
    };
    // Dos paneles apilados que COMPARTEN el eje de tiempo (sin doble eje):
    //  · arriba  (y)  = Premium drift ($) con Call/Put drift
    //  · abajo   (y2) = Precio del subyacente
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 66, r: 20, t: 92, b: 44 }, hovermode: "x unified",
      annotations: [{ xref: "paper", yref: "paper", x: 0.5, xanchor: "center",
        y: 1.17, yanchor: "bottom", showarrow: false,
        text: `Net Drift (Premium) · ${d.ticker || ""}`, font: { size: 12, color: C.text } }],
      showlegend: true,
      legend: { orientation: "h", x: 0.5, xanchor: "center", y: 1.04, font: { color: C.text, size: 11 } },
      xaxis: { type: "category", tickmode: "auto", nticks: 12, gridcolor: C.grid,
        tickfont: { size: 9 }, showgrid: true, anchor: "y2", domain: [0, 1] },
      yaxis: { domain: [0.56, 1], title: { text: "Premium drift ($)", font: { size: 10 } },
        gridcolor: C.grid, zeroline: true, zerolinecolor: C.border, tickfont: { size: 9 },
        tickformat: "$~s", anchor: "x" },
      yaxis2: { domain: [0, 0.46], title: { text: `Precio ${d.ticker || ""}`, font: { size: 10, color: WHITE } },
        gridcolor: C.grid, zeroline: false, tickfont: { size: 9, color: C.text },
        tickprefix: "$", anchor: "x" },
    });
    Plotly.react(el("netDrift"), [callT, putT, priceT], layout, CONFIG);
  }

  // ── view 8a: VOLATILITY — term structure (drift) ──────────────────────────
  function renderVolDrift(d) {
    const x = d.dte || [];
    const pctAxis = (name, arr, color, dash) => ({
      type: "scatter", mode: "lines+markers", x, y: (arr || []).map((v) => v == null ? null : v * 100),
      name, line: { color, width: 2, dash: dash || "solid" }, marker: { size: 5, color },
      hovertemplate: `${name} %{y:.1f}%<br>%{x} DTE<extra></extra>`,
    });
    const traces = [
      pctAxis("ATM IV", d.atm_iv, C.cyan),
      pctAxis("Call IV", d.call_iv, C.green, "dot"),
      pctAxis("Put IV", d.put_iv, C.red, "dot"),
    ];
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 60, r: 24, t: 30, b: 44 }, showlegend: true,
      legend: { orientation: "h", x: 0, y: 1.08, font: { color: C.text } },
      xaxis: { title: { text: "Days to expiry", font: { size: 10 } }, gridcolor: C.grid, tickfont: { size: 10 } },
      yaxis: { title: { text: "Implied volatility (%)", font: { size: 10 } }, gridcolor: C.grid,
        ticksuffix: "%", tickfont: { size: 10 } },
    });
    Plotly.react(el("volChart"), traces, layout, CONFIG);
  }

  // ── view 8b: VOLATILITY — surface (3-D surface, 2-D heatmap fallback/toggle)
  let _volSurfData = null;
  function renderVolSurface(d) {
    _volSurfData = d;
    const zpct = (d.z || []).map((row) => row.map((v) => v == null ? null : v * 100));
    const x = (d.dte && d.dte.length) ? d.dte : d.expiries;
    if (state.surf3d && webglOK()) {
      const surf = {
        type: "surface", z: zpct, x, y: d.strikes || [], colorscale: "Viridis",
        colorbar: { title: { text: "IV %", side: "right", font: { size: 9 } }, tickfont: { size: 8 }, thickness: 10 },
        hovertemplate: "DTE %{x}<br>Strike %{y:,.0f}<br>IV %{z:.1f}%<extra></extra>",
      };
      const layout = Object.assign({}, BASE_LAYOUT, {
        margin: { l: 0, r: 0, t: 10, b: 0 },
        scene: {
          dragmode: "turntable",   // arrastrar = rotar (no pan)
          xaxis: SCENE_AX("Días a vencimiento"), yaxis: SCENE_AX("Strike"), zaxis: SCENE_AX("IV %"),
          camera: { eye: { x: 1.7, y: -1.5, z: 0.8 } }, aspectratio: { x: 1.3, y: 1, z: 0.7 },
        },
      });
      Plotly.react(el("volChart"), [surf], layout, CONFIG3D);
      return;
    }
    const heat = {
      type: "heatmap", z: zpct, x, y: d.strikes || [], colorscale: "Viridis",
      colorbar: { title: { text: "IV %", side: "right", font: { size: 9 } }, tickfont: { size: 8 }, thickness: 10 },
      hovertemplate: "DTE %{x}<br>Strike %{y:,.0f}<br>IV %{z:.1f}%<extra></extra>",
    };
    const shapes = [];
    if (d.spot != null && isFinite(d.spot)) {
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: d.spot, y1: d.spot,
        line: { color: C.text, width: 1.3, dash: "dot" } });
    }
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 62, r: 20, t: 30, b: 44 }, shapes,
      xaxis: { title: { text: "Días a vencimiento", font: { size: 10 } }, gridcolor: C.grid, tickfont: { size: 9 } },
      yaxis: { title: { text: "Strike", font: { size: 10 } }, gridcolor: C.grid, tickfont: { size: 10 } },
    });
    Plotly.react(el("volChart"), [heat], layout, CONFIG);
  }

  // ── view registry ──────────────────────────────────────────────────────────
  const VIEWS = {
    gamma:   { plot: "gammaChart", symbolic: true,  path: (s) => `/api/analyze/${s}?window=24`, render: renderGamma },
    chart:   { plot: "priceChart", symbolic: true,  sub: () => state.timeframe,
               path: (s) => { const t = TF[state.timeframe] || TF["5m"];
                 return `/api/chart/${s}?window=24&interval=${t.interval}&period=${t.period}`; },
               render: renderChart },
    gexheat: { plot: "gexHeat",    symbolic: true,  path: (s) => `/api/gex_heatmap/${s}`,        render: renderGexHeat },
    spectrum:{ plot: "spectrum",   symbolic: true,  path: (s) => `/api/gex_heatmap/${s}?window=30&exp=10`, render: renderSpectrum },
    oi:      { plot: "oiChart",    symbolic: true,  path: (s) => `/api/oi/${s}?window=24`,        render: renderOI },
    flow:    { plot: "flowChart",  symbolic: true,  path: (s) => `/api/flow/${s}?top=18`,         render: renderFlow },
    dsurf:   { plot: "deltaSurf",  symbolic: true,  sub: () => state.deltaKind,
               path: (s) => `/api/delta_surface/${s}?kind=${state.deltaKind}`, render: renderDeltaSurface },
    drift:   { plot: "netDrift",   symbolic: true,  path: (s) => `/api/net_drift/${s}`,          render: renderNetDrift },
    vol:     { plot: "volChart",   symbolic: true,  sub: () => state.volMode,
               path: (s) => state.volMode === "surface" ? `/api/vol_surface/${s}` : `/api/vol_drift/${s}`,
               render: (d) => state.volMode === "surface" ? renderVolSurface(d) : renderVolDrift(d) },
  };

  async function loadView(view, { force = false } = {}) {
    const def = VIEWS[view];
    const plotEl = el(def.plot);
    const sym = def.symbolic ? state.symbol : "_";
    const sub = def.sub ? def.sub() : "";
    const key = `${view}:${sym}:${sub}`;
    if (!force && state.loaded.has(key)) return;
    setError("");
    const hadPlot = !!(plotEl && plotEl.data);   // Plotly stores .data on the div
    // On a cold start (Render free tier) the first request can take ~30-50s.
    // Show a reassuring message after a few seconds so it doesn't look hung.
    let slowTimer = null;
    if (!hadPlot) {
      plotEl.innerHTML = '<div class="loading">Cargando…</div>';
      slowTimer = setTimeout(() => {
        const l = plotEl.querySelector(".loading");
        if (l) l.textContent = "Despertando el servidor (puede tardar ~30s la primera vez)…";
      }, 4000);
    }
    try {
      const data = await fetchJSON(def.path(state.symbol));
      if (slowTimer) clearTimeout(slowTimer);
      // purge any existing plot so 3-D (WebGL) views re-render cleanly
      if (hadPlot) { try { Plotly.purge(plotEl); } catch (_) {} }
      def.render(data);
      state.loaded.add(key);
    } catch (e) {
      if (slowTimer) clearTimeout(slowTimer);
      try { Plotly.purge(plotEl); } catch (_) {}
      plotEl.innerHTML = "";
      const label = def.symbolic ? ` de ${state.symbol}` : "";
      setError(`No se pudieron cargar los datos${label}: ${e.message}`);
    }
  }

  function switchTo(view) {
    state.view = view;
    for (const t of document.querySelectorAll(".tab"))
      t.classList.toggle("active", t.dataset.view === view);
    for (const s of document.querySelectorAll(".view"))
      s.classList.toggle("hidden", s.id !== `view-${view}`);
    loadView(view).then(() => {
      const c = el(VIEWS[view].plot);
      if (c && c.data) Plotly.Plots.resize(c);
    });
  }

  function onTickerChange(pick) {
    state.pick = pick;
    state.symbol = U.resolve(pick) || DEFAULT_TICKER;
    el("tkName").textContent = U.isFutures(pick) ? `${pick} → ${state.symbol}` : state.symbol;
    state.loaded.clear();   // every view is symbol-specific now
    loadView(state.view, { force: true });
    loadReference();   // ref bar is symbol-specific, independent of the view
  }

  // ── account chrome ───────────────────────────────────────────────────────
  function renderAccount(st) {
    const user = st.user || {};
    const info = el("acctInfo");
    if (info) {
      let exp = '<span class="exp ok">Acceso · Aula</span>';
      if (st.lifetime) exp = '<span class="exp life">Acceso vitalicio</span>';
      else if (st.access_until) {
        const d = new Date(st.access_until.replace(" ", "T"));
        if (!isNaN(d)) exp = `<span class="exp ok">Acceso hasta ${d.toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" })}</span>`;
      }
      info.innerHTML = `<b>${user.name || user.email || ""}</b>${exp}`;
    }
    if (user.role === "admin") {
      const al = el("adminLink");
      if (al) { al.style.display = ""; al.href = "admin.html"; }
    }
    const lo = el("logoutBtn");
    if (lo) lo.addEventListener("click", () => window.PLAuth.logout());
  }

  // ── boot ────────────────────────────────────────────────────────────────
  function init() {
    const sel = el("ticker");
    U.populate(sel, DEFAULT_TICKER);
    sel.addEventListener("change", () => onTickerChange(sel.value));

    for (const t of document.querySelectorAll(".tab"))
      t.addEventListener("click", () => switchTo(t.dataset.view));

    el("oiMode").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      state.oiMode = b.dataset.mode;
      for (const x of el("oiMode").querySelectorAll("button"))
        x.classList.toggle("active", x === b);
      drawOI();   // redraw from cached data, no refetch
    });

    // GEX / DEX toggle on the heatmap table (re-render from cache, no refetch)
    el("heatMode").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      state.heatMode = b.dataset.hm;
      for (const x of el("heatMode").querySelectorAll("button"))
        x.classList.toggle("active", x === b);
      renderGexHeat();
    });

    // GEX / DEX toggle on the Espectro 3D surface (re-render from cache)
    el("spectrumMode").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      state.spectrumMode = b.dataset.sm;
      for (const x of el("spectrumMode").querySelectorAll("button"))
        x.classList.toggle("active", x === b);
      renderSpectrum();
    });

    // segmented toggles that switch which endpoint a view loads
    const segReload = (id, attr, field, view) => {
      el(id).addEventListener("click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        state[field] = b.dataset[attr];
        for (const x of el(id).querySelectorAll("button"))
          x.classList.toggle("active", x === b);
        loadView(view).then(() => {
          const c = el(VIEWS[view].plot);
          if (c && c.data) Plotly.Plots.resize(c);
        });
      });
    };
    segReload("deltaKind", "kind", "deltaKind", "dsurf");
    segReload("volMode", "mode", "volMode", "vol");
    segReload("timeframe", "tf", "timeframe", "chart");

    // 3D / 2D toggle for the surface views (re-renders from cached data)
    for (const seg of document.querySelectorAll(".surf3dToggle")) {
      seg.addEventListener("click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        state.surf3d = b.dataset.s3d === "3d";
        for (const t of document.querySelectorAll(".surf3dToggle button"))
          t.classList.toggle("active", t.dataset.s3d === b.dataset.s3d);
        if (state.view === "dsurf" && _dsurfData) renderDeltaSurface(_dsurfData);
        else if (state.view === "spectrum" && _spectrumData) renderSpectrum();
        else if (state.view === "vol" && state.volMode === "surface" && _volSurfData) renderVolSurface(_volSurfData);
        const c = el(VIEWS[state.view].plot);
        if (c && c.data) Plotly.Plots.resize(c);
      });
    }

    window.addEventListener("resize", () => {
      const c = el(VIEWS[state.view].plot);
      if (c && c.data) Plotly.Plots.resize(c);
    });

    // Recolor every chart when the user flips light/dark. We refresh the
    // palette and re-render the active view (cheap refetch keeps the code
    // simple and guarantees traces, scales and scene axes all pick up C.*).
    window.addEventListener("plq:themechange", () => {
      syncPalette();
      state.loaded.clear();
      loadView(state.view, { force: true }).then(() => {
        const c = el(VIEWS[state.view].plot);
        if (c && c.data) Plotly.Plots.resize(c);
      });
    });

    switchTo("gamma");
    loadReference();   // populate the reference bar on boot (wide strike scan)
  }

  // Gate the dashboard: valid Aula session + active quant access (coupon/pago).
  async function boot() {
    const st = await window.PLAuth.guard();
    if (!st) return;   // guard already redirected (login) or showed the paywall
    renderAccount(st);
    init();
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
