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
