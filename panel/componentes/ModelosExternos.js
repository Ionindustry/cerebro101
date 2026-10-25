"use client";
import { useCallback, useEffect, useState } from "react";
import { ESTADOS, mensajeError, puedeCambiar, resumen, uso } from "../lib/modelosExternos";

// Interruptores de Claude y ChatGPT: los agentes les pasan las consultas más complejas (datos anonimizados) solo mientras están conectados
export default function ModelosExternos() {
  const [d, setD] = useState(null);
  const [abierto, setAbierto] = useState(false);
  const [ocupado, setOcupado] = useState(null);
  const [aviso, setAviso] = useState("");

  const cargar = useCallback((probar) =>
    fetch(`/cerebro/modelos-externos${probar ? `?probar=${probar}` : ""}`)
      .then((r) => (r.ok ? r.json() : null)).then((x) => x && setD(x)).catch(() => {}), []);
  useEffect(() => { cargar(); }, [cargar]);

  async function cambiar(p) {
    setOcupado(p.id); setAviso("");
    try {
      const r = await fetch(`/cerebro/modelos-externos/${p.id}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ activo: !p.activo }),
      });
      if (r.ok) setD(await r.json());
      else setAviso(mensajeError(r.status, (await r.json().catch(() => ({}))).detail));
    } catch { setAviso(mensajeError(0)); }
    setOcupado(null);
  }

  async function probar(p) {
    setOcupado(p.id); setAviso("");
    await cargar(p.id);
    setOcupado(null);
  }

  if (!d) return null;
  return (
    <div className="jev">
      <button className="jev-chip" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>
        <i style={{ background: d.proveedores.some((p) => p.estado === "conectado") ? "#2e7d4f" : "#9a9aa2" }} aria-hidden="true" />
        Modelos externos (Claude · ChatGPT): <b>{resumen(d.proveedores)}</b>
      </button>
      {abierto && (
        <div className="jev-panel" role="region" aria-label="Modelos externos para consultas complejas">
          <p className="meta">Cuando un agente recibe una consulta compleja, se la pasa a un modelo externo <b>solo si está conectado</b>. Lo que sale va anonimizado
            (nombres, correos, IBAN, etc. se sustituyen y se restauran al volver) y los agentes de sensibilidad {d.sensibilidad_maxima === "media" ? "alta" : "superior"} nunca los usan.
            Si no se puede garantizar, la consulta se queda en el modelo local.</p>
          <ul>
            {d.proveedores.map((p) => (
              <li key={p.id} className="mx-fila">
                <i style={{ background: ESTADOS[p.estado].color }} aria-hidden="true" />
                <div className="mx-texto">
                  <b>{p.nombre}</b> · {ESTADOS[p.estado].texto}
                  <div className="meta">Modelo {p.modelo}{p.tiene_clave ? ` · ${uso(p)}` : ""}</div>
                  {p.prueba && <div className="meta" role="status">{p.prueba.ok ? `✓ ${p.prueba.detalle} (${p.prueba.segundos} s)` : `✗ ${p.prueba.detalle}`}</div>}
                  {!p.tiene_clave && <div className="jev-ayuda">Para poner la clave: <code>python3 scripts/modelos_activar.py {p.id}</code></div>}
                </div>
                <div className="mx-acciones">
                  {p.tiene_clave && <button className="of-boton" disabled={ocupado === p.id} onClick={() => probar(p)}>Probar</button>}
                  <button role="switch" aria-checked={p.activo} aria-label={`${p.activo ? "Desconectar" : "Conectar"} ${p.nombre}`}
                    className={`interruptor${p.activo ? " on" : ""}`} disabled={ocupado === p.id || !puedeCambiar(p)} onClick={() => cambiar(p)}>
                    <span />
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {aviso && <p className="mx-aviso" role="alert">{aviso}</p>}
        </div>
      )}
    </div>
  );
}
