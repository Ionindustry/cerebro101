"use client";
import { useCallback, useEffect, useState } from "react";

const COLORES = { operativo: "#2e7d4f", configurado: "#2e7d4f", caido: "#b3261e", sin_clave: "#c98a0b", desactivado: "#9a9aa2", no_desplegado: "#b3261e" };
const NOMBRES = { operativo: "Operativo", configurado: "Configurado (sin probar)", caido: "No responde", sin_clave: "Falta la clave", desactivado: "Desactivado", no_desplegado: "No arrancado" };
const VIAS = { jev: "Jev (nube)", jeff: "jeff (local)", local: "modelo local", ninguna: "ninguna" };

// Estado del motor de decisiones cerradas (Jev en la nube, jeff autoalojado y modelo local) y qué vía usará cada sensibilidad de datos
export default function EstadoJev() {
  const [e, setE] = useState(null);
  const [abierto, setAbierto] = useState(false);
  const [probando, setProbando] = useState(false);

  const cargar = useCallback((probar = false) => {
    if (probar) setProbando(true);
    return fetch(`/cerebro/salud/jev${probar ? "?probar=true" : ""}`).then((r) => (r.ok ? r.json() : null)).then((d) => d && setE(d)).catch(() => {})
      .finally(() => setProbando(false));
  }, []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 60000); return () => clearInterval(t); }, [cargar]);

  if (!e) return null;
  const color = ["operativo", "configurado"].includes(e.nube.estado) ? COLORES.operativo : e.operativo ? COLORES.sin_clave : COLORES.caido;
  return (
    <div className="jev">
      <button className="jev-chip" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>
        <i style={{ background: color }} aria-hidden="true" /> Decisiones (JEV): <b>{e.resumen}</b>
      </button>
      {abierto && (
        <div className="jev-panel" role="region" aria-label="Estado del motor de decisiones">
          <ul>
            {[["Jev en la nube", e.nube], ["jeff (autoalojado)", e.jeff], ["Modelo local", e.local]].map(([n, v]) => (
              <li key={n}>
                <i style={{ background: COLORES[v.estado] }} aria-hidden="true" />
                <div><b>{n}</b> · {NOMBRES[v.estado] || v.estado}<div className="meta">{v.detalle}{v.modelo ? ` · modelo ${v.modelo}` : ""}{v.segundos ? ` · ${v.segundos} s` : ""}</div></div>
              </li>
            ))}
          </ul>
          <p className="meta">Los agentes usarán: datos de sensibilidad baja → <b>{VIAS[e.se_usara.baja]}</b>, media → <b>{VIAS[e.se_usara.media]}</b>, alta → <b>{VIAS[e.se_usara.alta]}</b>. Si una vía falla, pasan solos a la siguiente.</p>
          {(e.nube.estado === "sin_clave" || e.nube.estado === "desactivado") && <p className="jev-ayuda">Para activar Jev en la nube: <code>python3 scripts/jev_activar.py</code></p>}
          {e.jeff.estado === "no_desplegado" && <p className="jev-ayuda">Para arrancar jeff: <code>docker compose up -d jeff</code></p>}
          <button className="of-boton" disabled={probando} onClick={() => cargar(true)}>{probando ? "Comprobando…" : "Comprobar ahora"}</button>
        </div>
      )}
    </div>
  );
}
