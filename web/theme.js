// ProfitLab Quant — theme controller (Apple light / dark / auto).
// Loads early (before paint) to avoid a flash, persists the choice, and
// exposes a palette + a `plq:themechange` event so Plotly charts recolor live.
(function () {
  var KEY = "plq_theme";          // "light" | "dark" | "auto"
  var root = document.documentElement;

  function stored() { try { return localStorage.getItem(KEY) || "auto"; } catch (_) { return "auto"; } }
  function systemDark() { try { return window.matchMedia("(prefers-color-scheme: dark)").matches; } catch (_) { return false; } }

  // effective = what's actually shown (resolves "auto")
  function effective(mode) { mode = mode || stored(); return mode === "auto" ? (systemDark() ? "dark" : "light") : mode; }

  function apply(mode) {
    if (mode === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
  }

  // Apply immediately (this script is placed in <head>, before body paints).
  apply(stored());

  // Palette for Plotly / canvas — reads the EFFECTIVE theme. Kept in sync with
  // theme.css tokens so charts match the chrome exactly.
  var PAL = {
    light: {
      paper: "rgba(0,0,0,0)", plot: "rgba(0,0,0,0)",
      text: "#1d1d1f", muted: "#6e6e73", grid: "rgba(0,0,0,.09)",
      border: "rgba(0,0,0,.14)", zero: "rgba(0,0,0,.22)", panel: "#ffffff",
      green: "#1f9d57", red: "#e0463b", accent: "#8ab320",
      purple: "#8a4be0", cyan: "#0a94c4", amber: "#e08c10", yellow: "#d6a908",
      blue: "#2563eb", white: "#1d1d1f",
      scene_bg: "rgba(0,0,0,0)", scene_grid: "rgba(0,0,0,.14)",
    },
    dark: {
      paper: "rgba(0,0,0,0)", plot: "rgba(0,0,0,0)",
      text: "#f5f5f7", muted: "#a1a1a6", grid: "rgba(255,255,255,.10)",
      border: "rgba(255,255,255,.16)", zero: "rgba(255,255,255,.28)", panel: "#1c1c1e",
      green: "#30d073", red: "#ff5247", accent: "#C7F94C",
      purple: "#b483ff", cyan: "#40c8ef", amber: "#ffa418", yellow: "#ffd60a",
      blue: "#4f8cff", white: "#e8eef7",
      scene_bg: "rgba(0,0,0,0)", scene_grid: "rgba(255,255,255,.14)",
    },
  };

  function palette() { return PAL[effective()]; }

  function set(mode) {
    try { localStorage.setItem(KEY, mode); } catch (_) {}
    apply(mode);
    emit();
  }

  // Cycle: light → dark → (back to light). "auto" collapses into the opposite
  // of what's currently shown, so a single click always flips the visible theme.
  function toggle() {
    set(effective() === "dark" ? "light" : "dark");
  }

  function emit() {
    try { window.dispatchEvent(new CustomEvent("plq:themechange", { detail: { theme: effective(), palette: palette() } })); } catch (_) {}
  }

  // React to OS theme changes while in "auto".
  try {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var onSys = function () { if (stored() === "auto") emit(); };
    mq.addEventListener ? mq.addEventListener("change", onSys) : mq.addListener(onSys);
  } catch (_) {}

  // Inject a round sun/moon toggle into any element with id="themeToggle".
  function mountToggle() {
    var host = document.getElementById("themeToggle");
    if (!host) return;
    host.classList.add("theme-toggle");
    host.setAttribute("type", "button");
    host.setAttribute("aria-label", "Cambiar tema claro/oscuro");
    host.innerHTML =
      '<svg class="ico-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>' +
      '<svg class="ico-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2.4M12 19.6V22M4.9 4.9l1.7 1.7M17.4 17.4l1.7 1.7M2 12h2.4M19.6 12H22M4.9 19.1l1.7-1.7M17.4 6.6l1.7-1.7"/></svg>';
    host.addEventListener("click", toggle);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountToggle);
  else mountToggle();

  window.PLQTheme = { get: effective, set: set, toggle: toggle, palette: palette, raw: stored };
  window.PLQ_THEME = palette();   // snapshot; refreshed on each themechange
  window.addEventListener("plq:themechange", function (e) { window.PLQ_THEME = e.detail.palette; });
})();
