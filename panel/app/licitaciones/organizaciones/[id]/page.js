"use client";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  FILTROS_ORG_VACIOS, ROLES_ORGANIZACION, alturasTrimestres, bajaTexto, competenciaDeCpv, cuotaTexto, fichaOrgHref, identificadoresTexto, importeTexto, muestraPoca,
  muestraTexto, orgAQuery, queryAOrg, repeticionTexto, trimestreTexto,
} from "../../../../lib/licitaciones";
import { Fallo, pedir } from "../../cliente";

const num = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 });

function Otras({ titulo, items, conCuota }) {
  if (!items?.length) return null;
  return (
    <section aria-label={titulo}>
      <h4>{titulo}</h4>
      <ol className="lic-lista">
        {items.map((o, i) => {
          const href = fichaOrgHref(o.organizacion?.id);
          return (
            <li key={o.organizacion?.id || i} className="lic-fila">
              {href ? <Link href={href}>{o.organizacion?.nombre || "(sin nombre)"}</Link> : <span>{o.organizacion?.nombre || "(sin nombre)"}</span>}
              <span className="meta">{o.contratos} {o.contratos === 1 ? "contrato" : "contratos"}{conCuota && typeof o.cuota === "number" ? ` · ${cuotaTexto(o.cuota)} del importe` : ""}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Trimestres({ ts }) {
  if (!ts?.length) return null;
  const alturas = alturasTrimestres(ts);
  return (
    <section aria-label="Contratos por trimestre">
      <h4>Contratos por trimestre</h4>
      <div className="lic-barras" role="img" aria-label={ts.map((t) => `${trimestreTexto(t.trimestre)}: ${t.contratos}`).join(", ")}>
        {ts.map((t, i) => (
          <div key={`${t.trimestre}-${i}`} className="lic-barra" title={`${trimestreTexto(t.trimestre)}: ${t.contratos} · ${importeTexto(t.importe)}`}>
            <span style={{ height: `${alturas[i]}%` }} />
            <small>{trimestreTexto(t.trimestre)}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function Rol({ clave, r }) {
  const comprador = clave === "comprador";
  const rep = comprador ? repeticionTexto(r.repeticion_adjudicatario) : "";
  return (
    <section className="tarjeta lic-rol" aria-labelledby={`rol-${clave}`}>
      <h2 id={`rol-${clave}`}>{comprador ? "Como comprador" : "Como adjudicataria"}</h2>
      <p className="meta" aria-live="polite">{muestraTexto(r.muestra)}</p>
      {muestraPoca(r.muestra) && <p role="status" className="lic-aviso">Hay pocas adjudicaciones detrás de estas cifras: tómalas como orientación.</p>}
      {r.contratos > 0 ? (
        <>
          <dl className="lic-ficha">
            <div><dt>Contratos</dt><dd>{r.contratos}</dd></div>
            <div><dt>Importe adjudicado</dt><dd>{importeTexto(r.importe_total)}</dd></div>
            <div><dt>Baja media</dt><dd>{bajaTexto(r.baja_media)}</dd></div>
            <div><dt>Baja (percentiles 25 / 50 / 75)</dt><dd>{bajaTexto(r.baja_p25)} / {bajaTexto(r.baja_p50)} / {bajaTexto(r.baja_p75)}</dd></div>
            <div><dt>Ofertas por licitación</dt><dd>{typeof r.ofertas_medias === "number" ? num.format(r.ofertas_medias) : "—"}</dd></div>
          </dl>
          {rep && <p className={`meta ${r.repeticion_adjudicatario >= 0.5 ? "lic-aviso" : ""}`}>{rep}</p>}
          <Otras titulo={comprador ? "A quién adjudica" : "A quién vende"} items={comprador ? r.principales_adjudicatarios : r.principales_compradores} conCuota={comprador} />
          {r.por_cpv?.length > 0 && (
            <section aria-label="Mercados">
              <h4>En qué mercados</h4>
              <ul className="lic-fila">{r.por_cpv.map((c) => <li key={c.cpv}><Link className="lic-etiqueta" href={competenciaDeCpv(c.cpv)} title="Ver quién gana en este mercado">CPV {c.cpv} · {c.contratos}</Link></li>)}</ul>
            </section>
          )}
          <Trimestres ts={r.por_trimestre} />
        </>
      ) : <p className="meta">En este periodo y con estos filtros no hay adjudicaciones en este papel.</p>}
    </section>
  );
}

function Ficha() {
  const { id } = useParams();
  const router = useRouter();
  const sp = useSearchParams();
  const clave = sp.toString();                                   // la dirección ES la consulta: se puede compartir
  const [f, setF] = useState(() => queryAOrg(sp));
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let vigente = true;
    setD(null); setError(null);
    pedir(`organizations/${encodeURIComponent(id)}?${orgAQuery(queryAOrg(new URLSearchParams(clave)))}`)
      .then((r) => vigente && setD(r)).catch((e) => vigente && setError(e));
    return () => { vigente = false; };
  }, [id, clave]);

  const enviar = (ev) => { ev.preventDefault(); const q = orgAQuery(f).toString(); router.push(q ? `/licitaciones/organizaciones/${id}?${q}` : `/licitaciones/organizaciones/${id}`); };
  const poner = (k) => (ev) => setF((x) => ({ ...x, [k]: ev.target.value }));
  const nif = d?.identificadores?.find((i) => i.esquema === "NIF")?.valor;

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones/competencia">← Competencia</Link></p>
      {error && (error.status === 404 ? <p role="alert" className="lic-error">No hay datos de esta organización: ni como comprador ni como adjudicataria.</p> : <Fallo e={error} />)}
      {!d && !error && <p className="meta" aria-busy="true">Cargando…</p>}
      {d && (
        <>
          <header>
            <h1>{d.nombre || "(sin nombre)"}</h1>
            <p className="lic-fila">
              {(d.roles || []).map((r) => <span key={r} className="lic-etiqueta">{ROLES_ORGANIZACION[r] || r}</span>)}
              {d.identificadores?.length > 0 && <span className="meta">{identificadoresTexto(d.identificadores)}</span>}
              {d.nuts?.length > 0 && <span className="meta">Zonas: {d.nuts.join(", ")}</span>}
            </p>
            {d.persona_fisica && <p role="note" className="lic-aviso">Persona física: se identifica por su nombre porque su NIF no se publica completo; puede haber homónimos.</p>}
            {d.nombres_alternativos?.length > 0 && (
              <details>
                <summary>Otros nombres con los que aparece ({d.nombres_alternativos.length})</summary>
                <ul>{d.nombres_alternativos.map((n) => <li key={n}>{n}</li>)}</ul>
                <p className="meta">Son informativos: así la escriben otros órganos. No prueban que sea la misma empresa y nunca se usan para unir organizaciones.</p>
              </details>
            )}
          </header>
          <form className="tarjeta lic-form" onSubmit={enviar}>
            <div className="lic-campos">
              <label>Adjudicado desde<input type="date" value={f.desde} onChange={poner("desde")} /></label>
              <label>Adjudicado hasta<input type="date" value={f.hasta} onChange={poner("hasta")} /></label>
              <label>CPV<input type="text" value={f.cpv} onChange={poner("cpv")} placeholder="72 35125" /><span className="ayuda">Acota las cifras a estos mercados</span></label>
            </div>
            <div className="lic-fila">
              <button className="boton si" type="submit">Aplicar</button>
              <button className="boton no" type="button" onClick={() => { setF(FILTROS_ORG_VACIOS); router.push(`/licitaciones/organizaciones/${id}`); }}>Limpiar</button>
              {d.roles?.includes("comprador") && nif && <Link className="lic-vuelve" href={`/licitaciones/vencen?comprador=${nif}`}>Ver sus contratos que vencen</Link>}
            </div>
          </form>
          <p className="meta">Solo cuenta lo adjudicado en euros (sin IVA). La baja se muestra cuando el presupuesto del lote es fiable.</p>
          {d.como_comprador && <Rol clave="comprador" r={d.como_comprador} />}
          {d.como_proveedor && <Rol clave="proveedor" r={d.como_proveedor} />}
        </>
      )}
    </div>
  );
}

export default function PaginaOrganizacion() {
  return <Suspense fallback={<div className="lic"><p className="meta">Cargando…</p></div>}><Ficha /></Suspense>;
}
