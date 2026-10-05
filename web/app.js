// ProfitLab Quant — frontend logic.
// Fetches /api/analyze/{ticker} from the backend (window.PROFITLAB_API),
// then renders the metric ribbon, the GEX-by-strike profile with the DEX
// overlay, and the dealer gamma-regime panel. Pure Plotly.js — no build step.

(function () {
  const U = window.PROFITLAB_UNIVERSE;
  const API = (window.PROFITLAB_API || "").replace(/\/+$/, "");

  const COLORS = {
    bg: "#05070b", panel: "#0b1220", grid: "#111a2b", border: "#1f2937",
    text: "#e2e8f0", muted: "#64748b",
    green: "#22c55e", red: "#ef4444", purple: "#a855f7",
    cyan: "#06b6d4", amber: "#f59e0b", yellow: "#facc15",
  };

  const el = (id) => document.getElementById(id);
  const DEFAULT_TICKER = "QQQ";

  // ── formatting helpers ──────────────────────────────────────────────────
  function fmtPrice(v) {
    if (v == null || !isFinite(v)) return "—";
    return Number(v).toLocaleString("en-US", {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
  }
  function fmtLevel(v) {
    if (v == null || !isFinite(v)) return "—";
    return Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  function fmtBig(v) {
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v);
    const sign = v < 0 ? "-" : "";
    if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
    if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}K`;
    return `${sign}$${a.toFixed(0)}`;
  }
  function fmtPct(v) {
    if (v == null || !isFinite(v)) return "—";
    return `${(v * 100).toFixed(2)}%`;
  }

  // ── metric ribbon ───────────────────────────────────────────────────────
  function renderRibbon(d) {
    const L = d.levels || {};
    const T = d.totals || {};
    const cells = [
      { cls: "", lbl: "Spot", val: fmtPrice(d.spot),
        sub: `as of ${(d.asof || "").slice(0, 10)}`, subcls: "" },
      { cls: "call", lbl: "Call Wall", val: fmtLevel(L.call_wall),
        sub: "resistance", subcls: "pos" },
      { cls: "put", lbl: "Put Wall", val: fmtLevel(L.put_wall),
        sub: "support", subcls: "neg" },
      { cls: "gamma", lbl: "Gamma Flip", val: fmtLevel(L.gamma_flip),
        sub: "regime pivot", subcls: "" },
      { cls: "pain", lbl: "Max Pain", val: fmtLevel(L.max_pain),
        sub: "pin target", subcls: "" },
      { cls: "gamma", lbl: "Total GEX", val: fmtBig(T.gex),
        sub: T.gex >= 0 ? "net long" : "net short",
        subcls: T.gex >= 0 ? "pos" : "neg" },
      { cls: "delta", lbl: "Total DEX", val: fmtBig(T.dex),
        sub: T.dex >= 0 ? "net long" : "net short",
        subcls: T.dex >= 0 ? "pos" : "neg" },
    ];
    el("ribbon").innerHTML = cells.map((c) => `
      <div class="cell ${c.cls}">
        <div class="lbl">${c.lbl}</div>
        <div class="val">${c.val}</div>
        <div class="sub ${c.subcls}">${c.sub}</div>
      </div>`).join("");
  }

  // ── GEX / DEX chart ─────────────────────────────────────────────────────
  function renderChart(d) {
    const strikes = d.strikes || [];
    const gex = d.gex || [];
    const dexStrikes = d.dex_strikes || [];
    const dex = d.dex || [];
    const L = d.levels || {};

    const gexColors = gex.map((v) => (v >= 0 ? COLORS.green : COLORS.red));

    const gexBars = {
      type: "bar", orientation: "h",
      x: gex, y: strikes,
      marker: { color: gexColors, line: { width: 0 } },
      name: "GEX", hovertemplate: "Strike %{y}<br>GEX %{x:$,.0f}<extra></extra>",
      xaxis: "x", yaxis: "y",
    };
    const dexLine = {
      type: "scatter", mode: "lines+markers", orientation: "h",
      x: dex, y: dexStrikes,
      line: { color: COLORS.cyan, width: 2 },
      marker: { size: 4, color: COLORS.cyan },
      name: "DEX", hovertemplate: "Strike %{y}<br>DEX %{x:$,.0f}<extra></extra>",
      xaxis: "x2", yaxis: "y",
    };

    const shapes = [];
    const anns = [];
    const hline = (val, color, label) => {
      if (val == null || !isFinite(val)) return;
      shapes.push({
        type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: val, y1: val,
        line: { color, width: 1.4, dash: "dot" },
      });
      anns.push({
        xref: "paper", x: 1, xanchor: "right", yref: "y", y: val, yanchor: "bottom",
        text: label, showarrow: false,
        font: { size: 9, color }, bgcolor: "rgba(5,7,11,.7)",
      });
    };
    hline(d.spot, COLORS.text, `SPOT ${fmtLevel(d.spot)}`);
    hline(L.call_wall, COLORS.green, "CALL WALL");
    hline(L.put_wall, COLORS.red, "PUT WALL");
    hline(L.gamma_flip, COLORS.purple, "γ FLIP");

    const layout = {
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: COLORS.muted, family: "Inter, sans-serif", size: 11 },
      margin: { l: 64, r: 70, t: 28, b: 36 },
      barmode: "overlay", bargap: 0.18,
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1.08, font: { color: COLORS.text } },
      shapes, annotations: anns,
      xaxis: {
        title: { text: "Gamma Exposure ($)", font: { size: 10 } },
        zeroline: true, zerolinecolor: COLORS.border,
        gridcolor: COLORS.grid, domain: [0, 1],
      },
      xaxis2: {
        overlaying: "x", side: "top", showgrid: false,
        zeroline: false, title: { text: "Delta Exposure ($)", font: { size: 10, color: COLORS.cyan } },
        tickfont: { color: COLORS.cyan, size: 9 },
      },
      yaxis: {
        title: { text: "Strike", font: { size: 10 } },
        gridcolor: COLORS.grid, zeroline: false,
        tickfont: { size: 10 }, fixedrange: false,
      },
    };
    const config = {
      responsive: true, displayModeBar: false, scrollZoom: true,
    };
    Plotly.react(el("chart"), [gexBars, dexLine], layout, config);
  }

  // ── regime panel ────────────────────────────────────────────────────────
  function renderRegime(d) {
    const r = d.regime || {};
    const L = d.levels || {};
    const label = (r.label || "UNKNOWN").toUpperCase();
    let cls = "trans";
    if (label.includes("LONG")) cls = "long";
    else if (label.includes("SHORT")) cls = "short";

    const gap = r.gap_pct;
    const gapTxt = gap == null ? "—"
      : `${gap >= 0 ? "+" : ""}${(gap * 100).toFixed(2)}% vs γ-flip`;

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
        ${statRow("Total GEX", fmtBig((d.totals || {}).gex))}
        ${statRow("Total DEX", fmtBig((d.totals || {}).dex))}
        ${statRow("Vanna", fmtBig((d.totals || {}).vanna))}
        ${statRow("Charm", fmtBig((d.totals || {}).charm))}
      </div>
      <div class="reading" style="margin-top:12px; font-size:10px; letter-spacing:.14em">
        VENDOR · ${(d.vendor || "—").toUpperCase()}
      </div>`;
  }
  function statRow(k, v) {
    return `<div class="statrow"><span class="k">${k}</span><span class="v">${v}</span></div>`;
  }

  // ── fetch + orchestrate ─────────────────────────────────────────────────
  function setError(msg) {
    el("err").innerHTML = msg ? `<div class="error">${msg}</div>` : "";
  }

  async function load(pick) {
    const symbol = U.resolve(pick) || DEFAULT_TICKER;
    el("tkName").textContent = U.isFutures(pick) ? `${pick} → ${symbol}` : symbol;
    setError("");
    el("chart").innerHTML = '<div class="loading">Cargando…</div>';
    el("ribbon").innerHTML = "";
    el("regimePanel").innerHTML = '<div class="loading">Cargando…</div>';

    if (!API) {
      setError("API no configurada. Edita config.js con la URL de tu backend (Render).");
      return;
    }

    try {
      const res = await fetch(`${API}/api/analyze/${encodeURIComponent(symbol)}?window=24`);
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
        throw new Error(detail);
      }
      const data = await res.json();
      renderRibbon(data);
      renderChart(data);
      renderRegime(data);
    } catch (e) {
      el("chart").innerHTML = "";
      el("regimePanel").innerHTML = "";
      setError(`No se pudieron cargar los datos de ${symbol}: ${e.message}`);
    }
  }

  // ── boot ────────────────────────────────────────────────────────────────
  function init() {
    const sel = el("ticker");
    U.populate(sel, DEFAULT_TICKER);
    sel.addEventListener("change", () => load(sel.value));
    load(DEFAULT_TICKER);

    // keep the chart responsive without a full reload
    window.addEventListener("resize", () => {
      const c = el("chart");
      if (c && c.data) Plotly.Plots.resize(c);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
