"use client";
import { useCallback, useEffect, useState } from "react";
import { copiasResumen } from "../lib/copias";

// La tarjeta «Copias de seguridad»: última copia (fecha, tamaño, si salió bien), si la restauración se ha probado y si hay que preocuparse (más de 3 días sin una buena).
// Los datos los anota el servidor al hacer la copia (scripts/copia_automatica.sh); aquí solo se leen.
export default function EstadoCopias() {
  const [e, setE] = useState(null);
  const [abierto, setAbierto] = useState(false);
  const cargar = useCallback(() => fetch("/cerebro/salud/copias").then((r) => (r.ok ? r.json() : null)).then((d) => d && setE(d)).catch(() => {}), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 300000); return () => clearInterval(t); }, [cargar]);
  if (!e) return null;
  const r = copiasResumen(e);
  const color = { bien: "#2e7d4f", aviso: "#c98a0b", mal: "#b3261e" }[r.nivel];
  return (
    <div className="jev">
      <button className="jev-chip" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>
        <i style={{ background: color }} aria-hidden="true" /> Copias de seguridad: <b>{r.titulo}</b>
      </button>
      {abierto && (
        <div className="jev-panel" role="region" aria-label="Estado de las copias de seguridad">
          <ul>{r.lineas.map((l) => <li key={l}><div>{l}</div></li>)}</ul>
          <p className="meta">Las hace el servidor cada día a las 14:00 (tarea de Windows «Cerebro - copia») y se conservan las 7 últimas. Si pasan más de {e.dias_limite} días sin una correcta, se avisa por correo a soporte@.</p>
          {r.ayuda && <p className="jev-ayuda">{r.ayuda}</p>}
        </div>
      )}
    </div>
  );
}
