"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { claseEncargo, encargoEditado, fechaTexto, mensajeEncargos, origenEncargoTexto } from "../../../../lib/licitaciones";
import { pedirCerebro } from "../../cliente";

/** El encargo a medida que recibe cada agente en esta licitación. Lo redacta el director de la oferta (Claude o ChatGPT; sin modelo, una plantilla) y una persona lo puede editar: lo suyo no lo pisa
 *  ninguna ejecución nueva y se aplica a los agentes que aún no han empezado. Se suma a las reglas de cada agente, nunca las sustituye. `version` cambia cuando avanza la redacción para recargar. */
export default function Encargos({ id, version }) {
  const [lista, setLista] = useState(null);
  const [textos, setTextos] = useState({});
  const [guardando, setGuardando] = useState(null);
  const [error, setError] = useState(null);
  const [abierto, setAbierto] = useState(false);
  const sucios = useRef({});                       // agentes cuyo texto se está editando: recargar no lo pisa
  const cargar = useCallback(async () => {
    try {
      const r = await pedirCerebro(`licitaciones/ofertas/${encodeURIComponent(id)}/encargos`);
      setLista(r.encargos);
      setTextos((t) => Object.fromEntries(r.encargos.map((e) => [e.agente, sucios.current[e.agente] ? t[e.agente] : e.contenido])));
    } catch (e) { if (e.status !== 403 && e.status !== 401 && e.status !== 404) setError(e); setLista((x) => x ?? []); }
  }, [id]);
  useEffect(() => { cargar(); }, [cargar, version]);
  if (!lista || lista.length === 0) return null;
  const hay = lista.some((e) => e.origen);
  const guardar = async (e, vaciar) => {
    setGuardando(e.agente); setError(null);
    try {
      await pedirCerebro(`licitaciones/ofertas/${encodeURIComponent(id)}/encargos/${encodeURIComponent(e.agente)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contenido: vaciar ? "" : textos[e.agente] || "" }) });
      sucios.current[e.agente] = false;
      await cargar();
    } catch (x) { setError(x); }
    finally { setGuardando(null); }
  };
  return (
    <section className="tarjeta" aria-label="Encargos por agente">
      <header>
        <h3>Encargos por agente</h3>
        <button className="boton no" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>{abierto ? "Ocultar" : hay ? "Ver y editar" : "Ver"}</button>
      </header>
      <p className="meta">Al preparar la oferta, el director reparte el trabajo: cada agente recibe un encargo a medida de esta licitación (qué le toca, qué debe entregar, qué no le corresponde). Puedes editarlos: lo tuyo no se pisa y se aplica a los agentes que aún no han empezado. Se suman a las reglas de cada agente, nunca las sustituyen.</p>
      {!hay && <p className="meta">Todavía no se han generado: se crean al pulsar «Preparar la oferta con los agentes».</p>}
      {error && <p role="alert" className="lic-error">{mensajeEncargos(error.status)}</p>}
      {abierto && (
        <ul className="lic-lista">
          {lista.map((e) => (
            <li key={e.agente} className="tarjeta lic-item">
              <span className="lic-fila">
                <span className="titulo">{e.nombre}</span><span className="meta">{e.area}</span>
                <span className={`lic-etiqueta ${claseEncargo(e)}`}>{origenEncargoTexto(e)}</span>
                {e.actualizado && <span className="meta">{fechaTexto(e.actualizado)}</span>}
              </span>
              {e.sensibilidad === "alta" && <span className="meta">Hecho solo con datos públicos del pliego; este agente trabaja siempre en local.</span>}
              <textarea rows={8} value={textos[e.agente] ?? ""} aria-label={`Encargo de ${e.nombre}`} placeholder="Sin generar"
                onChange={(ev) => { sucios.current[e.agente] = true; setTextos((t) => ({ ...t, [e.agente]: ev.target.value })); }} />
              <span className="lic-fila">
                <button className="boton si" disabled={guardando === e.agente || !encargoEditado(e, textos[e.agente])} onClick={() => guardar(e, false)}>Guardar mi versión</button>
                {e.origen === "persona" && <button className="boton no" disabled={guardando === e.agente} onClick={() => guardar(e, true)}>Quitar mi versión</button>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
