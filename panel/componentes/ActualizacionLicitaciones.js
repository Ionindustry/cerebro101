"use client";
import { useEffect, useState } from "react";
import { avisoActualizacion } from "../lib/licitaciones";

// Al abrir la aplicación se comprueba si las licitaciones están al día; si no, se pide al motor que actualice YA y se enseña un aviso que se quita solo cuando lo está.
// Es una comodidad: si la comprobación falla (sin sesión, red…), no se dice nada. Se repite al volver a abrir la aplicación, no a cada cambio de pantalla.
const CADA_MS = 20000;      // mientras se actualiza, se vuelve a mirar cada 20 s
const INTENTOS = 15;        // hasta 5 minutos

async function comprobar() {
  try {
    const r = await fetch("/cerebro/licitaciones/motor/comprobar", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", cache: "no-store" });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export default function ActualizacionLicitaciones() {
  const [aviso, setAviso] = useState(null);
  useEffect(() => {
    let vivo = true;
    let timer = null;
    let tras = 0;
    let actualizando = false;
    const vuelta = async () => {
      const d = await comprobar();
      if (!vivo) return;
      const a = avisoActualizacion(d);
      if (a) {
        actualizando = d.estado === "actualizando";
        setAviso(a);
        if (++tras < INTENTOS) timer = setTimeout(vuelta, CADA_MS);
        return;
      }
      if (actualizando && d?.estado === "al_dia") {                 // acaba de terminar de actualizar
        setAviso({ clase: "ok", texto: "Licitaciones al día." });
        timer = setTimeout(() => vivo && setAviso(null), 6000);
        return;
      }
      setAviso(null);
    };
    vuelta();
    return () => { vivo = false; clearTimeout(timer); };
  }, []);
  if (!aviso) return null;
  return <div role="status" className={`aviso-actualizacion ${aviso.clase}`}>{aviso.texto}</div>;
}
