// ── ProfitLab Quant — configuración del frontend ──
// 1) URL del backend de datos (Render).
window.PROFITLAB_API = "https://profitlab-quant.onrender.com";

// 2) Aula Virtual (mismo dominio → sesión compartida con pl_token).
//    El acceso al dashboard se gestiona en el Aula: cupón o pago.
window.PROFITLAB_AULA = {
  // Base de la API PHP del Aula (cupones, pago, sesión). Ruta relativa porque
  // el Aula y el quant comparten dominio.
  apiBase: "/aulavirtual/api",
  // Login del Aula (a donde se envía a quien no tiene sesión).
  loginUrl: "/aulavirtual/login",
  // A dónde volver al cerrar sesión.
  homeUrl: "/aulavirtual",
  // Panel de gestión del Aula (solo se muestra a administradores).
  adminUrl: "/aulavirtual/admin/estudiantes",
};
