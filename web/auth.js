// Access control via the Aula Virtual (shared pl_token on the same domain).
// Gate = quant access, granted by a COUPON or a PAYMENT, both handled by the
// Aula PHP API. If the user has no access, we show a paywall: redeem a coupon,
// or pay (Mercado Pago) to unlock the dashboard.

(function () {
  const AULA = window.PROFITLAB_AULA || {};
  const API_BASE = (AULA.apiBase || "/aulavirtual/api").replace(/\/+$/, "");
  // Own session key — NOT the Aula's "pl_token", so the quant login is
  // independent. Credentials are still validated against the Aula accounts.
  const KEY = "plq_token";

  const DEMO = !!window.PROFITLAB_DEMO;
  const getToken = () => {
    if (DEMO) return "demo";   // local review: always "signed in"
    try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; }
  };
  const setToken = (t) => { try { localStorage.setItem(KEY, t); } catch (_) {} };
  const clearToken = () => { try { localStorage.removeItem(KEY); } catch (_) {} };
  const goLogin = () => { location.href = "login.html"; };
  function logout() { clearToken(); goLogin(); }

  // ── SSO desde el Aula / super-app ────────────────────────────────────────
  // Cuando el Aula embebe este dashboard en un iframe, pasa el JWT del alumno
  // por la URL: index.html#plq=<token> (o ?plq=<token>). Lo adoptamos como sesión
  // del quant y limpiamos la URL para no dejar el token a la vista. Sin esto el
  // iframe caía siempre en login.html aunque el alumno ya tuviera sesión y cupón.
  (function adoptSSOToken() {
    try {
      const src = (location.hash || "") + "&" + (location.search || "");
      const m = src.match(/[#&?]plq=([^&]+)/);
      if (m && m[1]) {
        setToken(decodeURIComponent(m[1]));
        // Quitar plq= de hash y query, conservando lo demás de la URL.
        const hash = (location.hash || "").replace(/([#&])plq=[^&]*/, "$1").replace(/[#&]$/, "");
        const search = (location.search || "").replace(/([?&])plq=[^&]*/, "$1").replace(/[?&]$/, "");
        history.replaceState(null, "", location.pathname + search + hash);
      }
    } catch (_) {}
  })();

  // Sign in with Aula credentials (email + password) via the Aula API.
  async function login(email, password) {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    let data = null; try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error((data && (data.error || data.detail)) || "Email o contraseña incorrectos");
    if (!data || !data.token) throw new Error("Respuesta inválida del Aula");
    setToken(data.token);
    return data;
  }

  function headers(extra) {
    const h = Object.assign({ "Content-Type": "application/json" }, extra || {});
    const t = getToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }
  async function aula(method, path, body) {
    const opts = { method, headers: headers() };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${path}`, opts);
    let data = null; try { data = await res.json(); } catch (_) {}
    if (!res.ok) { const e = new Error((data && data.detail) || (data && data.error) || `HTTP ${res.status}`); e.status = res.status; throw e; }
    return data;
  }

  const money = (v, cur) => {
    const n = Number(v);
    if (!isFinite(n)) return "";
    return (cur === "USD" ? "$" : (cur ? cur + " " : "")) + n.toLocaleString("es", { maximumFractionDigits: 2 });
  };

  // ── paywall (no access): redeem coupon or pay ────────────────────────────
  // Uses the shared Apple theme (theme.css / theme.js) so it matches the rest
  // of the app in light and dark.
  function showPaywall(st) {
    const name = (st.user && st.user.name) ? st.user.name : "";
    const priceTxt = money(st.price, st.currency);
    const daysTxt = st.days > 0 ? `${st.days} días` : "acceso vitalicio";
    const wrap = document.createElement("div");
    wrap.id = "pl-paywall";
    wrap.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;" +
      "background:var(--bg-grad);padding:24px";
    wrap.innerHTML = `
      <div class="card rise" style="width:100%;max-width:420px;padding:32px 28px">
        <div class="brand" style="font-size:24px;text-align:center">Profit<span>Lab</span> Quant</div>
        <p class="muted" style="font-size:14px;line-height:1.55;margin:16px 0 22px;text-align:center">
          ${name ? "Hola <b style='color:var(--text)'>" + name + "</b>. " : ""}Activa tu acceso al dashboard.</p>

        <label class="lbl" style="display:block;margin-bottom:7px">Tengo un cupón</label>
        <div style="display:flex;gap:8px">
          <input id="pl-code" placeholder="CÓDIGO" style="flex:1;min-width:0;text-transform:uppercase;letter-spacing:.1em;font-weight:650" />
          <button id="pl-redeem" class="btn primary" style="padding:0 20px">Canjear</button>
        </div>
        <div id="pl-msg" style="font-size:13px;margin-top:10px;min-height:16px;color:var(--red-soft)"></div>

        <div style="display:flex;align-items:center;gap:10px;margin:20px 0;color:var(--text-3);font-size:11px">
          <span style="flex:1;height:1px;background:var(--border)"></span>O<span style="flex:1;height:1px;background:var(--border)"></span>
        </div>

        <button id="pl-pay" class="btn block" style="border-color:color-mix(in srgb, var(--accent) 50%, transparent);color:var(--accent-text);font-weight:600">
          Comprar acceso — ${priceTxt} · ${daysTxt}</button>
        <div style="text-align:center;margin-top:18px"><a id="pl-logout" class="muted" style="font-size:12px;cursor:pointer">Cerrar sesión</a></div>
      </div>`;
    document.body.innerHTML = "";
    document.body.appendChild(wrap);

    const msg = (t, ok) => { const m = document.getElementById("pl-msg"); m.textContent = t || ""; m.style.color = ok ? "var(--green-soft)" : "var(--red-soft)"; };
    document.getElementById("pl-logout").addEventListener("click", logout);
    document.getElementById("pl-redeem").addEventListener("click", async () => {
      const code = (document.getElementById("pl-code").value || "").trim().toUpperCase();
      if (!code) { msg("Ingresa tu cupón."); return; }
      try { await aula("POST", "/quant/redeem", { code }); msg("¡Acceso activado! Entrando…", true); setTimeout(() => location.reload(), 700); }
      catch (e) { msg(e.message || "No se pudo canjear."); }
    });
    document.getElementById("pl-code").addEventListener("keydown", (e) => { if (e.key === "Enter") document.getElementById("pl-redeem").click(); });
    document.getElementById("pl-pay").addEventListener("click", async () => {
      msg("Abriendo el pago…", true);
      try { const d = await aula("POST", "/quant/checkout", {}); if (d && d.init_point) location.href = d.init_point; else msg("No se pudo iniciar el pago."); }
      catch (e) { msg(e.message || "No se pudo iniciar el pago."); }
    });
  }

  // Gate a page. Resolves with the user when access is active; otherwise
  // redirects to the Aula login or renders the paywall and resolves null.
  async function guard() {
    // Local demo: fake an active session so the dashboard renders without the
    // Aula. The local backend (PROFITLAB_DEMO=1) also skips its own gate.
    if (DEMO) {
      return { user: { name: "Demo", email: "demo@local", role: "admin" },
               has_access: true, lifetime: true, access_until: null };
    }
    if (!getToken()) { goLogin(); return null; }
    let st;
    try { st = await aula("GET", "/quant/me"); }
    catch (e) {
      if (e.status === 401) { clearToken(); goLogin(); return null; }
      document.body.innerHTML = '<div style="color:var(--red-soft);font-family:var(--font, system-ui);padding:40px">No se pudo contactar el Aula Virtual. Intenta de nuevo en un momento.</div>';
      return null;
    }
    if (!st.has_access) { showPaywall(st); return null; }
    return st;   // { user, has_access, access_until, lifetime, price, currency, days }
  }

  window.PLAuth = {
    AULA, API_BASE, getToken, setToken, clearToken, headers, authHeaders: headers,
    aula, login, guard, logout, goLogin, showPaywall,
  };
})();
