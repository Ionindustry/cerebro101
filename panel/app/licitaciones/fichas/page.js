"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { aBase64 } from "../../../lib/adjuntos";
import { ESTADO_FICHA, ORIGEN_FICHA, comandoAutorizar, informeFichasTexto } from "../../../lib/licitaciones";
import { Fallo, pedirCerebro } from "../cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

export default function Fichas() {
  const [d, setD] = useState(undefined);
  const [error, setError] = useState(null);
  const [aviso, setAviso] = useState(null);
  const [trabajando, setTrabajando] = useState(false);
  const [lista, setLista] = useState("");
  const [revision, setRevision] = useState(null);
  const [url, setUrl] = useState("");
  const [marca, setMarca] = useState("");
  const [ref, setRef] = useState("");
  const [ej, setEj] = useState(null);
  const [marcaCarga, setMarcaCarga] = useState("Hikvision");
  const [infoMarca, setInfoMarca] = useState(null);

  const cargar = async () => {
    try { setD(await pedirCerebro("licitaciones/fichas")); setError(null); }
    catch (e) { setError(e); setD((x) => (x === undefined ? null : x)); }
  };
  useEffect(() => { cargar(); }, []);
  const verEjemplos = () => accion(async () => setEj(await pedirCerebro("licitaciones/fichas/ejemplos")));
  const cargarEjemplos = () => accion(async () => { const r = await pedirCerebro("licitaciones/fichas/ejemplos/cargar", enviar({})); setAviso(`Ejemplos: ${r.cargadas} cargadas · ${r.repetidas} ya estaban · ${r.fallidas.length} fallidas · ${r.omitidas} no descargables`); setEj(await pedirCerebro("licitaciones/fichas/ejemplos")); });
  useEffect(() => {                                              // mientras haya una carga en curso, se refresca sola
    if (!d?.cargas?.some((c) => c.estado === "en_curso")) return undefined;
    const t = setInterval(cargar, 8000);
    return () => clearInterval(t);
  }, [d]);

  const verMarca = async (m) => { try { setInfoMarca(await pedirCerebro(`licitaciones/fichas/marca/${encodeURIComponent(m.trim())}`)); } catch { setInfoMarca(null); } };
  useEffect(() => { if (marcaCarga.trim().length >= 2) verMarca(marcaCarga); }, [marcaCarga]);        // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                                              // mientras la marca se carga, se refresca sola
    if (infoMarca?.carga?.estado !== "en_curso") return undefined;
    const t = setInterval(() => verMarca(marcaCarga), 8000);
    return () => clearInterval(t);
  }, [infoMarca, marcaCarga]);                                    // eslint-disable-line react-hooks/exhaustive-deps
  const lanzarMarca = () => accion(async () => { await pedirCerebro("licitaciones/fichas/marca", enviar({ marca: marcaCarga.trim() })); setAviso(`Carga de «${marcaCarga.trim()}» lanzada: baja hasta 40 fichas por pulsación; vuelve a pulsar para seguir.`); await verMarca(marcaCarga); });

  const accion = async (f) => {
    setTrabajando(true); setError(null); setAviso(null);
    try { await f(); await cargar(); } catch (e) { setError(e); } finally { setTrabajando(false); }
  };
  const revisar = (id) => { setLista(id); setRevision(null); if (id) accion(async () => setRevision(await pedirCerebro(`licitaciones/fichas/revisar/${id}`))); };
  const lanzar = () => accion(async () => { await pedirCerebro("licitaciones/fichas/cargar", enviar({ importacion: Number(lista) })); setAviso("Carga lanzada: puede tardar unos minutos."); });
  const porUrl = () => accion(async () => { const r = await pedirCerebro("licitaciones/fichas/url", enviar({ url, marca, referencia: ref })); setAviso(`${r.nombre}: ${ESTADO_FICHA[r.estado] || r.estado}${r.motivo ? ` (${r.motivo})` : ""}`); setUrl(""); });
  const subir = (ev) => {
    const f = ev.target.files?.[0];
    ev.target.value = "";
    if (!f) return;
    if (!/\.pdf$/i.test(f.name)) { setError({ status: 422, detalle: "Solo se admiten fichas en PDF" }); return; }
    accion(async () => { const r = await pedirCerebro("licitaciones/fichas/subir", enviar({ nombre: f.name, marca, referencia: ref, base64: aBase64(await f.arrayBuffer()) })); setAviso(`${r.nombre}: ${ESTADO_FICHA[r.estado] || r.estado}${r.motivo ? ` (${r.motivo})` : ""}`); });
  };

  if (d === undefined) return <main><p>Cargando…</p></main>;
  return (
    <main className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link> · <Link href="/fabricantes">Fabricantes por sector</Link></p>
      <h1>Fichas técnicas de producto</h1>
      <p className="meta">Las fichas de fabricante son la evidencia con la que la comparativa y la tabla de equivalencias demuestran que un producto cumple. Cada PDF pasa por el antivirus y se lee en un proceso aparte.</p>
      {error && <Fallo e={error} />}
      {aviso && <p className="aviso" role="status">{aviso}</p>}
      {d && (<>
        <section className="tarjeta">
          <h2>Todas las fichas de una marca</h2>
          <p className="meta">Toma los modelos de la marca que hay en tus tarifas y busca el PDF oficial de cada uno en el dominio autorizado del fabricante. Baja hasta 40 por pulsación (respeta el tope diario) y sigue donde lo dejó; lo que no encuentra no lo vuelve a buscar hasta pasadas dos semanas.</p>
          <p className="lic-fila">
            <input value={marcaCarga} onChange={(e) => setMarcaCarga(e.target.value)} placeholder="Marca (p. ej. Hikvision)" maxLength={60} aria-label="Marca" disabled={trabajando} />
            <button className="boton si" disabled={trabajando || marcaCarga.trim().length < 2 || infoMarca?.carga?.estado === "en_curso"} onClick={lanzarMarca}>{infoMarca?.carga?.estado === "en_curso" ? "Cargando…" : "Cargar las fichas de la marca"}</button>
          </p>
          {infoMarca && (
            <div className="meta" role="status">
              <p>{infoMarca.modelos} modelos de «{infoMarca.marca}» en tus tarifas · {infoMarca.con_ficha} con ficha · {infoMarca.sin_ficha} sin ficha{infoMarca.no_encontradas ? ` (${infoMarca.no_encontradas} buscadas sin encontrar)` : ""}.</p>
              {infoMarca.carga?.informe?.error && <p className="aviso" role="alert">{infoMarca.carga.informe.error}</p>}
              {infoMarca.carga?.estado === "terminada" && <p>Última carga: {infoMarca.carga.informe.cargadas} nuevas · {infoMarca.carga.informe.repetidas} ya estaban · {infoMarca.carga.informe.sin_enlace} sin PDF encontrado · {infoMarca.carga.informe.errores?.length || 0} con error{infoMarca.carga.informe.tope_diario ? " · se alcanzó el tope diario de descargas: sigue mañana" : ""}.</p>}
              {infoMarca.carga?.informe?.errores?.length > 0 && <ul>{infoMarca.carga.informe.errores.map((x, i) => <li key={i}>{x}</li>)}</ul>}
            </div>
          )}
        </section>
        <section className="tarjeta">
          <h2>1. Desde los enlaces de una lista de proveedor</h2>
          <p className="meta">Dominios autorizados: {d.dominios?.length ? d.dominios.join(", ") : "ninguno (añádelos en config/fichas.yaml: solo se descarga de los dominios oficiales de cada fabricante)"}</p>
          <select value={lista} onChange={(e) => revisar(e.target.value)} aria-label="Lista de proveedor" disabled={trabajando}>
            <option value="">Elige una lista…</option>
            {d.listas.map((l) => <option key={l.id} value={l.id}>{l.proveedor || l.lista} · {l.con_enlace} de {l.lineas} líneas con enlace</option>)}
          </select>
          {revision && (
            <div className="meta">
              <p>{revision.fichas} fichas descargables de dominios autorizados · {revision.lineas_sin_enlace} líneas sin enlace.</p>
              {revision.sugerencias?.length > 0 && (
                <div>
                  <p>Dominios sin autorizar (los decides tú; el directorio de fabricantes dice lo que se sabe):</p>
                  <ul>{revision.sugerencias.map((x) => (
                    <li key={x.dominio}><strong>{x.dominio}</strong> ({x.enlaces} enlaces){x.conocido ? ` · ${x.fabricante}` : ""} — <span className={x.comprobado ? "" : "aviso"}>{x.recomendacion}</span>{x.conocido && x.login && x.login !== "NO_CONFIRMADO" ? ` · login en su área documental: ${x.login}` : ""}</li>
                  ))}</ul>
                  <p>Para autorizar los comprobados, en Ubuntu: <code>{comandoAutorizar(revision.sugerencias)}</code></p>
                </div>
              )}
              <button className="boton si" disabled={trabajando || revision.fichas === 0} onClick={lanzar}>Cargar {revision.fichas} fichas</button>
            </div>
          )}
        </section>
        <section className="tarjeta">
          <h2>2. Una dirección o un PDF a mano</h2>
          <div className="lic-fila">
            <input value={marca} onChange={(e) => setMarca(e.target.value)} placeholder="Marca" maxLength={60} aria-label="Marca" />
            <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Referencia" maxLength={60} aria-label="Referencia" />
          </div>
          <div className="lic-fila">
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/ficha.pdf (dominio autorizado)" maxLength={500} aria-label="Dirección de la ficha" />
            <button className="boton si" disabled={trabajando || url.length < 8} onClick={porUrl}>Descargar</button>
          </div>
          <label className="boton no">Subir un PDF<input type="file" accept="application/pdf,.pdf" hidden disabled={trabajando} onChange={subir} /></label>
        </section>
        <section className="tarjeta">
          <h2>3. Modelos de ejemplo del directorio de fabricantes</h2>
          <p className="meta">Modelos con ficha oficial conocida. Solo se descargan los que son un PDF directo de un dominio autorizado; de los portales se abre la página y se sube el PDF a mano.</p>
          {!ej && <button className="boton no" disabled={trabajando} onClick={verEjemplos}>Ver modelos de ejemplo</button>}
          {ej && (<>
            <ul>{ej.ejemplos.map((x, i) => (
              <li key={i}><strong>{x.fabricante}</strong> {x.modelo} · {x.categoria} — <span className={x.accion === "descargar" ? "" : "aviso"}>{ej.acciones[x.accion]}</span>
                {" "}<a href={x.url} target="_blank" rel="noopener noreferrer">abrir ficha o portal</a>{x.accion === "fuera" ? ` · dominio: ${x.dominio}` : ""}</li>))}</ul>
            <button className="boton si" disabled={trabajando || !ej.ejemplos.some((x) => x.accion === "descargar")} onClick={cargarEjemplos}>Cargar los descargables ({ej.ejemplos.filter((x) => x.accion === "descargar").length})</button>
          </>)}
        </section>
        {d.cargas?.length > 0 && (
          <section className="tarjeta">
            <h2>Últimas cargas</h2>
            <ul>{d.cargas.map((c) => (
              <li key={c.id}>Lista {c.importacion} · {c.estado === "en_curso" ? "en curso…" : informeFichasTexto(c.informe)}
                {c.informe?.fallidas?.length > 0 && <details><summary>Fallos</summary><ul>{c.informe.fallidas.map((f, i) => <li key={i}>{f.url} — {f.motivo}</li>)}</ul></details>}
              </li>))}</ul>
          </section>
        )}
        <section className="tarjeta">
          <h2>Cargadas ({Object.entries(d.por_estado).map(([k, n]) => `${n} ${(ESTADO_FICHA[k] || k).toLowerCase()}`).join(" · ") || "ninguna"})</h2>
          <ul>{d.fichas.map((f) => <li key={f.id}>{f.marca} {f.referencia} · {f.nombre} · {ESTADO_FICHA[f.estado] || f.estado} · {ORIGEN_FICHA[f.origen]}{f.motivo ? ` — ${f.motivo}` : ""}</li>)}</ul>
        </section>
      </>)}
    </main>
  );
}
