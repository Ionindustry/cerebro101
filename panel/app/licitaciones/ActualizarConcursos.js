"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { INTERVALO_ACTUALIZACION_MS, MAX_ESPERA_ACTUALIZACION_MS, huboIngestaNueva, textoActualizacionManual } from "../../lib/licitaciones";
import { mensajeDeError } from "../../lib/licitaciones";
import { pedirCerebro } from "./cliente";

/** El botón manual de las licitaciones: pide al ingestor que empiece una vuelta YA (sin esperar a sus 15 minutos) y sigue el progreso hasta que termina una ingesta nueva. */
export default function ActualizarConcursos({ alTerminar }) {
  const [p, setP] = useState(null);                   // última lectura del progreso
  const [esperando, setEsperando] = useState(false);
  const [terminado, setTerminado] = useState(false);
  const [error, setError] = useState(null);
  const reloj = useRef(null);

  const leer = useCallback(async () => { try { const d = await pedirCerebro("licitaciones/motor/actualizacion"); setP(d); return d; } catch { return null; } }, []);
  useEffect(() => { leer(); return () => clearTimeout(reloj.current); }, [leer]);

  const seguir = useCallback((anterior, desde) => {
    reloj.current = setTimeout(async () => {
      const d = await leer();
      if (d && huboIngestaNueva(anterior, d.mas_reciente_s)) { setEsperando(false); setTerminado(true); if (alTerminar) alTerminar(); return; }
      if (Date.now() - desde > MAX_ESPERA_ACTUALIZACION_MS) { setEsperando(false); setError("Sigue sin llegar lo nuevo: el ingestor puede estar ocupado. Vuelve a mirar en unos minutos."); return; }
      seguir(d ? d.mas_reciente_s : anterior, desde);
    }, INTERVALO_ACTUALIZACION_MS);
  }, [leer, alTerminar]);

  const pedir = async () => {
    setError(null); setTerminado(false); clearTimeout(reloj.current);
    try {
      const r = await pedirCerebro("licitaciones/motor/actualizar", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (r.estado !== "actualizando") { setError(r.mensaje || "No se ha podido pedir la actualización."); return; }
      setEsperando(true);
      seguir(r.mas_reciente_s, Date.now());
    } catch (e) { setError(e?.status === 403 ? "Solo Dirección y el departamento de Licitaciones pueden actualizar los concursos a mano." : mensajeDeError(e?.status, e?.detalle)); }
  };

  const t = textoActualizacionManual({ esperando, terminado, error, p });
  return (
    <section className="lic-fila" aria-label="Actualizar concursos">
      <button className="boton si" onClick={pedir} disabled={esperando}>{esperando ? "Actualizando…" : "Actualizar concursos ahora"}</button>
      {t.texto && <span role={t.clase === "error" ? "alert" : "status"} className={t.clase === "error" ? "lic-error" : t.clase === "aviso" ? "aviso" : "meta"}>{t.texto}</span>}
    </section>
  );
}
