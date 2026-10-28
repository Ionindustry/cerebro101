"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  VENCEN_VACIO, agruparPorMes, confianzaFinTexto, fechaCivilTexto, fichaOrgHref, importeTexto, prorrogasTexto, queryAVencen, totalTexto, vencenAQuery, vencenProblema, venceEnTexto,
} from "../../../lib/licitaciones";
import { Fallo, pedir } from "../cliente";

const hoyMadrid = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(new Date());   // «AAAA-MM-DD»

function Contrato({ x, hoy }) {
  const cuando = venceEnTexto(x.fecha_fin, hoy);
  return (
    <li className="tarjeta lic-venc">
      <Link href={`/licitaciones/expedientes/${x.licitacion_id}`} className="titulo">{x.titulo || x.expediente || "(sin título)"}{x.lote && x.lote !== "1" ? ` · lote ${x.lote}` : ""}</Link>
      <span className="meta">
        {fichaOrgHref(x.comprador?.id) ? <Link href={fichaOrgHref(x.comprador.id)}>{x.comprador.nombre}</Link> : x.comprador?.nombre}
        {x.expediente ? `${x.comprador?.nombre ? " · " : ""}${x.expediente}` : ""}
      </span>
      <dl className="lic-ficha">
        <div><dt>Termina</dt><dd>{fechaCivilTexto(x.fecha_fin)}{cuando ? ` (${cuando})` : ""}<br /><span className="meta">{confianzaFinTexto(x.confianza)}</span></dd></div>
        <div><dt>Lo tiene ahora</dt><dd>{fichaOrgHref(x.adjudicatario?.id) ? <Link href={fichaOrgHref(x.adjudicatario.id)}>{x.adjudicatario.nombre || "—"}</Link> : (x.adjudicatario?.nombre || "—")}{x.adjudicatario?.nif ? <span className="meta"> · {x.adjudicatario.nif}</span> : null}</dd></div>
        <div><dt>Importe adjudicado</dt><dd>{importeTexto(x.importe_adjudicado)}</dd></div>
        <div><dt>Prórrogas</dt><dd>{prorrogasTexto(x)}</dd></div>
      </dl>
      {x.prorrogas_texto && (
        <details>
          <summary>Qué dice el pliego sobre las prórrogas</summary>
          <p className="lic-informe-texto">{x.prorrogas_texto}</p>
        </details>
      )}
    </li>
  );
}

function Vencen() {
  const router = useRouter();
  const sp = useSearchParams();
  const clave = sp.toString();                                   // la dirección de la página ES la consulta: se puede compartir
  const [f, setF] = useState(() => queryAVencen(sp));
  const [d, setD] = useState(null);
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const ultima = useRef(0);
  const hoy = useMemo(hoyMadrid, []);
  const problema = vencenProblema(f);

  useEffect(() => {
    const n = ++ultima.current;
    const fl = queryAVencen(new URLSearchParams(clave));
    if (vencenProblema(fl)) { setError({ status: 400 }); setD(null); setItems([]); setCursor(null); setCargando(false); return; }
    setCargando(true); setError(null);
    pedir(`expiring-contracts?${vencenAQuery(fl)}&limit=30`)
      .then((r) => { if (n === ultima.current) { setD(r); setItems(r.items); setCursor(r.siguiente_cursor); } })
      .catch((e) => { if (n === ultima.current) { setError(e); setD(null); setItems([]); setCursor(null); } })
      .finally(() => { if (n === ultima.current) setCargando(false); });
  }, [clave]);

  const mas = async () => {
    setCargando(true);
    try {
      const r = await pedir(`expiring-contracts?${vencenAQuery(queryAVencen(new URLSearchParams(clave)))}&limit=30&cursor=${encodeURIComponent(cursor)}`);
      setItems((a) => [...a, ...r.items]); setCursor(r.siguiente_cursor);
    } catch (e) { setError(e); } finally { setCargando(false); }
  };
  const enviar = (ev) => {
    ev.preventDefault();
    if (problema) return;
    const q = vencenAQuery(f).toString();
    router.push(q ? `/licitaciones/vencen?${q}` : "/licitaciones/vencen");
  };
  const poner = (k) => (ev) => setF((x) => ({ ...x, [k]: ev.target.value }));
  const grupos = useMemo(() => agruparPorMes(items), [items]);

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link></p>
      <h1>Contratos que vencen</h1>
      <p className="meta">Contratos ya adjudicados que están a punto de terminar: el concurso volverá a salir. Sin fechas, mira de aquí a 3 meses hasta dentro de 12 meses.</p>
      <form className="tarjeta lic-form" onSubmit={enviar} role="search">
        <div className="lic-campos">
          <label>CPV<input type="text" value={f.cpv} onChange={poner("cpv")} placeholder="72 35125300" /><span className="ayuda">Códigos o prefijos de 2 a 8 cifras</span></label>
          <label>Zona (NUTS)<input type="text" value={f.nuts} onChange={poner("nuts")} placeholder="ES512" /><span className="ayuda">ES51 = Cataluña, ES512 = Girona</span></label>
          <label>Comprador (NIF)<input type="text" value={f.comprador} onChange={poner("comprador")} placeholder="P1708500E" /></label>
          <label>Importe mínimo (€, sin IVA)<input type="text" inputMode="decimal" value={f.importeMin} onChange={poner("importeMin")} /></label>
          <label>Termina desde<input type="date" value={f.desde} onChange={poner("desde")} /></label>
          <label>Termina hasta<input type="date" value={f.hasta} onChange={poner("hasta")} /><span className="ayuda">Como máximo 36 meses</span></label>
        </div>
        <label className="lic-check"><input type="checkbox" checked={f.conProrrogas} onChange={(e) => setF((x) => ({ ...x, conProrrogas: e.target.checked }))} />Contar las prórrogas posibles (cuando el pliego las detalla)</label>
        {problema && <p role="alert" className="lic-error">{problema}</p>}
        <div className="lic-fila">
          <button className="boton si" type="submit" disabled={Boolean(problema)}>Ver contratos</button>
          <button className="boton no" type="button" onClick={() => { setF(VENCEN_VACIO); router.push("/licitaciones/vencen"); }}>Limpiar</button>
        </div>
      </form>

      {error && <Fallo e={error} />}
      {d && (
        <>
          <p className="meta" aria-live="polite">
            Terminan entre {fechaCivilTexto(d.periodo?.vence_desde)} y {fechaCivilTexto(d.periodo?.vence_hasta)} · {totalTexto(d.total).replace("resultados", "contratos").replace("resultado", "contrato")}
          </p>
          <p className="meta">La fecha de fin es la prevista en el contrato (inicio + duración): no cuenta modificaciones ni prórrogas ya ejecutadas. Compruébala en el pliego antes de planificar.</p>
        </>
      )}
      {cargando && items.length === 0 && <p className="meta" aria-busy="true">Buscando…</p>}
      {!error && !cargando && d && items.length === 0 && <p className="meta">No hay contratos que terminen en ese periodo con esos filtros. Prueba con un periodo más largo o menos filtros.</p>}
      {grupos.map((g) => (
        <section key={g.mes} aria-labelledby={`mes-${g.mes}`}>
          <h2 id={`mes-${g.mes}`} className="lic-mes">{g.titulo}</h2>
          <ul className="lic-lista">{g.items.map((x) => <Contrato key={x.adjudicacion_id} x={x} hoy={hoy} />)}</ul>
        </section>
      ))}
      {cursor && <div><button className="boton no" onClick={mas} disabled={cargando}>{cargando ? "Cargando…" : "Cargar más"}</button></div>}
    </div>
  );
}

export default function PaginaVencen() {
  return <Suspense fallback={<div className="lic"><p className="meta">Cargando…</p></div>}><Vencen /></Suspense>;
}
