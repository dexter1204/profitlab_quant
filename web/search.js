// ProfitLab Quant — búsqueda de activos estilo "Notas".
// Funciones PURAS (sin DOM) para que sean unit-testables con `node`.
// Mecanismo: normalización (minúsculas + sin acentos) → puntuación por
// niveles (exacta > prefijo > inicio-de-palabra > subcadena > subsecuencia
// difusa) → ranking → resaltado de los caracteres que coincidieron.
(function (root) {
  "use strict";

  // Minúsculas + quita diacríticos (á→a, ñ→n). Búsqueda insensible a
  // mayúsculas y acentos, igual que Notas/Spotlight. Para tickers ASCII
  // (A–Z, 0–9, ".") la longitud no cambia, así que los índices de
  // coincidencia siguen alineados con la etiqueta original (clave para
  // resaltar bien).
  function norm(s) {
    return (s == null ? "" : String(s))
      .normalize("NFD").replace(/[̀-ͯ]/g, "")
      .toLowerCase();
  }

  function isAlnum(c) { return c >= "a" && c <= "z" || c >= "0" && c <= "9"; }
  function range(a, b) { const r = []; for (let i = a; i < b; i++) r.push(i); return r; }

  // Subsecuencia: ¿aparecen todas las letras de `nq` dentro de `nl` en orden?
  // Devuelve los índices donde cayeron, o null si no.
  function subseq(nq, nl) {
    const hits = []; let j = 0;
    for (let i = 0; i < nl.length && j < nq.length; i++) {
      if (nl[i] === nq[j]) { hits.push(i); j++; }
    }
    return j === nq.length ? hits : null;
  }

  // Puntúa un candidato contra una query YA normalizada.
  // Devuelve {score, hits} (hits = índices que coinciden, para resaltar) o
  // null si no hay coincidencia. Más score = mejor.
  function scoreOne(nq, label) {
    const nl = norm(label);
    if (!nq) return { score: 0, hits: [] };
    if (nl === nq) return { score: 1000, hits: range(0, nl.length) };          // exacta
    if (nl.startsWith(nq)) return { score: 800 - (nl.length - nq.length), hits: range(0, nq.length) }; // prefijo
    const idx = nl.indexOf(nq);                                                // subcadena contigua
    if (idx >= 0) {
      const boundary = idx === 0 || !isAlnum(nl[idx - 1]);                     // bonus si cae en borde de palabra
      return { score: (boundary ? 600 : 400) - idx, hits: range(idx, idx + nq.length) };
    }
    const hits = subseq(nq, nl);                                               // subsecuencia difusa
    if (hits) {
      const spread = hits[hits.length - 1] - hits[0];                         // más apretado = mejor
      return { score: 200 - spread - hits[0], hits };
    }
    return null;
  }

  // Ordena una lista de items. Cada item: string, o {label, alias?}.
  // `alias` deja que un futuro (ES) coincida por su subyacente (SPX).
  // Devuelve [{item, label, score, hits, viaAlias}] de mejor a peor.
  // Query vacía → lista intacta (preserva el orden curado), score 0.
  function rank(query, items, opts) {
    opts = opts || {};
    const nq = norm(query);
    const out = [];
    for (const it of items) {
      const label = typeof it === "string" ? it : it.label;
      let best = scoreOne(nq, label);
      if (it && it.alias) {
        const a = scoreOne(nq, it.alias);
        if (a && (!best || a.score > best.score)) best = { score: a.score - 50, hits: [], viaAlias: true };
      }
      if (best) out.push({ item: it, label, score: best.score, hits: best.hits || [], viaAlias: !!best.viaAlias });
    }
    if (nq) {
      out.sort((a, b) => b.score - a.score || a.label.length - b.label.length || a.label.localeCompare(b.label));
    }
    return opts.limit ? out.slice(0, opts.limit) : out;
  }

  // HTML con los caracteres coincidentes envueltos en <mark>. Escapa la
  // etiqueta para que un símbolo raro no inyecte HTML.
  function highlight(label, hits) {
    const set = new Set(hits || []);
    const esc = (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] || c);
    let html = "";
    for (let i = 0; i < label.length; i++) {
      const c = esc(label[i]);
      html += set.has(i) ? "<mark>" + c + "</mark>" : c;
    }
    return html;
  }

  const api = { norm, scoreOne, subseq, rank, highlight };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PLSearch = api;
})(typeof window !== "undefined" ? window : globalThis);
