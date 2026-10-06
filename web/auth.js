// Auth via SSO with the Profit Lab Aula Virtual.
// The Aula stores its JWT in localStorage['pl_token'] on the same origin
// (profitlab-academy.com), so the quant dashboard reuses it directly — no
// separate login. Access is granted to users enrolled in the ProfitLab Quant
// course (enforced by the backend /api/access + gated data endpoints).

(function () {
  const API = (window.PROFITLAB_API || "").replace(/\/+$/, "");
  const AULA = window.PROFITLAB_AULA || {};
  const KEY = "pl_token";   // SAME key the Aula frontend uses

  const getToken = () => { try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; } };
  const clearToken = () => { try { localStorage.removeItem(KEY); } catch (_) {} };

  function authHeaders(extra) {
    const h = Object.assign({}, extra || {});
    const t = getToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }

  const goLogin = () => { location.href = AULA.loginUrl || "/"; };
  const goCourse = () => { location.href = AULA.courseUrl || AULA.homeUrl || "/"; };
  function logout() { clearToken(); location.href = AULA.homeUrl || AULA.loginUrl || "/"; }

  // Returns { authenticated, has_access, user } from the quant backend,
  // which delegates to the Aula API. Throws on network/unexpected errors.
  async function accessStatus() {
    if (!API) throw new Error("API no configurada (config.js).");
    const res = await fetch(`${API}/api/access`, { headers: authHeaders() });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
      const e = new Error(detail); e.status = res.status; throw e;
    }
    return res.json();
  }

  // Full-screen "no access" overlay with a path to get the course.
  function showNoAccess(user) {
    const name = (user && user.name) ? user.name : "";
    const wrap = document.createElement("div");
    wrap.id = "pl-noaccess";
    wrap.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;" +
      "background:radial-gradient(1200px 700px at 20% -20%, #0b1220 0%, #05070b 60%);" +
      "font-family:'Inter',system-ui,sans-serif;color:#e2e8f0;padding:24px";
    wrap.innerHTML = `
      <div style="max-width:420px;text-align:center;background:#0b1220;border:1px solid #1f2937;
        border-radius:16px;padding:30px 26px;box-shadow:0 24px 60px rgba(0,0,0,.5)">
        <div style="font-size:20px;font-weight:700;color:#f8fafc;letter-spacing:.04em">
          Profit<span style="color:#22c55e">Lab</span> Quant</div>
        <p style="color:#94a3b8;font-size:14px;line-height:1.55;margin:18px 0 22px">
          ${name ? "Hola <b style='color:#e2e8f0'>" + name + "</b>. " : ""}Tu cuenta del Aula no tiene acceso al
          <b style="color:#e2e8f0">dashboard ProfitLab Quant</b>. Adquiere o activa el curso para entrar.</p>
        <a href="${AULA.courseUrl || AULA.homeUrl || '#'}" style="display:inline-block;background:#22c55e;color:#04120a;
          text-decoration:none;border-radius:9px;padding:12px 20px;font-weight:700;font-size:14px">Ver el curso</a>
        <div style="margin-top:16px"><a id="pl-logout" style="color:#64748b;font-size:12px;cursor:pointer">Cerrar sesión</a></div>
      </div>`;
    document.body.innerHTML = "";
    document.body.appendChild(wrap);
    const lo = document.getElementById("pl-logout");
    if (lo) lo.addEventListener("click", logout);
  }

  // Gate a page. Resolves with the user when access is granted; otherwise
  // redirects (to Aula login) or renders the no-access screen and resolves null.
  async function guard() {
    if (!getToken()) { goLogin(); return null; }
    let st;
    try {
      st = await accessStatus();
    } catch (e) {
      if (e.status === 503) { document.body.innerHTML =
        '<div style="color:#f87171;font-family:system-ui;padding:40px">No se pudo contactar el Aula Virtual. Intenta de nuevo en un momento.</div>';
        return null;
      }
      goLogin(); return null;
    }
    if (!st.authenticated) { clearToken(); goLogin(); return null; }
    if (!st.has_access) { showNoAccess(st.user); return null; }
    return st.user;
  }

  window.PLAuth = { API, AULA, getToken, clearToken, authHeaders, accessStatus, guard, logout, goLogin, goCourse };
})();
