// ── ProfitLab Quant — configuración del frontend ──
// 1) URL del backend de datos (Render).
window.PROFITLAB_API = "https://profitlab-quant.onrender.com";

// 2) Aula Virtual: el quant tiene su PROPIO login, pero valida las
//    credenciales (email + contraseña) contra las cuentas del Aula.
window.PROFITLAB_AULA = {
  // Base de la API PHP del Aula (login, cupones, pago). Ruta relativa porque
  // el Aula y el quant comparten dominio.
  apiBase: "/aulavirtual/api",
  // Registro de cuentas nuevas (en el Aula) — enlace desde el login del quant.
  signupUrl: "/aulavirtual/signup",
  // Panel de gestión del Aula (solo se muestra a administradores).
  adminUrl: "/aulavirtual/admin/estudiantes",
};

// 3) MODO DEMO LOCAL — automático al abrir desde localhost/127.0.0.1.
//    Salta el login del Aula y apunta a un backend FastAPI local en :8000
//    corriendo con PROFITLAB_VENDOR=demo PROFITLAB_DEMO=1 (datos mock, sin
//    internet). No afecta a producción: solo se activa en local.
(function () {
  var h = location.hostname;
  if (h === "localhost" || h === "127.0.0.1" || h === "0.0.0.0" || h === "") {
    window.PROFITLAB_DEMO = true;
    window.PROFITLAB_API = "http://127.0.0.1:8000";
  }
})();

// 4) WARM-UP del backend. En el plan gratuito de Render el servidor se
//    "duerme" tras 15 min y tarda ~30-50s en despertar en la 1ª petición.
//    Disparamos un ping a /api/health en CUANTO carga cualquier página
//    (login incluido): así Render despierta mientras el usuario lee/inicia
//    sesión, y el primer gráfico ya no espera el arranque en frío.
//    Fire-and-forget, no-cors para que ni CORS lo bloquee.
(function warmBackend() {
  try {
    if (!window.PROFITLAB_API) return;
    var ping = function () {
      try { fetch(window.PROFITLAB_API + "/api/health", { mode: "no-cors", cache: "no-store" }).catch(function () {}); }
      catch (e) {}
    };
    ping();
    // Reintento a los 3s por si el primer ping llega justo durante el arranque.
    setTimeout(ping, 3000);
  } catch (e) {}
})();
