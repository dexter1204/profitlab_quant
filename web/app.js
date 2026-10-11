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

  const C = {
    // Gama del Aula ProfitLab (mismo diseño que la app)
    bg: "#0A0B0E", panel: "#14161C", grid: "#1F222B", border: "#1F222B",
    text: "#CBD5E1", muted: "#94A3B8", lime: "#C7F94C",
    green: "#22c55e", red: "#ef4444", purple: "#a855f7",
    cyan: "#06b6d4", amber: "#f59e0b", yellow: "#facc15",
  };
  const FONT = { color: C.muted, family: "Manrope, sans-serif", size: 11 };
  // dragmode "pan" = drag to move, wheel to zoom (TradingView-style); no
  // rubber-band box zoom. scrollZoom in CONFIG enables the wheel.
  const BASE_LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: FONT, dragmode: "pan",
  };
  const CONFIG = { responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: "reset" };

  // En móvil recortamos los márgenes internos de Plotly para que el área de
  // la gráfica ocupe más ancho (en PC se mantienen los valores de escritorio).
  const isNarrow = () => (typeof window !== "undefined" && window.innerWidth <= 640);

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
        text: label, showarrow: false, font: { size: 9, color }, bgcolor: "rgba(5,7,11,.7)" });
    };
    add(d.spot, C.text, `SPOT ${fmtLevel(d.spot)}`);
    add(L.call_wall, C.green, "CALL WALL");
    add(L.put_wall, C.red, "PUT WALL");
    add(L.gamma_flip, C.purple, "γ FLIP");
    return { shapes, anns };
  }

  // ── view 1: GAMMA & FLOW ──────────────────────────────────────────────────
  function renderGamma(d) {
    const L = d.levels || {}, T = d.totals || {};
    const cells = [
      { c: "", lbl: "Spot", v: fmtPrice(d.spot), s: `as of ${(d.asof || "").slice(0, 10)}`, sc: "" },
      { c: "call", lbl: "Call Wall", v: fmtLevel(L.call_wall), s: "resistance", sc: "pos" },
      { c: "put", lbl: "Put Wall", v: fmtLevel(L.put_wall), s: "support", sc: "neg" },
      { c: "gamma", lbl: "Gamma Flip", v: fmtLevel(L.gamma_flip), s: "regime pivot", sc: "" },
      { c: "pain", lbl: "Max Pain", v: fmtLevel(L.max_pain), s: "pin target", sc: "" },
      { c: "gamma", lbl: "Total GEX", v: fmtBig(T.gex), s: T.gex >= 0 ? "net long" : "net short", sc: T.gex >= 0 ? "pos" : "neg" },
      { c: "delta", lbl: "Total DEX", v: fmtBig(T.dex), s: T.dex >= 0 ? "net long" : "net short", sc: T.dex >= 0 ? "pos" : "neg" },
    ];
    el("ribbon").innerHTML = cells.map((x) => `
      <div class="cell ${x.c}">
        <div class="lbl">${x.lbl}</div><div class="val">${x.v}</div>
        <div class="sub ${x.sc}">${x.s}</div></div>`).join("");

    const gexColors = (d.gex || []).map((v) => (v >= 0 ? C.green : C.red));
    const gexBars = { type: "bar", orientation: "h", x: d.gex || [], y: d.strikes || [],
      marker: { color: gexColors, line: { width: 0 } }, name: "GEX",
      hovertemplate: "Strike %{y}<br>GEX %{x:$,.0f}<extra></extra>", xaxis: "x", yaxis: "y" };
    const dexLine = { type: "scatter", mode: "lines+markers", x: d.dex || [], y: d.dex_strikes || [],
      line: { color: C.cyan, width: 2 }, marker: { size: 4, color: C.cyan }, name: "DEX",
      hovertemplate: "Strike %{y}<br>DEX %{x:$,.0f}<extra></extra>", xaxis: "x2", yaxis: "y" };
    const { shapes, anns } = levelShapes(d, L);
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: isNarrow() ? { l: 44, r: 30, t: 26, b: 34 } : { l: 64, r: 70, t: 28, b: 36 }, barmode: "overlay", bargap: 0.18,
      showlegend: true, legend: { orientation: "h", x: 0, y: 1.08, font: { color: C.text } },
      shapes, annotations: anns,
      xaxis: { title: { text: "Gamma Exposure ($)", font: { size: 10 } }, zeroline: true,
        zerolinecolor: C.border, gridcolor: C.grid, domain: [0, 1] },
      xaxis2: { overlaying: "x", side: "top", showgrid: false, zeroline: false,
        title: { text: "Delta Exposure ($)", font: { size: 10, color: C.cyan } },
        tickfont: { color: C.cyan, size: 9 } },
      yaxis: { title: { text: "Strike", font: { size: 10 } }, gridcolor: C.grid, zeroline: false,
        tickfont: { size: 10 }, fixedrange: false },
    });
    Plotly.react(el("gammaChart"), [gexBars, dexLine], layout, CONFIG);
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
          // En móvil: superficie menos ancha y cámara más alejada para que
          // quepa completa en la pantalla (en PC se mantiene como estaba).
          camera: { eye: isNarrow() ? { x: 1.05, y: -2.25, z: 0.78 } : { x: 0.85, y: -1.85, z: 0.6 },
            center: { x: 0, y: 0, z: isNarrow() ? -0.16 : -0.04 } },
          aspectratio: isNarrow() ? { x: 1.55, y: 1.0, z: 1.05 } : { x: 2.4, y: 1.0, z: 1.25 },
        },
      });
      Plotly.react(el("spectrum"), traces, layout, { responsive: true, displayModeBar: false });
      return;
    }
    // 2-D fallback heatmap
    const heat = {
      type: "heatmap", z: Zt, x: strikes, y: dte, zmid: 0, zmin: -cScale, zmax: cScale,
      colorscale: [[0, C.red], [0.5, "#14161C"], [1, C.green]],
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
    el("flowRibbon").innerHTML = cells.map((x) => `
      <div class="cell ${x.c}"><div class="lbl">${x.lbl}</div>
        <div class="val">${x.v}</div><div class="sub ${x.sc}">${x.s}</div></div>`).join("");
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
  const SCENE_AX = (text) => ({ title: { text }, gridcolor: C.border, color: C.muted,
    backgroundcolor: "rgba(0,0,0,0)", showbackground: true });

  // ── view 6: DELTA SURFACE (3-D surface, 2-D heatmap fallback/toggle) ──────
  const SURF_SCALE = [[0, C.red], [0.5, "#14161C"], [1, C.green]];
  let _dsurfData = null;
  function renderDeltaSurface(d) {
    _dsurfData = d;
    const use3d = state.surf3d && webglOK();
    if (use3d) {
      const surf = {
        type: "surface", z: d.z || [], x: d.spot_axis || [], y: d.days_axis || [],
        colorscale: SURF_SCALE, cmid: d.kind === "put" ? -0.5 : 0.5,
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
      Plotly.react(el("deltaSurf"), [surf], layout, { responsive: true, displayModeBar: false });
      return;
    }
    const heat = {
      type: "heatmap", z: d.z || [], x: d.spot_axis || [], y: d.days_axis || [],
      colorscale: SURF_SCALE, zmid: d.kind === "put" ? -0.5 : 0.5,
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
    const BLUE = "#3b82f6", WHITE = "#e8eef7";
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
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 66, r: 60, t: 90, b: 42 }, hovermode: "x unified",
      annotations: [{ xref: "paper", yref: "paper", x: 0.5, xanchor: "center",
        y: 1.15, yanchor: "bottom", showarrow: false,
        text: `Net Drift (Premium) · ${d.ticker || ""}`, font: { size: 12, color: C.text } }],
      showlegend: true,
      legend: { orientation: "h", x: 0.5, xanchor: "center", y: 1.02, font: { color: C.text, size: 11 } },
      xaxis: { type: "category", tickmode: "auto", nticks: 14, gridcolor: C.grid,
        tickfont: { size: 9 }, showgrid: true },
      yaxis: { title: { text: "Premium drift ($)", font: { size: 10 } }, gridcolor: C.grid,
        zeroline: true, zerolinecolor: C.border, tickfont: { size: 9 }, tickformat: "$~s" },
      yaxis2: { overlaying: "y", side: "right", showgrid: false, zeroline: false,
        title: { text: "Precio", font: { size: 10, color: WHITE } },
        tickfont: { size: 9, color: "#cbd5e1" }, tickprefix: "$" },
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
      Plotly.react(el("volChart"), [surf], layout, { responsive: true, displayModeBar: false });
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
    if (!hadPlot) plotEl.innerHTML = '<div class="loading">Cargando…</div>';
    try {
      const data = await fetchJSON(def.path(state.symbol));
      // purge any existing plot so 3-D (WebGL) views re-render cleanly
      if (hadPlot) { try { Plotly.purge(plotEl); } catch (_) {} }
      def.render(data);
      state.loaded.add(key);
    } catch (e) {
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

    switchTo("gamma");
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
