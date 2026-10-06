// Shared auth helpers for ProfitLab Quant (login, dashboard, admin).
// Token lives in localStorage; every API call carries it as a Bearer header.
// Loaded after config.js (which sets window.PROFITLAB_API).

(function () {
  const API = (window.PROFITLAB_API || "").replace(/\/+$/, "");
  const KEY = "pl_token";

  const getToken = () => { try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; } };
  const setToken = (t) => { try { localStorage.setItem(KEY, t); } catch (_) {} };
  const clearToken = () => { try { localStorage.removeItem(KEY); } catch (_) {} };

  function authHeaders(extra) {
    const h = Object.assign({ "Content-Type": "application/json" }, extra || {});
    const t = getToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }

  async function request(method, path, body) {
    if (!API) throw new Error("API no configurada (config.js).");
    const opts = { method, headers: authHeaders() };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(`${API}${path}`, opts);
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const err = new Error((data && data.detail) || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  const apiGet = (p) => request("GET", p);
  const apiPost = (p, b) => request("POST", p, b || {});

  // Redirect helpers (relative so they work under /quantsistem/).
  const goLogin = () => { location.href = "login.html"; };
  const goApp = () => { location.href = "index.html"; };

  function logout() { clearToken(); goLogin(); }

  // Guard a page: ensure a valid session. Returns the user, or redirects.
  // opts.admin → also require admin. opts.needAccess → require active access.
  async function guard(opts) {
    opts = opts || {};
    if (!getToken()) { goLogin(); return null; }
    let user;
    try {
      user = (await apiGet("/api/auth/me")).user;
    } catch (e) {
      if (e.status === 401) { clearToken(); goLogin(); return null; }
      throw e;
    }
    if (opts.admin && !user.is_admin) { location.href = "index.html"; return null; }
    return user;
  }

  window.PLAuth = {
    API, getToken, setToken, clearToken, authHeaders,
    apiGet, apiPost, logout, guard, goLogin, goApp,
  };
})();
