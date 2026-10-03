"use client";
import { useRef, useState } from "react";

const SUGERENCIAS = [
  "¿Hay concursos nuevos que nos interesen?",
  "Prepara un presupuesto de CCTV para un comercio con 4 cámaras exteriores",
  "¿Qué tendencias nuevas hay en contra incendios?",
  "Resumen del día",
];

export default function Jarvis() {
  const [mensajes, setMensajes] = useState([]);
  const [texto, setTexto] = useState("");
  const [estado, setEstado] = useState("listo"); // listo | escuchando | pensando
  const [hilo, setHilo] = useState(null);
  const grabadora = useRef(null);

  async function enviar(contenido, porVoz = false) {
    if (!contenido.trim()) return;
    setMensajes((m) => [...m, { de: "persona", texto: contenido }]);
    setTexto("");
    setEstado("pensando");
    try {
      const r = await fetch("/cerebro/jarvis/mensaje", {
        method: "POST",
        body: JSON.stringify({ texto: contenido, hilo, origen: "jarvis" }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "El Cerebro no ha podido responder");
      setHilo(d.hilo);
      setMensajes((m) => [...m, { de: "jarvis", ...d }]);
      if (porVoz && d.respuesta) hablar(d.respuesta);
    } catch (e) {
      setMensajes((m) => [...m, { de: "jarvis", respuesta: `No he podido completar la petición: ${e.message}. Vuelve a intentarlo en un momento.` }]);
    } finally {
      setEstado("listo");
    }
  }

  async function hablar(contenido) {
    const r = await fetch("/voz/hablar", { method: "POST", body: JSON.stringify({ texto: contenido, idioma: "es" }) });
    if (r.ok) new Audio(URL.createObjectURL(await r.blob())).play();
  }

  async function alternarMicrofono() {
    if (estado === "escuchando") return grabadora.current?.stop();
    const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
    const rec = new MediaRecorder(flujo);
    const trozos = [];
    rec.ondataavailable = (e) => trozos.push(e.data);
    rec.onstop = async () => {
      flujo.getTracks().forEach((t) => t.stop());
      setEstado("pensando");
      const fd = new FormData();
      fd.append("audio", new Blob(trozos, { type: "audio/webm" }), "voz.webm");
      const r = await fetch("/voz/transcribir", { method: "POST", body: fd });
      const d = r.ok ? await r.json() : { texto: "" };
      d.texto ? enviar(d.texto, true) : setEstado("listo");
    };
    grabadora.current = rec;
    rec.start();
    setEstado("escuchando");
  }

  return (
    <>
      <div className="hilo" aria-live="polite">
        {mensajes.length === 0 && (
          <div className="vacio">
            <p>¿En qué te ayudo hoy?</p>
            <div className="sugerencias">
              {SUGERENCIAS.map((s) => <button key={s} onClick={() => enviar(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {mensajes.map((m, i) =>
          m.de === "persona" ? (
            <div key={i} className="burbuja persona">{m.texto}</div>
          ) : (
            <div key={i} className="burbuja jarvis">
              {m.agente && <div className="ruta">Responde {m.agente}, de {m.departamento}</div>}
              {m.respuesta}
              {(m.acciones || []).map((a, j) => (
                <div key={j} className={`accion ${a.estado}`}>
                  {a.estado === "pendiente" ? "Espera tu aprobación: " : a.estado === "ejecutada" ? "Hecho: " : ""}
                  {a.resumen}
                </div>
              ))}
            </div>
          )
        )}
      </div>
      <div className="barra">
        <form className="compositor" onSubmit={(e) => { e.preventDefault(); enviar(texto); }}>
          <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Escribe o habla con Jarvis"
                 aria-label="Mensaje para Jarvis" disabled={estado === "pensando"} />
          {texto && <button className="enviar" type="submit">Enviar</button>}
          <button type="button" className="microfono" data-estado={estado} onClick={alternarMicrofono}
                  aria-label={estado === "escuchando" ? "Dejar de escuchar" : "Hablar con Jarvis"} disabled={estado === "pensando"}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
            </svg>
          </button>
        </form>
      </div>
    </>
  );
}
