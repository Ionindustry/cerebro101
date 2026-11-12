// Textos del cuadro «Modelos externos» (Claude y ChatGPT para consultas complejas). Sin dependencias: se prueba con node --test.
export const ESTADOS = {
  conectado: { texto: "Conectado", color: "#2e7d4f" },
  desconectado: { texto: "Desconectado", color: "#9a9aa2" },
  sin_clave: { texto: "Falta la clave", color: "#c98a0b" },
};

export const resumen = (proveedores = []) => {
  const on = proveedores.filter((p) => p.estado === "conectado").map((p) => p.nombre.split(" ")[0]);
  return on.length ? `${on.join(" y ")} conectado${on.length > 1 ? "s" : ""}` : "todo en local";
};

export const uso = (p) => (p.usadas_hoy == null ? "uso de hoy no disponible" : `${p.usadas_hoy} de ${p.limite_diario} consultas hoy`);

// Se puede conectar si tiene clave; desconectar se puede siempre
export const puedeCambiar = (p) => p.activo || p.tiene_clave;

export function mensajeError(estado, detalle) {
  if (estado === 403) return "Solo Dirección puede conectar o desconectar los modelos externos.";
  if (estado === 409) return detalle || "Falta la clave de este modelo.";
  if (estado === 422) return detalle || "Ese modelo no está entre los permitidos.";
  if (estado === 503) return "No se ha podido guardar el cambio. Inténtalo de nuevo en un momento.";
  return "No se ha podido cambiar el estado.";
}
