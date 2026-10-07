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
    bg: "#05070b", panel: "#0b1220", grid: "#111a2b", border: "#1f2937",
    text: "#e2e8f0", muted: "#64748b",
    green: "#22c55e", red: "#ef4444", purple: "#a855f7",
    cyan: "#06b6d4", amber: "#f59e0b", yellow: "#facc15",
  };
  const FONT = { color: C.muted, family: "Inter, sans-serif", size: 11 };
  // dragmode "pan" = drag to move, wheel to zoom (TradingView-style); no
  // rubber-band box zoom. scrollZoom in CONFIG enables the wheel.
  const BASE_LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: FONT, dragmode: "pan",
  };
  const CONFIG = { responsive: true, displayModeBar: false, scrollZoom: true, doubleClick: "reset" };

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
      margin: { l: 64, r: 70, t: 28, b: 36 }, barmode: "overlay", bargap: 0.18,
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
  function statRow(k, v) {
    return `<div class="statrow"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  }
  function renderRegime(d) {
    const r = d.regime || {}, L = d.levels || {}, T = d.totals || {};
    const label = (r.label || "UNKNOWN").toUpperCase();
    let cls = "trans";
    if (label.includes("LONG")) cls = "long"; else if (label.includes("SHORT")) cls = "short";
    const gap = r.gap_pct;
    const gapTxt = gap == null ? "—" : `${gap >= 0 ? "+" : ""}${(gap * 100).toFixed(2)}% vs γ-flip`;
    el("regimePanel").innerHTML = `
      <h3>Dealer Regime</h3>
      <div class="regime ${cls}"><span class="dot"></span>${label}</div>
      <div style="text-align:center">
        <div class="price-big">${fmtPrice(d.spot)}</div>
        <div class="reading">${r.reading || ""}</div>
        <div class="reading" style="margin-top:2px">${gapTxt}</div>
      </div>
      <div style="margin-top:14px">
        ${statRow("Call Wall", fmtLevel(L.call_wall))}
        ${statRow("Put Wall", fmtLevel(L.put_wall))}
        ${statRow("Gamma Flip", fmtLevel(L.gamma_flip))}
        ${statRow("Delta Flip", fmtLevel(L.delta_flip))}
        ${statRow("Delta Wall", fmtLevel(L.delta_wall))}
        ${statRow("Major Neg Δ", fmtLevel(L.major_neg_delta))}
        ${statRow("Max Pain", fmtLevel(L.max_pain))}
      </div>
      <div style="margin-top:12px">
        ${statRow("Total GEX", fmtBig(T.gex))}
        ${statRow("Total DEX", fmtBig(T.dex))}
        ${statRow("Vanna", fmtBig(T.vanna))}
        ${statRow("Charm", fmtBig(T.charm))}
      </div>
      <div class="reading" style="margin-top:12px; font-size:10px; letter-spacing:.14em">
        VENDOR · ${(d.vendor || "—").toUpperCase()}</div>`;
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

  // ── view 3: GEX HEATMAP (strike × expiry) ─────────────────────────────────
  function renderGexHeat(d) {
    const z = d.z || [], strikes = d.strikes || [], expiries = d.expiries || [];
    // diverging red→green centered at zero
    const flat = z.flat().filter((v) => v != null && isFinite(v));
    const amax = flat.length ? Math.max(...flat.map(Math.abs)) : 1;
    const heat = {
      type: "heatmap", z, x: expiries, y: strikes,
      zmid: 0, zmin: -amax, zmax: amax,
      colorscale: [[0, C.red], [0.5, "#0b1220"], [1, C.green]],
      colorbar: { title: { text: "GEX", side: "right", font: { size: 9 } },
        tickfont: { size: 8 }, thickness: 10 },
      hovertemplate: "Expiry %{x}<br>Strike %{y}<br>GEX %{z:$,.0f}<extra></extra>",
    };
    const shapes = [];
    if (d.spot != null && isFinite(d.spot)) {
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: d.spot, y1: d.spot,
        line: { color: C.text, width: 1.4, dash: "dot" } });
    }
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 62, r: 20, t: 30, b: 70 }, shapes,
      xaxis: { title: { text: "Expiry", font: { size: 10 } }, tickangle: -40, tickfont: { size: 9 } },
      yaxis: { title: { text: "Strike", font: { size: 10 } }, tickfont: { size: 10 } },
    });
    Plotly.react(el("gexHeat"), [heat], layout, CONFIG);
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
  const SURF_SCALE = [[0, C.red], [0.5, "#111a2b"], [1, C.green]];
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

  // ── view 7: NET DRIFT ──────────────────────────────────────────────────────
  function renderNetDrift(d) {
    const x = d.spot_grid || [], y = d.net_delta || [];
    const line = {
      type: "scatter", mode: "lines", x, y,
      line: { color: C.cyan, width: 2.5 }, fill: "tozeroy",
      fillcolor: "rgba(6,182,212,.10)", name: "Net dealer Δ",
      hovertemplate: "Spot %{x:,.0f}<br>Net Δ %{y:$,.0f}<extra></extra>",
    };
    const shapes = [];
    const anns = [];
    const vline = (val, color, label) => {
      if (val == null || !isFinite(val) || val < x[0] || val > x[x.length - 1]) return;
      shapes.push({ type: "line", xref: "x", x0: val, x1: val, yref: "paper", y0: 0, y1: 1,
        line: { color, width: 1.4, dash: "dot" } });
      anns.push({ xref: "x", x: val, yref: "paper", y: 1, yanchor: "bottom", showarrow: false,
        text: label, font: { size: 9, color } });
    };
    vline(d.spot, C.text, `SPOT ${fmtLevel(d.spot)}`);
    vline(d.gamma_flip, C.purple, "γ FLIP");
    const layout = Object.assign({}, BASE_LAYOUT, {
      margin: { l: 70, r: 24, t: 30, b: 44 }, shapes, annotations: anns, showlegend: false,
      xaxis: { title: { text: "Spot price", font: { size: 10 } }, gridcolor: C.grid, tickfont: { size: 10 } },
      yaxis: { title: { text: "Net dealer dollar-delta ($)", font: { size: 10 } },
        gridcolor: C.grid, zeroline: true, zerolinecolor: C.border, tickfont: { size: 10 } },
    });
    Plotly.react(el("netDrift"), [line], layout, CONFIG);
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
