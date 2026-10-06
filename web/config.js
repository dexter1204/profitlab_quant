// ── ProfitLab Quant — configuración del frontend ──
// 1) URL del backend de datos (Render).
window.PROFITLAB_API = "https://profitlab-quant.onrender.com";

// 2) Integración con el Aula Virtual (mismo dominio → sesión compartida).
//    Los alumnos inician sesión en el Aula; el quant reutiliza ese acceso.
window.PROFITLAB_AULA = {
  // Página de login del Aula (a donde se envía a quien no tiene sesión).
  loginUrl: "https://profitlab-academy.com/aulavirtual/login",
  // Página del curso "ProfitLab Quant" (a donde se envía a quien no tiene acceso).
  courseUrl: "https://profitlab-academy.com/aulavirtual/cursos",
  // Panel de gestión de alumnos del Aula (solo se muestra a administradores).
  adminUrl: "https://profitlab-academy.com/aulavirtual/admin/estudiantes",
  // A dónde volver al cerrar sesión.
  homeUrl: "https://profitlab-academy.com/aulavirtual",
};
