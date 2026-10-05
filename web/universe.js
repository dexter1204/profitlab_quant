// Ticker search universe — mirrors profitlab/universe.py.
// Three <optgroup>s: Options (stocks & ETFs) · Futures (→ index gamma) · Indices.
// Futures map to the index/ETF whose option gamma actually drives them, so a
// futures trader picks ES and the API loads SPX gamma.

(function () {
  const OPTIONS = [
    "QQQ", "SPY", "IWM", "DIA", "VOO", "VTI",
    "GLD", "SLV", "USO", "UNG", "GDX", "GDXJ",
    "TLT", "IEF", "HYG", "LQD",
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLP", "XLU", "XLY", "XLB", "XLRE", "XLC",
    "SMH", "SOXL", "SOXS", "TQQQ", "SQQQ", "SPXL", "SPXS",
    "ARKK", "KWEB", "FXI", "EEM", "EFA", "EWZ",
    "UVXY", "VXX", "SVXY",
    "BITO", "IBIT", "ETHA",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA",
    "AVGO", "AMD", "NFLX", "ADBE", "CRM", "ORCL", "CSCO", "INTC", "QCOM",
    "TXN", "MU", "AMAT", "ARM", "SMCI", "PLTR", "SNOW", "NOW", "PANW",
    "BRK.B", "JPM", "BAC", "WFC", "GS", "MS", "C", "SCHW", "V", "MA", "AXP",
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR",
    "XOM", "CVX", "COP", "SLB", "OXY",
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "MCD", "SBUX", "DIS",
    "PG", "KO", "PEP", "PM", "MDLZ",
    "BA", "CAT", "DE", "GE", "HON", "UPS", "FDX", "LMT", "RTX",
    "T", "VZ", "TMUS", "CMCSA",
    "COIN", "HOOD", "SOFI", "MSTR", "MARA", "RIOT", "CLSK",
    "GME", "AMC", "RKLB", "ACHR", "LUNR",
    "UBER", "LYFT", "ABNB", "DASH", "SHOP", "SQ", "PYPL", "ROKU",
    "DKNG", "RBLX", "U", "NET", "DDOG", "CRWD", "ZS", "MDB",
    "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "BABA", "PDD", "JD", "CVNA", "AFRM", "UPST", "DJT", "OKLO",
  ];

  // user sees the futures symbol; value is the underlying the API loads
  const FUTURES_MAP = {
    "ES": "SPX", "MES": "SPX",
    "NQ": "NDX", "MNQ": "NDX",
    "YM": "DJX", "MYM": "DJX",
    "RTY": "RUT", "M2K": "RUT",
    "CL": "USO", "MCL": "USO",
    "GC": "GLD", "MGC": "GLD",
    "SI": "SLV",
    "ZB": "TLT", "ZN": "IEF",
  };
  const FUTURES = Object.keys(FUTURES_MAP);

  const INDICES = ["SPX", "NDX", "VIX", "RUT", "DJX", "OEX"];

  // Resolve a dropdown pick to the symbol the API should load.
  function resolve(pick) {
    if (!pick) return null;
    const p = pick.trim().toUpperCase();
    return FUTURES_MAP[p] || p;
  }

  function isFutures(pick) {
    return !!pick && pick.trim().toUpperCase() in FUTURES_MAP;
  }

  // Populate a <select> with three labeled optgroups.
  function populate(selectEl, selected) {
    const groups = [
      ["OPTIONS · stocks & ETFs", OPTIONS],
      ["FUTURES → index gamma", FUTURES],
      ["INDICES", INDICES],
    ];
    selectEl.innerHTML = "";
    for (const [label, syms] of groups) {
      const og = document.createElement("optgroup");
      og.label = label;
      for (const s of syms) {
        const o = document.createElement("option");
        o.value = s;
        o.textContent = isFutures(s) ? `${s}  →  ${FUTURES_MAP[s]}` : s;
        if (s === selected) o.selected = true;
        og.appendChild(o);
      }
      selectEl.appendChild(og);
    }
  }

  window.PROFITLAB_UNIVERSE = {
    OPTIONS, FUTURES, FUTURES_MAP, INDICES, resolve, isFutures, populate,
  };
})();
