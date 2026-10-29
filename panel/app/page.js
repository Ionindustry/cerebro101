"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { detectarIdioma, limpiarParaHablar, mensajeAudioBloqueado, mensajeErrorVoz, recortarParaHablar } from "../lib/voz";
import { ACCEPT, aBase64, estadoAdjuntoTexto, idsParaMensaje, mensajeSubida, textoConAdjuntos, validarAdjunto } from "../lib/adjuntos";
import { ayudaSinMicrofonos, elegir, mensajeError, mensajeTranscripcion, nivel, nombre, restricciones, soloEntradas } from "../lib/microfonos";

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
  const [adjuntos, setAdjuntos] = useState([]);         // documentos subidos para el próximo mensaje
  const [subiendo, setSubiendo] = useState(false);
  const [avisoAdjunto, setAvisoAdjunto] = useState("");
  const ficheroRef = useRef(null);
  const grabadora = useRef(null);
  const [micros, setMicros] = useState([]);       // micrófonos disponibles (el de una webcam USB, el del portátil…)
  const [micId, setMicId] = useState("");
  const [nivelMic, setNivelMic] = useState(0);
  const [avisoMic, setAvisoMic] = useState("");
  const [vozActiva, setVozActiva] = useState(true);       // Jarvis contesta en voz alta (también a lo escrito)
  const [hablando, setHablando] = useState(false);
  const audio = useRef(null);
  const [entorno, setEntorno] = useState(null);           // lo que el navegador permite; se lee tras pintar para no chocar con el servidor

  const detectar = useCallback(async () => {
    try {
      const lista = soloEntradas(await navigator.mediaDevices.enumerateDevices());
      setMicros(lista);
      let guardado = "";
      try { guardado = localStorage.getItem("jarvis_micro") || ""; } catch {}
      setMicId((actual) => elegir(lista, actual || guardado));
    } catch { /* sin acceso a los dispositivos: se usará el predeterminado */ }
  }, []);
  useEffect(() => {
    setEntorno({ seguro: Boolean(window.isSecureContext), api: Boolean(navigator.mediaDevices) });
    try { if (localStorage.getItem("jarvis_respuesta_voz") === "no") setVozActiva(false); } catch {}
  }, []);
  useEffect(() => {
    detectar();
    navigator.mediaDevices?.addEventListener?.("devicechange", detectar);      // al enchufar o quitar la webcam
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", detectar);
  }, [detectar]);

  async function pedirPermiso() {                      // el navegador solo enseña los micrófonos tras dar permiso una vez
    setAvisoMic("");
    try {
      const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      flujo.getTracks().forEach((t) => t.stop());
    } catch (e) {
      setAvisoMic(mensajeError(e));
    }
    detectar();
  }

  function cambiarMicro(id) {
    setMicId(id);
    setAvisoMic("");
    try { localStorage.setItem("jarvis_micro", id); } catch {}
  }

  async function adjuntar(ev) {
    const f = ev.target.files?.[0];
    ev.target.value = "";                                   // permite volver a elegir el mismo fichero
    if (!f) return;
    const motivo = validarAdjunto(f);
    if (motivo) { setAvisoAdjunto(motivo); return; }
    setAvisoAdjunto(""); setSubiendo(true);
    try {
      const r = await fetch("/cerebro/documentos/subir", { method: "POST", body: JSON.stringify({ nombre: f.name, base64: aBase64(await f.arrayBuffer()) }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw { status: r.status, detalle: typeof d.detail === "string" ? d.detail : "" };
      setAdjuntos((a) => [...a.filter((x) => x.id !== d.id), d].slice(-5));
      if (!d.disponible) setAvisoAdjunto(`«${d.nombre}»: ${estadoAdjuntoTexto(d)}`);
    } catch (e) {
      setAvisoAdjunto(mensajeSubida(e.status, e.detalle));
    } finally { setSubiendo(false); }
  }

  async function enviar(contenido, porVoz = false) {
    if (!contenido.trim()) return;
    const ids = idsParaMensaje(adjuntos);
    setMensajes((m) => [...m, { de: "persona", texto: textoConAdjuntos(contenido, adjuntos) }]);
    setAdjuntos([]); setAvisoAdjunto("");
    setTexto("");
    setEstado("pensando");
    try {
      const r = await fetch("/cerebro/jarvis/mensaje", {
        method: "POST",
        body: JSON.stringify({ texto: contenido, hilo, origen: "jarvis", ...(ids.length ? { documentos: ids } : {}) }),
      });
      const d = await r.json();
      if (!r.ok) {
        const err = new Error(d.detail || "El Cerebro no ha podido responder");
        err.amigable = Boolean(d.codigo);          // el modelo de IA no está disponible, va lento…: la API ya lo explica
        throw err;
      }
      setHilo(d.hilo);
      setMensajes((m) => [...m, { de: "jarvis", ...d }]);
      if (vozActiva && d.respuesta) hablar(d.respuesta);
    } catch (e) {
      const aviso = e.amigable ? e.message : `No he podido completar la petición: ${e.message}. Vuelve a intentarlo en un momento.`;
      setMensajes((m) => [...m, { de: "jarvis", respuesta: aviso }]);
    } finally {
      setEstado("listo");
    }
  }

  function pararAudio() {
    if (audio.current) { audio.current.pause(); audio.current = null; }
    setHablando(false);
  }

  function cambiarVoz() {
    const nuevo = !vozActiva;
    setVozActiva(nuevo);
    if (!nuevo) pararAudio();
    try { localStorage.setItem("jarvis_respuesta_voz", nuevo ? "si" : "no"); } catch {}
  }

  async function hablar(contenido) {
    const texto = recortarParaHablar(limpiarParaHablar(contenido));
    if (!texto) return;
    pararAudio();
    try {
      const r = await fetch("/voz/hablar", { method: "POST", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify({ texto, idioma: detectarIdioma(texto) }) });
      if (!r.ok) {
        const detalle = (await r.json().catch(() => ({}))).error;
        return setAvisoMic(mensajeErrorVoz(r.status, detalle));
      }
      const url = URL.createObjectURL(await r.blob());
      const a = new Audio(url);
      audio.current = a;
      a.onended = a.onpause = () => { setHablando(false); URL.revokeObjectURL(url); };
      setHablando(true);
      await a.play();
    } catch (e) {
      setHablando(false);
      setAvisoMic(e?.name === "NotAllowedError" ? mensajeAudioBloqueado : mensajeErrorVoz(0));
    }
  }

  async function alternarMicrofono() {
    if (estado === "escuchando") return grabadora.current?.stop();
    setAvisoMic("");
    pararAudio();                                        // si Jarvis está hablando y le hablas, se calla
    let flujo;
    try {
      try {
        flujo = await navigator.mediaDevices.getUserMedia(restricciones(micId));
      } catch (e) {
        if (e.name !== "OverconstrainedError" && e.name !== "NotFoundError") throw e;
        setMicId("");                                    // el micrófono guardado ya no está: se prueba con el predeterminado
        flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
        setAvisoMic("El micrófono elegido no está conectado: uso el predeterminado.");
      }
    } catch (e) {
      setAvisoMic(mensajeError(e));
      return;
    }
    detectar();                                          // con permiso concedido, el navegador ya da los nombres reales
    const rec = new MediaRecorder(flujo);
    const trozos = [];
    let medidor = null;
    try {                                                // barra de nivel: se ve si el micrófono recoge sonido
      const ctx = new AudioContext();
      const analizador = ctx.createAnalyser();
      ctx.createMediaStreamSource(flujo).connect(analizador);
      const muestras = new Uint8Array(analizador.fftSize);
      const t = setInterval(() => { analizador.getByteTimeDomainData(muestras); setNivelMic(nivel(muestras)); }, 100);
      medidor = () => { clearInterval(t); ctx.close(); setNivelMic(0); };
    } catch { /* sin medidor: se graba igual */ }
    rec.ondataavailable = (e) => trozos.push(e.data);
    rec.onstop = async () => {
      medidor?.();
      flujo.getTracks().forEach((t) => t.stop());
      setEstado("pensando");
      const fd = new FormData();
      fd.append("audio", new Blob(trozos, { type: "audio/webm" }), "voz.webm");
      let estadoHttp = 0, d = { texto: "" };
      try {
        const r = await fetch("/voz/transcribir", { method: "POST", body: fd });
        estadoHttp = r.status;
        if (r.ok) d = await r.json();
      } catch { /* sin llegar al servicio de voz */ }
      const aviso = mensajeTranscripcion(estadoHttp, d.texto || "");
      if (aviso) { setAvisoMic(aviso); setEstado("listo"); } else enviar(d.texto, true);
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
                  {a.aviso && <div className="aviso">{a.aviso}</div>}
                </div>
              ))}
            </div>
          )
        )}
      </div>
      <div className="barra">
        <div className="micro-selector">
          <label htmlFor="micro">Micrófono</label>
          {micros.length > 0 ? (
            <select id="micro" value={micId} onChange={(e) => cambiarMicro(e.target.value)} disabled={estado !== "listo"}>
              {micros.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{nombre(d, i)}</option>)}
            </select>
          ) : (
            <button type="button" className="of-boton" onClick={pedirPermiso} disabled={estado !== "listo"}>Detectar micrófonos</button>
          )}
          <button type="button" role="switch" aria-checked={vozActiva} className={`interruptor${vozActiva ? " on" : ""}`}
                  aria-label="Respuesta por voz" title="Respuesta por voz" onClick={cambiarVoz}><span /></button>
          <span className="voz-etiqueta">Respuesta por voz</span>
          {hablando && <button type="button" className="of-boton" onClick={pararAudio}>Callar</button>}
          {estado === "escuchando" && <span className="mic-nivel" role="meter" aria-label="Nivel del micrófono" aria-valuemin="0" aria-valuemax="1" aria-valuenow={nivelMic.toFixed(2)}><i style={{ width: `${Math.round(nivelMic * 100)}%` }} /></span>}
        </div>
        {micros.length === 0 && !avisoMic && entorno && <div className="micro-ayuda">{ayudaSinMicrofonos(entorno.seguro, entorno.api)}</div>}
        {avisoMic && <div className="micro-aviso" role="alert">{avisoMic}</div>}
        {(adjuntos.length > 0 || avisoAdjunto || subiendo) && (
          <div className="adjuntos" aria-live="polite">
            {adjuntos.map((a) => (
              <span key={a.id} className="adjunto" data-ok={a.disponible ? "si" : "no"}>
                📎 {a.nombre} <small>({estadoAdjuntoTexto(a)})</small>
                <button type="button" aria-label={`Quitar ${a.nombre}`} onClick={() => setAdjuntos((x) => x.filter((y) => y.id !== a.id))}>×</button>
              </span>
            ))}
            {subiendo && <span className="adjunto">Subiendo y analizando el documento…</span>}
            {adjuntos.length > 0 && !texto.trim() && <span className="micro-ayuda">Escribe qué quieres que haga con {adjuntos.length === 1 ? "el documento" : "los documentos"}.</span>}
            {avisoAdjunto && <span className="micro-aviso" role="alert">{avisoAdjunto}</span>}
          </div>
        )}
        <form className="compositor" onSubmit={(e) => { e.preventDefault(); enviar(texto); }}>
          <input ref={ficheroRef} type="file" accept={ACCEPT} onChange={adjuntar} hidden />
          <button type="button" className="clip" onClick={() => ficheroRef.current?.click()} disabled={estado === "pensando" || subiendo} aria-label="Adjuntar un documento (PDF, Word, Excel, CSV)" title="Adjuntar un documento">📎</button>
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
