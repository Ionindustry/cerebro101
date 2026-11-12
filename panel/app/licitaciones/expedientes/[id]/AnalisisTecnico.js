"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { citasTexto, estadoAnalisisTecnico, fechaTexto, lugarDeCita, mensajeAnalisisTecnico, preguntasParaCopiar, tipoCriterioEtiqueta, tipoDebilEtiqueta } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

function Cita({ x }) {
  const lugar = lugarDeCita(x);
  if (!x.cita && !lugar) return null;
  return (
    <blockquote className="meta">
      {x.cita && <>«{x.cita}»</>} {lugar && <span>({lugar})</span>}{" "}
      <span className={`lic-etiqueta ${x.cita_verificada ? "ok" : "aviso"}`}>{x.cita_verificada ? "Cita comprobada" : "Cita sin comprobar: mírala en el pliego"}</span>
    </blockquote>
  );
}

/** Análisis técnico del pliego con Claude o ChatGPT: criterios de puntuación, puntos fuertes y débiles (cada uno con su cita comprobada) y preguntas para el órgano de contratación. Es ayuda para decidir: no decide nada. */
export default function AnalisisTecnico({ id }) {
  const [d, setD] = useState(undefined);        // undefined = consultando; null = sin acceso
  const [error, setError] = useState(null);
  const [pidiendo, setPidiendo] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const cargar = useCallback(async () => {
    try { setD(await pedirCerebro(`licitaciones/analisis-tecnico/${encodeURIComponent(id)}`)); }
    catch (e) { if (e.status === 403 || e.status === 401) setD(null); else { setError(e); setD((x) => (x === undefined ? null : x)); } }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar]);
  const enCurso = d?.analisis?.estado === "en_curso";
  useEffect(() => {
    if (!enCurso) return undefined;
    const t = setInterval(cargar, 5000);               // mientras trabaja el modelo, se mira cada 5 s
    return () => clearInterval(t);
  }, [enCurso, cargar]);
  if (d === undefined || (d === null && !error)) return null;
  const a = d?.analisis, inf = a?.informe;
  const estado = estadoAnalisisTecnico(a);
  const pedir = async () => {
    setPidiendo(true); setError(null);
    try { await pedirCerebro(`licitaciones/analisis-tecnico/${encodeURIComponent(id)}`, { method: "POST" }); await cargar(); }
    catch (e) { setError(e); }
    finally { setPidiendo(false); }
  };
  const copiar = async () => {
    try { await navigator.clipboard.writeText(preguntasParaCopiar(inf)); setCopiado(true); setTimeout(() => setCopiado(false), 2500); } catch { setError({ status: 0 }); }
  };
  const preguntas = inf ? preguntasParaCopiar(inf) : "";
  return (
    <section className="tarjeta" aria-label="Análisis técnico del pliego">
      <header>
        <h2>Análisis técnico del pliego</h2>
        <span className={`lic-etiqueta ${estado.clase}`}>{estado.texto}</span>
      </header>
      <p className="meta">Claude o ChatGPT leen el texto de los pliegos y señalan qué es claro y favorable, qué es ambiguo o arriesgado y cómo se puntúa lo técnico. Solo sale a la nube el texto del pliego (documentación pública), nunca datos de la empresa. Cada hallazgo lleva su cita y se comprueba contra el texto leído. Es una ayuda: lo revisa una persona.</p>
      {error && <p role="alert" className="lic-error">{error.status ? mensajeAnalisisTecnico(error.status) : "No se ha podido copiar."}</p>}
      {d && !d.modelo_listo && <p role="status" className="lic-aviso">No hay ningún modelo externo conectado. Dirección lo hace en <Link href="/agentes">Agentes → Modelos externos</Link> (necesita la clave de Claude o de ChatGPT).</p>}
      <p className="lic-fila">
        <button className="boton si" onClick={pedir} disabled={pidiendo || enCurso || !d?.modelo_listo}>{enCurso ? "Analizando…" : a ? "Repetir el análisis" : "Analizar el pliego"}</button>
        {a?.proveedor && a.estado === "hecho" && <span className="meta">Con {a.proveedor === "claude" ? "Claude" : "ChatGPT"} ({a.modelo}) · {fechaTexto(a.actualizado)}</span>}
      </p>
      {enCurso && <p className="meta" aria-busy="true">El modelo está leyendo el pliego: suele tardar uno o dos minutos. Esta tarjeta se actualiza sola.</p>}
      {a?.estado === "error" && <p role="alert" className="lic-error">{a.error}</p>}
      {inf && a.estado === "hecho" && (
        <>
          {inf.avisos?.map((x) => <p key={x} role="status" className="lic-aviso">{x}</p>)}
          <p className="meta">{citasTexto(inf.citas)}. Documentos leídos: {(a.documentos || []).map((x) => `${x.n} (${x.paginas} págs.)`).join(", ") || "—"}.</p>
          {inf.resumen && <p>{inf.resumen}</p>}

          {inf.criterios_tecnicos?.length > 0 && (
            <>
              <h3>Cómo se puntúa lo técnico</h3>
              <ul className="lic-lista">
                {inf.criterios_tecnicos.map((c, i) => (
                  <li key={i} className="tarjeta lic-item">
                    <span className="lic-fila"><span className="titulo">{c.criterio}</span>{c.peso && <span className="lic-etiqueta">{c.peso}</span>}<span className="meta">{tipoCriterioEtiqueta(c.tipo)}</span></span>
                    {c.como_se_puntua && <span className="meta">{c.como_se_puntua}</span>}
                    <Cita x={c} />
                  </li>
                ))}
              </ul>
            </>
          )}

          <h3>Puntos fuertes del pliego</h3>
          {inf.puntos_fuertes?.length ? (
            <ul className="lic-lista">
              {inf.puntos_fuertes.map((p, i) => (
                <li key={i} className="tarjeta lic-item"><span className="titulo">{p.punto}</span><span>{p.detalle}</span><Cita x={p} /></li>
              ))}
            </ul>
          ) : <p className="meta">No se ha señalado ninguno.</p>}

          <h3>Puntos débiles del pliego</h3>
          {inf.puntos_debiles?.length ? (
            <ul className="lic-lista">
              {inf.puntos_debiles.map((p, i) => (
                <li key={i} className="tarjeta lic-item">
                  <span className="lic-fila"><span className="titulo">{p.punto}</span><span className="lic-etiqueta aviso">{tipoDebilEtiqueta(p.tipo)}</span></span>
                  <span>{p.detalle}</span>
                  <Cita x={p} />
                  {p.pregunta_aclaracion && <span className="meta">Qué preguntar: {p.pregunta_aclaracion}</span>}
                </li>
              ))}
            </ul>
          ) : <p className="meta">No se ha señalado ninguno.</p>}

          {preguntas && (
            <>
              <h3>Preguntas para el órgano de contratación</h3>
              <pre className="meta" style={{ whiteSpace: "pre-wrap" }}>{preguntas}</pre>
              <button className="boton no" onClick={copiar}>{copiado ? "Copiado" : "Copiar las preguntas"}</button>
            </>
          )}
        </>
      )}
    </section>
  );
}
