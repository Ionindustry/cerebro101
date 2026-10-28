"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { estadoEtiqueta, etiquetaEmbudo, fechaTexto, importeTexto, mensajeEmbudo, nombreFuente, urlSegura } from "../../../../lib/licitaciones";
import { Fallo, pedir, pedirCerebro } from "../../cliente";

const Dato = ({ t, children }) => <div><dt>{t}</dt><dd>{children ?? "—"}</dd></div>;
const Enlace = ({ url, children }) => {
  const u = urlSegura(url);
  return u ? <a href={u} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
};

// «Estudiar»: pasa el expediente al embudo de 101.cat. Solo lo ven Dirección y Licitaciones (para los demás la consulta da 403 y la tarjeta no aparece).
function Estudiar({ id }) {
  const [fila, setFila] = useState(undefined);        // undefined = consultando; null = no está en el embudo
  const [permitido, setPermitido] = useState(true);
  const [trabajando, setTrabajando] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    pedirCerebro(`licitaciones/embudo?motor_id=${encodeURIComponent(id)}`).then((l) => setFila(l.items[0] || null)).catch(() => setPermitido(false));
  }, [id]);
  if (!permitido || fila === undefined) return null;
  const estudiar = async () => {
    setTrabajando(true); setError(null);
    try { setFila(await pedirCerebro("licitaciones/embudo/estudiar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motor_id: id }) })); }
    catch (e) { setError(e); }
    finally { setTrabajando(false); }
  };
  return (
    <section className="tarjeta" aria-label="Embudo">
      <h2>Embudo de 101.cat</h2>
      {fila ? (
        <p>Estado: <span className="lic-etiqueta">{etiquetaEmbudo(fila.estado)}</span> · <Link href="/licitaciones/embudo">Ver el embudo</Link></p>
      ) : (
        <>
          <p className="meta">Si te interesa, pásala a estudio: se anota en el embudo y Viabilidad podrá valorarla. No se presenta nada por ti.</p>
          <button className="boton si" onClick={estudiar} disabled={trabajando}>{trabajando ? "Anotando…" : "Estudiar"}</button>
        </>
      )}
      {error && <p role="alert" className="lic-error">{mensajeEmbudo(error.status)}</p>}
    </section>
  );
}

export default function Ficha() {
  const { id } = useParams();
  const [x, setX] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { pedir(`tenders/${encodeURIComponent(id)}`).then(setX).catch(setError); }, [id]);

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones/buscar">← Buscar licitaciones</Link></p>
      {error && <Fallo e={error} />}
      {!x && !error && <p className="meta" aria-busy="true">Cargando…</p>}
      {x && (
        <>
          <h1>{x.titulo || "(sin título)"}</h1>
          <Estudiar id={id} />
          <section className="tarjeta" aria-label="Resumen">
            <dl className="lic-ficha">
              <Dato t="Estado"><span className={`lic-etiqueta ${x.estado}`}>{estadoEtiqueta(x.estado)}</span>{x.estado_origen ? ` (en origen: ${x.estado_origen})` : ""}</Dato>
              <Dato t="Expediente">{x.expediente}</Dato>
              <Dato t="Comprador">{x.comprador?.nombre}{x.comprador?.nif ? ` · ${x.comprador.nif}` : ""}</Dato>
              <Dato t="Procedimiento">{x.procedimiento?.replace(/_/g, " ")}</Dato>
              <Dato t="Plazo de presentación">{x.plazos?.presentacion ? fechaTexto(x.plazos.presentacion) : null}</Dato>
              <Dato t="Última actualización">{fechaTexto(x.actualizada_en)}</Dato>
              <Dato t="CPV">{x.cpv?.join(", ")}</Dato>
              <Dato t="Zona (NUTS)">{x.nuts?.join(", ")}</Dato>
              <Dato t="Fuente">{(x.fuentes || []).map(nombreFuente).join(", ")}</Dato>
              <Dato t="Original">{x.url_origen ? <Enlace url={x.url_origen}>Ver en la plataforma</Enlace> : null}</Dato>
            </dl>
          </section>

          {x.importes?.length > 0 && (
            <section className="tarjeta" aria-label="Importes">
              <h2>Importes</h2>
              <ul>{x.importes.map((i, n) => <li key={n}>{importeTexto(i, true)}</li>)}</ul>
            </section>
          )}

          {x.lotes?.length > 0 && (
            <section className="tarjeta" aria-label="Lotes">
              <h2>Lotes</h2>
              <table className="lic-tabla">
                <thead><tr><th>Lote</th><th>Objeto</th><th>Importes</th></tr></thead>
                <tbody>{x.lotes.map((l) => (
                  <tr key={l.numero}><td>{l.numero}</td><td>{l.objeto || "—"}</td><td>{(l.importes || []).map((i) => importeTexto(i, true)).join(" · ") || "—"}</td></tr>
                ))}</tbody>
              </table>
            </section>
          )}

          {x.criterios?.length > 0 && (
            <section className="tarjeta" aria-label="Criterios de adjudicación">
              <h2>Criterios de adjudicación</h2>
              <ul>{x.criterios.map((c, n) => <li key={n}>{c.descripcion || "—"}{c.peso != null ? ` · ${c.peso} puntos` : ""} <span className="meta">({String(c.tipo).replace(/_/g, " ")})</span></li>)}</ul>
            </section>
          )}

          {x.adjudicaciones?.length > 0 && (
            <section className="tarjeta" aria-label="Adjudicaciones">
              <h2>Adjudicaciones</h2>
              <table className="lic-tabla">
                <thead><tr><th>Lote</th><th>Resultado</th><th>Adjudicatario</th><th>Importe</th><th>Baja</th><th>Ofertas</th></tr></thead>
                <tbody>{x.adjudicaciones.map((a) => (
                  <tr key={a.id}>
                    <td>{a.lote}</td><td>{a.resultado}</td>
                    <td>{a.adjudicatario?.nombre || "—"}{a.adjudicatario?.nif ? <span className="meta"> · {a.adjudicatario.nif}</span> : null}</td>
                    <td>{(a.importes || []).filter((i) => i.significado === "adjudicado").map((i) => importeTexto(i)).join(" · ") || "—"}</td>
                    <td>{typeof a.baja === "number" ? `${(a.baja * 100).toFixed(1).replace(".", ",")} %` : "—"}</td>
                    <td>{a.ofertas_recibidas ?? "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </section>
          )}

          {x.documentos?.length > 0 && (
            <section className="tarjeta" aria-label="Documentos">
              <h2>Documentos</h2>
              <ul>{x.documentos.map((d, n) => <li key={n}><Enlace url={d.url_origen}>{d.nombre || d.url_origen}</Enlace> <span className="meta">{String(d.tipo || "").replace(/_/g, " ")}</span></li>)}</ul>
            </section>
          )}

          {x.evidencia && (
            <section className="tarjeta" aria-label="Evidencia">
              <h2>Evidencia</h2>
              <p className="meta">El original de esta ficha está guardado sin modificar. Su huella SHA-256 permite comprobar que no ha cambiado.</p>
              <dl className="lic-ficha">
                <Dato t="Fuente">{nombreFuente(x.evidencia.fuente)}</Dato>
                <Dato t="Visto por última vez">{fechaTexto(x.evidencia.capturado_en)}</Dato>
                <Dato t="Huella SHA-256"><code>{x.evidencia.sha256}</code></Dato>
                <Dato t="Versión de la ficha">{x.version_entidad}</Dato>
              </dl>
            </section>
          )}
        </>
      )}
    </div>
  );
}
