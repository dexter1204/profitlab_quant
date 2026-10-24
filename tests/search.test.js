// Pruebas de la búsqueda estilo "Notas" (web/search.js).
// Sin framework: ejecuta con  →  node tests/search.test.js
"use strict";
const S = require("../web/search.js");

let pass = 0, fail = 0;
function ok(cond, name) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name); }
}
function eq(a, b, name) { ok(JSON.stringify(a) === JSON.stringify(b), name + "  (esperado " + JSON.stringify(b) + ", dio " + JSON.stringify(a) + ")"); }
function labels(q, items, n) { return S.rank(q, items, { limit: n }).map((r) => r.label); }

const UNIV = ["QQQ", "SPY", "NVDA", "SOXL", "SOXS", "SQ", "SQQQ", "TSLA", "BRK.B", "AMD", "SMH"];

console.log("\n1) Normalización (minúsculas + sin acentos)");
eq(S.norm("JosÉ"), "jose", "quita acento y baja a minúsculas");
eq(S.norm("Ñandú"), "nandu", "ñ→n y ú→u");
eq(S.norm("BRK.B"), "brk.b", "deja el punto, baja caja");

console.log("\n2) Jerarquía de ranking (exacta > prefijo > subcadena > fuzzy)");
ok(S.scoreOne("sq", "SQ").score > S.scoreOne("sq", "SQQQ").score, "exacta SQ gana a prefijo SQQQ");
ok(S.scoreOne("sox", "SOXL").score > S.scoreOne("mh", "SMH").score, "prefijo gana a subcadena interna");
ok(S.scoreOne("spy", "SPY").score > S.scoreOne("sy", "SPY").score, "coincidencia contigua gana a subsecuencia dispersa");

console.log("\n3) Orden de resultados sobre el universo");
eq(labels("sq", UNIV, 2), ["SQ", "SQQQ"], "'sq' → SQ (exacta) antes que SQQQ (prefijo)");
eq(labels("soxl", UNIV)[0], "SOXL", "'soxl' prioriza SOXL sobre SOXS");
eq(labels("nvda", UNIV)[0], "NVDA", "'nvda' encuentra NVDA");

console.log("\n4) Fuzzy por subsecuencia (letras en orden, no pegadas)");
ok(S.subseq("nda", "nvda") !== null, "'nda' es subsecuencia de nvda");
ok(S.subseq("adn", "nvda") === null, "'adn' NO (orden incorrecto)");
ok(labels("tla", UNIV).includes("TSLA"), "'tla' llega a TSLA por subsecuencia");
ok(labels("xyz", UNIV).length === 0, "query sin coincidencia → vacío");

console.log("\n5) Query vacía preserva el orden curado");
eq(labels("", UNIV, 3), ["QQQ", "SPY", "NVDA"], "sin query mantiene el orden original");

console.log("\n6) Resaltado de coincidencias (<mark>)");
const r = S.rank("sox", ["SOXL"])[0];
eq(S.highlight(r.label, r.hits), "<mark>S</mark><mark>O</mark><mark>X</mark>L", "marca S, O, X en SOXL");
eq(S.highlight("A<B", [1]), "A<mark>&lt;</mark>B", "escapa '<' al resaltar");

console.log("\n7) Alias de futuros (ES coincide por su subyacente SPX)");
const fut = [{ label: "ES", alias: "SPX" }, { label: "NQ", alias: "NDX" }];
const spx = S.rank("spx", fut)[0];
ok(spx && spx.label === "ES" && spx.viaAlias === true, "'spx' encuentra ES vía alias");

console.log("\n" + (fail ? "✗ " : "✓ ") + pass + " OK, " + fail + " fallos\n");
process.exit(fail ? 1 : 0);
