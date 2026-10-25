"use client";
import { barras, etiquetaDia, formatearDelta, formatearValor, segmentos, unidadVisible } from "../lib/kpi";

// Piezas compartidas por el panel de un agente y el dashboard de un departamento
export function Tarjeta({ k, malo }) {
  const d = formatearDelta(k.delta);
  const no = k.estado === "no_disponible";
  return (
    <article className={`kp-tarjeta${no ? " no" : ""}`}>
      <div className="kp-nombre">{k.nombre}</div>
      {no ? (
        <><div className="kp-valor apagado">No disponible</div><div className="kp-ayuda">{k.motivo}</div></>
      ) : (
        <>
          <div className="kp-valor">{formatearValor(k.valor, k.unidad)} <small>{k.valor === null ? "" : unidadVisible(k.unidad)}</small></div>
          {d && <div className={`kp-delta s${malo ? -d.signo : d.signo}`} title="Frente al periodo anterior de igual duración">{d.texto}</div>}
          {k.errores > 0 && <div className="kp-ayuda">{k.errores} con error</div>}
          {k.ayuda && <div className="kp-ayuda">{k.ayuda}</div>}
        </>
      )}
    </article>
  );
}

export function Actividad({ serie }) {
  const pet = barras(serie, "peticiones", 90), uso = barras(serie, "usos", 90);
  const w = 100 / serie.length;
  const hay = serie.some((s) => s.peticiones || s.usos);
  const marcas = serie.length > 31 ? 15 : serie.length > 14 ? 5 : 1;
  return (
    <section className="kp-seccion">
      <h2>Actividad por día</h2>
      <svg viewBox="0 0 100 110" preserveAspectRatio="none" role="img" aria-label="Peticiones y usos de herramientas por día" className="kp-grafico">
        {[0, 45, 90].map((y) => <line key={y} x1="0" x2="100" y1={100 - y} y2={100 - y} stroke="#e4e4e0" strokeWidth=".3" vectorEffect="non-scaling-stroke" />)}
        {uso.map((b, i) => <rect key={"u" + i} x={i * w + w * 0.12} width={w * 0.76} y={100 - b.altura} height={b.altura} fill="#d4d4d8"><title>{`${etiquetaDia(b.dia)}: ${b.usos} usos de herramientas`}</title></rect>)}
        {pet.map((b, i) => <rect key={"p" + i} x={i * w + w * 0.28} width={w * 0.44} y={100 - b.altura} height={b.altura} fill="#1c1c1c"><title>{`${etiquetaDia(b.dia)}: ${b.peticiones} peticiones`}</title></rect>)}
      </svg>
      <div className="kp-eje">{serie.map((s, i) => <span key={s.dia} style={{ visibility: i % marcas === 0 || i === serie.length - 1 ? "visible" : "hidden" }}>{etiquetaDia(s.dia)}</span>)}</div>
      <div className="kp-leyenda"><span><i style={{ background: "#1c1c1c" }} />Peticiones</span><span><i style={{ background: "#d4d4d8" }} />Usos de herramientas</span></div>
      {!hay && <p className="meta">Todavía no hay actividad en este periodo: se irá rellenando cuando el agente trabaje.</p>}
    </section>
  );
}

export function Herramientas({ lista }) {
  const max = Math.max(1, ...lista.map((h) => h.usos + h.errores));
  return (
    <section className="kp-seccion">
      <h2>Herramientas más usadas</h2>
      {lista.length === 0 ? <p className="meta">Sin uso de herramientas en este periodo.</p> : (
        <ul className="kp-herr">
          {lista.slice(0, 8).map((h) => (
            <li key={h.herramienta}>
              <span className="kp-herr-n">{h.herramienta}</span>
              <span className="kp-barra" aria-hidden="true">
                <i style={{ width: `${(h.usos / max) * 100}%`, background: "#1c1c1c" }} />
                <i style={{ width: `${(h.errores / max) * 100}%`, background: "#f2584b" }} />
              </span>
              <span className="kp-herr-v">{h.usos}{h.errores ? <b> · {h.errores} con error</b> : null}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Aprobaciones({ a }) {
  const seg = segmentos([{ n: a.aprobadas, c: "#2e7d4f", t: "Aprobadas" }, { n: a.rechazadas, c: "#9a9aa2", t: "Rechazadas" }, { n: a.pendientes, c: "#c98a0b", t: "Esperan tu firma" }]);
  return (
    <section className="kp-seccion">
      <h2>Lo que ha propuesto firmar</h2>
      {seg.length === 0 ? <p className="meta">No ha propuesto nada que requiera tu firma en este periodo.</p> : (
        <>
          <div className="kp-apiladas" role="img" aria-label={`${a.aprobadas} aprobadas, ${a.rechazadas} rechazadas, ${a.pendientes} pendientes`}>
            {seg.map((s) => <i key={s.t} style={{ width: `${s.ancho}%`, background: s.c }} title={`${s.t}: ${s.n}`} />)}
          </div>
          <div className="kp-leyenda">{seg.map((s) => <span key={s.t}><i style={{ background: s.c }} />{s.t}: <b>{s.n}</b></span>)}</div>
        </>
      )}
    </section>
  );
}

