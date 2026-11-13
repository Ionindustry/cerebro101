"use client";
import { useCallback, useEffect, useState } from "react";
import { fechaTexto } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

/** Más opciones de internet para los parámetros sin cubrir. Son PISTAS por verificar, no evidencia: solo cuentan cuando se carga la ficha técnica del fabricante (de un dominio autorizado). */
export default function Descubrimiento({ id }) {
  const [d, setD] = useState(undefined);
  const [error, setError] = useState(null);
  const [aviso, setAviso] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const cargar = useCallback(async () => {
    try { setD((await pedirCerebro(`licitaciones/ofertas/${encodeURIComponent(id)}/descubrimiento`)).descubrimiento); }
    catch { setD((x) => (x === undefined ? null : x)); }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => {
    if (d?.estado !== "en_curso") return undefined;
    const t = setInterval(cargar, 6000);
    return () => clearInterval(t);
  }, [d, cargar]);
  if (d === undefined) return null;

  const buscar = async () => {
    setTrabajando(true); setError(null); setAviso(null);
    try { await pedirCerebro(`licitaciones/ofertas/${encodeURIComponent(id)}/descubrimiento`, enviar({})); await cargar(); }
    catch (e) { setError(e); } finally { setTrabajando(false); }
  };
  const cargarFicha = async (p) => {
    setTrabajando(true); setError(null); setAviso(null);
    try { const r = await pedirCerebro("licitaciones/fichas/url", enviar({ url: p.url, marca: p.marca, referencia: p.referencia })); setAviso(`${p.producto}: ${r.estado === "indexada" ? "ficha cargada; repite la tabla de equivalencias para que la use" : `${r.estado}${r.motivo ? ` (${r.motivo})` : ""}`}`); }
    catch (e) { setError(e); } finally { setTrabajando(false); }
  };

  const c = d?.contenido;
  return (
    <div>
      <h4>Más opciones en internet</h4>
      <p className="meta">Busca productos que podrían cubrir lo que aún no tiene producto acreditado. Son pistas por verificar: no valen como evidencia hasta cargar la ficha técnica del fabricante.</p>
      <button className="boton no" disabled={trabajando || d?.estado === "en_curso"} onClick={buscar}>{d?.estado === "en_curso" ? "Buscando…" : d ? "Repetir la búsqueda" : "Buscar más opciones en internet"}</button>
      {error && <p className="aviso" role="alert">{error.detalle || "No se ha podido hacer."}</p>}
      {aviso && <p className="aviso" role="status">{aviso}</p>}
      {d?.estado === "error" && <p className="aviso" role="alert">{d.error}</p>}
      {d?.estado === "hecha" && c && (
        <>
          <p className="meta">Búsqueda del {fechaTexto(d.actualizado)}{d.proveedor ? ` con ${d.proveedor === "claude" ? "Claude" : "ChatGPT"}` : ""}. {c.aviso || `${c.comprobacion?.pistas || 0} pistas`}</p>
          <ul className="lic-lista">
            {c.pistas.map((p, i) => (
              <li key={i} className="tarjeta lic-item">
                <span className="lic-fila"><span className="titulo">{[p.marca, p.producto, p.referencia].filter(Boolean).join(" ")}</span><span className="lic-etiqueta">{p.parametro}</span>{p.valor_declarado && <strong>{p.valor_declarado}</strong>}</span>
                <span className="meta">{p.fuente} · <a href={p.url} target="_blank" rel="noopener noreferrer nofollow">{p.dominio}</a>{p.valor_declarado ? "" : " · valor sin comprobar en el resumen"}</span>
                {p.nota && <span className="meta">{p.nota}</span>}
                {p.dominio_autorizado && p.es_pdf
                  ? <button className="boton si" disabled={trabajando} onClick={() => cargarFicha(p)}>Cargar la ficha</button>
                  : <span className="meta">{p.dominio_autorizado ? "No es un PDF: busca su ficha técnica y cárgala en Fichas técnicas." : `Dominio sin autorizar (${p.dominio}): si es el oficial del fabricante, añádelo en config/fichas.yaml.`}</span>}
              </li>
            ))}
          </ul>
          {c.sin_pistas?.length > 0 && <p className="meta">Sin pistas útiles para: {c.sin_pistas.join(", ")}.</p>}
        </>
      )}
    </div>
  );
}
