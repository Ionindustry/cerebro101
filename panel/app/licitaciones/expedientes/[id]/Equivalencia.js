"use client";
import { useCallback, useEffect, useState } from "react";
import { VEREDICTO_EQUIVALENCIA, evidenciaTexto, exigidoTexto, fechaTexto, resumenEquivalencia } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

const CLASE = { supera: "ok", iguala: "ok", no_cumple: "mal", sin_datos: "aviso" };

/** La tabla de equivalencias «iguala o supera»: cada parámetro medible del pliego técnico con los productos del catálogo que lo cumplen. El veredicto lo fija el código comparando los números; lo que no se pudo
 *  comparar queda marcado «sin verificar». Es un informe de ayuda: una persona lo revisa. `version` cambia al avanzar la preparación y la recarga. */
export default function Equivalencia({ id, version }) {
  const [d, setD] = useState(undefined);
  const [abierto, setAbierto] = useState(false);
  const cargar = useCallback(async () => {
    try { setD((await pedirCerebro(`licitaciones/ofertas/${encodeURIComponent(id)}/equivalencia`)).equivalencia); }
    catch { setD((x) => (x === undefined ? null : x)); }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar, version]);
  if (d === undefined || d === null) return null;
  const c = d.contenido, ev = d.evidencias;
  return (
    <section className="tarjeta" aria-label="Tabla de equivalencias">
      <header>
        <h3>Tabla de equivalencias: ¿iguala o supera?</h3>
        <button className="boton no" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>{abierto ? "Ocultar" : "Ver"}</button>
      </header>
      <p className="meta">Hecha con {d.proveedor === "claude" ? "Claude" : "ChatGPT"}{d.modelo ? ` (${d.modelo})` : ""} el {fechaTexto(d.actualizado)}. {resumenEquivalencia(c)}. Los números los compara el código con el valor que figura en la ficha; «sin verificar» pide que una persona lo mire.</p>
      {abierto && (
        <>
          <ul className="lic-lista">
            {c.parametros.map((p, i) => (
              <li key={i} className="tarjeta lic-item">
                <span className="lic-fila"><span className="titulo">{p.parametro}</span><span className="lic-etiqueta">{exigidoTexto(p)}</span>{!p.cubierto && <span className="lic-etiqueta aviso">Sin producto acreditado</span>}</span>
                {p.cita && <span className="meta">Pliego: «{p.cita}»{p.cita_en_pliego ? "" : " (no se ha encontrado literal en el pliego: revisar)"}</span>}
                {p.candidatos.map((k, j) => (
                  <span key={j} className="lic-fila">
                    <span className={`lic-etiqueta ${CLASE[k.veredicto]}`}>{VEREDICTO_EQUIVALENCIA[k.veredicto]}</span><span>{k.producto}</span>{k.valor_producto && <strong>{k.valor_producto}</strong>}
                    {k.veredicto !== "sin_datos" && !k.verificado && <span className="lic-etiqueta aviso">Sin verificar</span>}
                    {k.nota && <span className="meta">{k.nota}</span>}
                    {k.evidencia?.length > 0 && <span className="meta"> Evidencia: {k.evidencia.map((i) => evidenciaTexto(i, ev)).join("; ")}</span>}
                  </span>
                ))}
                {p.recomendado && <span><strong>Recomendado:</strong> {p.recomendado}</span>}
              </li>
            ))}
          </ul>
          {c.pendientes.length > 0 && (<><h4>Datos que faltan</h4><ul>{c.pendientes.map((x, i) => <li key={i}>{x}</li>)}</ul></>)}
        </>
      )}
    </section>
  );
}
