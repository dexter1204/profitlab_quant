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

  const getToken = () => { try { return localStorage.getItem(KEY) || ""; } catch (_) { return ""; } };
  const setToken = (t) => { try { localStorage.setItem(KEY, t); } catch (_) {} };
  const clearToken = () => { try { localStorage.removeItem(KEY); } catch (_) {} };
  const goLogin = () => { location.href = "login.html"; };
  function logout() { clearToken(); goLogin(); }

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
  function showPaywall(st) {
    const name = (st.user && st.user.name) ? st.user.name : "";
    const priceTxt = money(st.price, st.currency);
    const daysTxt = st.days > 0 ? `${st.days} días` : "acceso vitalicio";
    const wrap = document.createElement("div");
    wrap.id = "pl-paywall";
    wrap.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;" +
      "background:radial-gradient(1200px 700px at 20% -20%, #14161C 0%, #0A0B0E 60%);" +
      "font-family:'Manrope',system-ui,sans-serif;color:#CBD5E1;padding:24px";
    wrap.innerHTML = `
      <div style="width:100%;max-width:420px;background:#14161C;border:1px solid #1F222B;
        border-radius:16px;padding:28px 26px;box-shadow:0 24px 60px rgba(0,0,0,.5)">
        <div style="font-size:20px;font-weight:800;color:#F1F5F9;letter-spacing:-.01em;text-align:center;font-family:'Bricolage Grotesque','Manrope',sans-serif">
          Profit<span style="color:#C7F94C">Lab</span> Quant</div>
        <p style="color:#94a3b8;font-size:14px;line-height:1.55;margin:16px 0 20px;text-align:center">
          ${name ? "Hola <b style='color:#CBD5E1'>" + name + "</b>. " : ""}Activa tu acceso al dashboard.</p>

        <label style="display:block;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#94A3B8;font-weight:700;margin-bottom:6px">Tengo un cupón</label>
        <div style="display:flex;gap:8px">
          <input id="pl-code" placeholder="CÓDIGO" style="flex:1;background:#0A0B0E;color:#F1F5F9;border:1px solid #1F222B;border-radius:9px;padding:11px 13px;font-family:inherit;font-size:14px;text-transform:uppercase;letter-spacing:.1em;font-weight:700" />
          <button id="pl-redeem" style="background:#C7F94C;color:#0A0B0E;border:0;border-radius:9px;padding:0 16px;font-family:inherit;font-weight:700;cursor:pointer">Canjear</button>
        </div>
        <div id="pl-msg" style="font-size:13px;margin-top:10px;min-height:16px;color:#f87171"></div>

        <div style="display:flex;align-items:center;gap:10px;margin:18px 0;color:#475569;font-size:11px">
          <span style="flex:1;height:1px;background:#1F222B"></span>O<span style="flex:1;height:1px;background:#1F222B"></span>
        </div>

        <button id="pl-pay" style="width:100%;background:#14161C;border:1px solid rgba(199,249,76,.5);color:#C7F94C;border-radius:9px;padding:13px;font-family:inherit;font-size:14px;font-weight:700;cursor:pointer">
          Comprar acceso — ${priceTxt} · ${daysTxt}</button>
        <div style="text-align:center;margin-top:16px"><a id="pl-logout" style="color:#94A3B8;font-size:12px;cursor:pointer">Cerrar sesión</a></div>
      </div>`;
    document.body.innerHTML = "";
    document.body.appendChild(wrap);

    const msg = (t, ok) => { const m = document.getElementById("pl-msg"); m.textContent = t || ""; m.style.color = ok ? "#C7F94C" : "#f87171"; };
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
    if (!getToken()) { goLogin(); return null; }
    let st;
    try { st = await aula("GET", "/quant/me"); }
    catch (e) {
      if (e.status === 401) { clearToken(); goLogin(); return null; }
      document.body.innerHTML = '<div style="color:#f87171;font-family:system-ui;padding:40px">No se pudo contactar el Aula Virtual. Intenta de nuevo en un momento.</div>';
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
