"use client";
import { useCallback, useEffect, useState } from "react";
import { autorDocumentoTexto, claseDocumento, fechaTexto, mensajeDocumentos, plantillaEtiqueta, tamanoDocumentoTexto } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

function guardar(f) {
  const bytes = Uint8Array.from(atob(f.base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: f.tipo }));
  const a = document.createElement("a"); a.href = url; a.download = f.nombre; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}

/** Todo lo que han redactado los agentes de esta licitación en un solo sitio: se lee en pantalla y se baja en Word. Los documentos son borradores de agentes; nada de aquí se presenta ni se envía. */
export default function DocumentosAgentes({ id }) {
  const base = `licitaciones/ofertas/${id}/documentos-agentes`;
  const [d, setD] = useState(undefined);
  const [abierto, setAbierto] = useState(null);       // { id, texto }
  const [msg, setMsg] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(async () => {
    try { setD(await pedirCerebro(base)); setMsg(null); }
    catch (e) { setD(null); setMsg(mensajeDocumentos(e.status, e.detalle)); }
  }, [base]);
  useEffect(() => { cargar(); }, [cargar]);

  const ver = async (doc) => {
    if (abierto?.id === doc.id) { setAbierto(null); return; }
    setOcupado(true); setMsg(null);
    try { const r = await pedirCerebro(`${base}/${doc.id}`); setAbierto({ id: doc.id, texto: r.texto }); }
    catch (e) { setMsg(mensajeDocumentos(e.status, e.detalle)); } finally { setOcupado(false); }
  };
  const word = async (doc) => {
    setOcupado(true); setMsg(null);
    try { guardar(await pedirCerebro(`${base}/${doc.id}/word`)); } catch (e) { setMsg(mensajeDocumentos(e.status, e.detalle)); } finally { setOcupado(false); }
  };
  const plantilla = async (p) => {
    setOcupado(true); setMsg(null);
    try { guardar(await pedirCerebro(`licitaciones/ofertas/${id}/plantillas/${p.id}/fichero`)); } catch (e) { setMsg(mensajeDocumentos(e.status, e.detalle)); } finally { setOcupado(false); }
  };

  if (d === undefined) return null;
  const hay = d && (d.documentos.length > 0 || d.plantillas.length > 0);
  return (
    <section className="tarjeta" aria-label="Documentos de los agentes">
      <h2>Documentos de los agentes</h2>
      <p className="meta">Lo que han redactado los agentes en esta licitación, reunido aquí para leerlo y bajarlo en Word. Son <strong>borradores</strong>: los revisa una persona antes de usarlos.</p>
      {msg && <p role="alert" className="lic-error">{msg}</p>}
      {d && !hay && <p className="meta">Aún no hay documentos: aparecerán cuando los agentes redacten (botón «Preparar la oferta»).</p>}
      {d?.documentos.length > 0 && (
        <ul>
          {d.documentos.map((doc) => (
            <li key={doc.id}>
              <strong>{doc.titulo}</strong> <span className={`lic-etiqueta ${claseDocumento(doc.estado)}`}>{doc.estado_texto}</span>
              <span className="meta"> · {autorDocumentoTexto(doc.por)} · {tamanoDocumentoTexto(doc.caracteres)}{doc.actualizado ? ` · ${fechaTexto(doc.actualizado)}` : ""}</span>
              <div className="lic-fila">
                <button className="boton no" disabled={ocupado} onClick={() => ver(doc)}>{abierto?.id === doc.id ? "Ocultar" : "Leer"}</button>
                <button className="boton si" disabled={ocupado} onClick={() => word(doc)}>Descargar Word</button>
              </div>
              {abierto?.id === doc.id && <pre className="lic-documento" style={{ whiteSpace: "pre-wrap" }}>{abierto.texto}</pre>}
            </li>
          ))}
        </ul>
      )}
      {d?.plantillas.length > 0 && (
        <>
          <h3>Documentación administrativa rellenada</h3>
          <ul>
            {d.plantillas.map((p) => (
              <li key={p.id}>{p.nombre} <span className="meta">· {plantillaEtiqueta(p.estado)}{p.pendientes ? ` · ${p.pendientes} datos por completar` : ""}</span>
                {" "}<button className="boton no" disabled={ocupado} onClick={() => plantilla(p)}>Descargar</button></li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
