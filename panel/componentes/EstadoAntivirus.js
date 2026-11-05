"use client";
import { useCallback, useEffect, useState } from "react";
import { antivirusResumen } from "../lib/antivirus";

// La tarjeta «Antivirus»: si ClamAV responde y de cuándo son sus firmas. Con firmas de más de 48 horas, el sistema rechaza los pliegos y los documentos que se suben a Jarvis.
export default function EstadoAntivirus() {
  const [e, setE] = useState(null);
  const [abierto, setAbierto] = useState(false);
  const cargar = useCallback(() => fetch("/cerebro/salud/antivirus").then((r) => (r.ok ? r.json() : null)).then((d) => d && setE(d)).catch(() => {}), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 300000); return () => clearInterval(t); }, [cargar]);
  if (!e) return null;
  const r = antivirusResumen(e);
  const color = { bien: "#2e7d4f", aviso: "#c98a0b", mal: "#b3261e" }[r.nivel];
  return (
    <div className="jev">
      <button className="jev-chip" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>
        <i style={{ background: color }} aria-hidden="true" /> Antivirus: <b>{r.titulo}</b>
      </button>
      {abierto && (
        <div className="jev-panel" role="region" aria-label="Estado del antivirus">
          <ul>{r.lineas.map((l) => <li key={l}><div>{l}</div></li>)}</ul>
          <p className="meta">Los pliegos y los documentos que subes a Jarvis solo se aceptan si el antivirus los analiza con firmas de menos de {e.limite_horas} horas. Se avisa por correo a soporte@ si pasan {e.aviso_horas} horas sin firmas nuevas.</p>
          {r.ayuda && <p className="jev-ayuda"><code>{r.ayuda}</code></p>}
          <button className="of-boton" onClick={cargar}>Comprobar ahora</button>
        </div>
      )}
    </div>
  );
}
