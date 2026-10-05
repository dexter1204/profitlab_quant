// ProfitLab Quant — frontend logic (multi-view).
// Tabs: Gamma & Flow · Chart · GEX Heatmap · OI / % OI · Market Heatmap.
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
  const BASE_LAYOUT = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: FONT,
  };
  const CONFIG = { responsive: true, displayModeBar: false, scrollZoom: true };

  // ── state ────────────────────────────────────────────────────────────────
  const state = {
    view: "gamma",
    pick: DEFAULT_TICKER,          // what the user selected (may be a future)
    symbol: DEFAULT_TICKER,        // resolved symbol the API loads
    oiMode: "oi",
    loaded: new Set(),             // "view:symbol" already fetched+rendered
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
    const res = await fetch(`${API}${path}`);
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

  // ── view 5: MARKET HEATMAP (treemap by sector, color = day change) ────────
  function renderMarket(d) {
    const rows = d.rows || [];
    const labels = [], parents = [], values = [], colors = [], texts = [], custom = [];
    const sectors = [...new Set(rows.map((r) => r.sector))];
    for (const s of sectors) { labels.push(s); parents.push(""); values.push(0); colors.push(0); texts.push(""); custom.push([null, null]); }
    for (const r of rows) {
      labels.push(r.ticker); parents.push(r.sector);
      values.push(Math.max(r.weight || 1, 1));
      colors.push((r.pct || 0) * 100);
      texts.push(`${r.ticker}<br>${(r.pct >= 0 ? "+" : "")}${(r.pct * 100).toFixed(2)}%`);
      custom.push([r.price, r.pct]);
    }
    const tm = {
      type: "treemap", branchvalues: "remainder",
      labels, parents, values,
      marker: {
        colors, cmid: 0, cmin: -4, cmax: 4,
        colorscale: [[0, C.red], [0.5, "#111a2b"], [1, C.green]],
        line: { color: C.bg, width: 1 },
      },
      text: texts, textinfo: "text", textfont: { size: 12, color: C.text },
      customdata: custom,
      hovertemplate: "%{label}<br>Price %{customdata[0]:,.2f}<br>Chg %{customdata[1]:.2%}<extra></extra>",
      tiling: { pad: 2 },
    };
    const layout = Object.assign({}, BASE_LAYOUT, { margin: { l: 6, r: 6, t: 6, b: 6 } });
    Plotly.react(el("marketHeat"), [tm], layout, CONFIG);

    const s = d.summary || {};
    const cells = [
      { lbl: "Symbols", v: fmtInt(s.n_symbols), sc: "" },
      { lbl: "Advancing", v: fmtInt(s.n_up), sc: "pos" },
      { lbl: "Declining", v: fmtInt(s.n_down), sc: "neg" },
      { lbl: "Breadth", v: fmtPct(s.breadth_pct), sc: s.breadth_pct >= 0.5 ? "pos" : "neg" },
      { lbl: "Best", v: `${(s.best || {}).ticker || "—"}`, sc: "pos", s2: fmtPct((s.best || {}).pct) },
      { lbl: "Worst", v: `${(s.worst || {}).ticker || "—"}`, sc: "neg", s2: fmtPct((s.worst || {}).pct) },
    ];
    el("marketSummary").innerHTML = cells.map((x) => `
      <div class="cell"><div class="lbl">${x.lbl}</div>
        <div class="val ${x.sc}">${x.v}</div>
        <div class="sub ${x.sc}">${x.s2 || (d.source === "demo" ? "demo" : "")}</div></div>`).join("");
  }

  // ── view registry ──────────────────────────────────────────────────────────
  const VIEWS = {
    gamma:   { plot: "gammaChart", symbolic: true,  path: (s) => `/api/analyze/${s}?window=24`, render: renderGamma },
    chart:   { plot: "priceChart", symbolic: true,  path: (s) => `/api/chart/${s}?window=24`,   render: renderChart },
    gexheat: { plot: "gexHeat",    symbolic: true,  path: (s) => `/api/gex_heatmap/${s}`,        render: renderGexHeat },
    oi:      { plot: "oiChart",    symbolic: true,  path: (s) => `/api/oi/${s}?window=24`,        render: renderOI },
    market:  { plot: "marketHeat", symbolic: false, path: () => `/api/market`,                   render: renderMarket },
  };

  async function loadView(view, { force = false } = {}) {
    const def = VIEWS[view];
    const sym = def.symbolic ? state.symbol : "_";
    const key = `${view}:${sym}`;
    if (!force && state.loaded.has(key)) return;
    setError("");
    el(def.plot).innerHTML = '<div class="loading">Cargando…</div>';
    try {
      const data = await fetchJSON(def.path(state.symbol));
      def.render(data);
      state.loaded.add(key);
    } catch (e) {
      el(def.plot).innerHTML = "";
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
    // invalidate per-symbol views; market is symbol-independent
    state.loaded = new Set([...state.loaded].filter((k) => k.startsWith("market:")));
    loadView(state.view, { force: true });
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
      drawOI();
    });

    window.addEventListener("resize", () => {
      const c = el(VIEWS[state.view].plot);
      if (c && c.data) Plotly.Plots.resize(c);
    });

    switchTo("gamma");
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
