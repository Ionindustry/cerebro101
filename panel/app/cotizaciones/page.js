"use client";
import { useCallback, useEffect, useState } from "react";
import { ESTADO_COTIZACION, ETIQUETA_ERP, MODO_COTIZACION, claseCotizacion, cotizacionAEnvio, mailtoHref, mensajeCotizaciones, respuestaAEnvio, respuestaTexto, resumenCotizacion } from "../../lib/cotizaciones";
import { fechaTexto } from "../../lib/licitaciones";
import { pedirCerebro } from "../licitaciones/cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo ?? {}) });

function Tarjeta({ c, hacer, ocupado }) {
  const [abierta, setAbierta] = useState(c.estado === "borrador");
  const [resp, setResp] = useState({ precio: "", moneda: "EUR", plazo_dias: "", validez_hasta: "", nota: "" });
  const [item, setItem] = useState("");
  const [error, setError] = useState(null);
  const puedeResponder = ["borrador", "enviada", "respondida"].includes(c.estado);
  const guardarRespuesta = () => {
    const { cuerpo, error: e } = respuestaAEnvio(resp);
    if (e) { setError(e); return; }
    setError(null);
    hacer(() => pedirCerebro(`cotizaciones/${c.id}/respuesta`, enviar(cuerpo)), () => "Respuesta guardada: la partida de la oferta ya usa este coste.");
  };
  const copiar = async () => { try { await navigator.clipboard.writeText(`Asunto: ${c.asunto}\n\n${c.cuerpo}`); setError(null); } catch { setError("No se ha podido copiar: selecciona el texto y cópialo."); } };
  return (
    <li className="tarjeta">
      <strong>{resumenCotizacion(c)}</strong> <span className={`lic-etiqueta ${claseCotizacion(c)}`}>{ESTADO_COTIZACION[c.estado]}{c.sin_respuesta ? " · sin respuesta" : ""}</span>
      <div className="meta">Creada {fechaTexto(c.creado)} por {c.creado_por} · {MODO_COTIZACION[c.modo]}{c.enviado_en ? ` · enviada ${fechaTexto(c.enviado_en)} por ${c.enviado_por}` : ""}</div>
      {c.respuesta?.precio && <p><strong>Respuesta: {respuestaTexto(c.respuesta)}</strong>{c.respuesta.nota ? <span className="meta"> · {c.respuesta.nota}</span> : null}</p>}
      <button className="boton no" onClick={() => setAbierta((v) => !v)}>{abierta ? "Ocultar el correo" : "Ver el correo"}</button>
      {abierta && (
        <div>
          <p className="meta">Para: {c.email}</p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{`Asunto: ${c.asunto}\n\n${c.cuerpo}`}</pre>
          {c.estado === "borrador" && c.modo === "manual" && (
            <div className="lic-fila">
              <a className="boton si" href={mailtoHref(c)}>Abrir en mi programa de correo</a>
              <button className="boton no" onClick={copiar}>Copiar el correo</button>
              <button className="boton si" disabled={ocupado} onClick={() => hacer(() => pedirCerebro(`cotizaciones/${c.id}/marcar-enviada`, enviar({})), () => "Marcada como enviada.")}>Ya lo he enviado</button>
            </div>
          )}
          {c.estado === "borrador" && c.modo === "enviar" && (
            <div className="lic-fila">
              <button className="boton si" disabled={ocupado} onClick={() => { if (window.confirm(`¿Enviar este correo a ${c.email}? Sale de la empresa y queda constancia a tu nombre.`)) hacer(() => pedirCerebro(`cotizaciones/${c.id}/enviar`, enviar({ confirmo: true })), () => "Enviada al proveedor."); }}>Enviar al proveedor</button>
              <span className="meta">Solo Dirección envía. El texto no se edita: el sistema lo redacta siempre.</span>
            </div>
          )}
        </div>
      )}
      {puedeResponder && (
        <details>
          <summary>{c.estado === "respondida" ? "Corregir la respuesta del proveedor" : "Registrar la respuesta del proveedor"}</summary>
          <div className="lic-fila">
            <input value={resp.precio} onChange={(e) => setResp((r) => ({ ...r, precio: e.target.value }))} placeholder="Precio unitario" aria-label="Precio unitario" size={10} inputMode="decimal" />
            <select value={resp.moneda} onChange={(e) => setResp((r) => ({ ...r, moneda: e.target.value }))} aria-label="Moneda">{["EUR", "USD", "GBP"].map((m) => <option key={m}>{m}</option>)}</select>
            <input value={resp.plazo_dias} onChange={(e) => setResp((r) => ({ ...r, plazo_dias: e.target.value }))} placeholder="Plazo (días)" aria-label="Plazo de entrega en días" size={8} inputMode="numeric" />
            <input value={resp.validez_hasta} onChange={(e) => setResp((r) => ({ ...r, validez_hasta: e.target.value }))} placeholder="Válida hasta AAAA-MM-DD" aria-label="Validez de la oferta" size={18} />
          </div>
          <input value={resp.nota} onChange={(e) => setResp((r) => ({ ...r, nota: e.target.value }))} placeholder="Nota (opcional)" aria-label="Nota" maxLength={500} size={50} />
          <button className="boton si" disabled={ocupado} onClick={guardarRespuesta}>Guardar la respuesta</button>
        </details>
      )}
      <div className="meta">ERPNext: {c.erp?.estado ? `${ETIQUETA_ERP[c.erp.estado] || c.erp.estado}${c.erp.nombre ? ` (${c.erp.nombre})` : ""}${c.erp.motivo ? ` — ${c.erp.motivo}` : ""}` : "aún no se ha creado la petición de cotización"}</div>
      {c.estado !== "cancelada" && !["creada"].includes(c.erp?.estado) && (
        <div className="lic-fila">
          <input value={item} onChange={(e) => setItem(e.target.value)} placeholder="Código del artículo en el ERP" aria-label="Código del artículo en el ERP" size={28} />
          <button className="boton no" disabled={ocupado} onClick={() => hacer(() => pedirCerebro(`cotizaciones/${c.id}/erp`, enviar({ item_code: item })), (r) => r.erp?.estado === "creada" ? "Petición de cotización creada en el ERP (borrador)." : (r.erp?.motivo || "No se ha podido crear en el ERP."))}>Crear en ERPNext</button>
        </div>
      )}
      {error && <p role="alert" className="lic-error">{error}</p>}
      {["borrador", "enviada"].includes(c.estado) && <button className="boton no" disabled={ocupado} onClick={() => { if (window.confirm("¿Cancelar esta cotización?")) hacer(() => pedirCerebro(`cotizaciones/${c.id}/cancelar`, enviar({})), () => "Cancelada."); }}>Cancelar</button>}
    </li>
  );
}

function Contactos({ contactos, hacer, ocupado }) {
  const [f, setF] = useState({ proveedor: "", email: "", nombre: "" });
  return (
    <section className="tarjeta" aria-label="Contactos de proveedores">
      <h2>Contactos de proveedores</h2>
      <p className="meta">A qué correo se le pide la cotización a cada proveedor (el nombre tiene que ser el mismo que en «Proveedores y marcas»). Solo Dirección los cambia.</p>
      <ul>{contactos.map((c) => <li key={c.proveedor}><strong>{c.proveedor}</strong> · {c.email}{c.nombre ? ` · ${c.nombre}` : ""}</li>)}</ul>
      {contactos.length === 0 && <p className="meta">Aún no hay ninguno.</p>}
      <div className="lic-fila">
        <input value={f.proveedor} onChange={(e) => setF((x) => ({ ...x, proveedor: e.target.value }))} placeholder="Proveedor" aria-label="Proveedor" maxLength={80} />
        <input value={f.email} onChange={(e) => setF((x) => ({ ...x, email: e.target.value }))} placeholder="correo@proveedor.com" aria-label="Correo" maxLength={200} />
        <input value={f.nombre} onChange={(e) => setF((x) => ({ ...x, nombre: e.target.value }))} placeholder="Persona de contacto (opcional)" aria-label="Persona de contacto" maxLength={80} />
        <button className="boton no" disabled={ocupado || f.proveedor.trim().length < 2 || f.email.trim().length < 3} onClick={() => hacer(() => pedirCerebro("cotizaciones/contactos", enviar(f)), () => "Contacto guardado.").then(() => setF({ proveedor: "", email: "", nombre: "" }))}>Guardar contacto</button>
      </div>
    </section>
  );
}

export default function Cotizaciones() {
  const [lista, setLista] = useState(undefined);
  const [contactos, setContactos] = useState([]);
  const [estado, setEstado] = useState("");
  const [msg, setMsg] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const [f, setF] = useState({ referencia: "", marca: "", cantidad: "1", plazo_tipo: "dias", plazo_valor: "15", proveedor: "", modo: "manual", licitacion: "", partida: "" });
  const [sugeridos, setSugeridos] = useState(null);

  useEffect(() => {                                       // «Pedir cotización» desde una partida enlaza aquí con los datos ya puestos
    const q = new URLSearchParams(window.location.search);
    setF((x) => ({ ...x, referencia: q.get("ref") || x.referencia, marca: q.get("marca") || x.marca, cantidad: q.get("cantidad") || x.cantidad, licitacion: q.get("licitacion") || "", partida: q.get("partida") || "" }));
  }, []);

  const cargar = useCallback(async () => {
    try { setLista((await pedirCerebro(`cotizaciones${estado ? `?estado=${estado}` : ""}`)).cotizaciones); setContactos((await pedirCerebro("cotizaciones/contactos")).contactos); }
    catch (e) { setLista(null); setMsg({ mal: true, texto: mensajeCotizaciones(e.status, e.detalle) }); }
  }, [estado]);
  useEffect(() => { cargar(); }, [cargar]);

  const hacer = async (fn, ok) => {
    setOcupado(true); setMsg(null);
    try { const r = await fn(); setMsg({ mal: false, texto: ok(r) }); await cargar(); return r; }
    catch (e) { setMsg({ mal: true, texto: mensajeCotizaciones(e.status, e.detalle) }); } finally { setOcupado(false); }
  };
  const buscarProveedores = async () => {
    try { setSugeridos((await pedirCerebro(`cotizaciones/sugerencias?marca=${encodeURIComponent(f.marca.trim())}`)).proveedores); }
    catch (e) { setSugeridos([]); setMsg({ mal: true, texto: mensajeCotizaciones(e.status, e.detalle) }); }
  };
  const crear = async () => {
    const { cuerpo, error } = cotizacionAEnvio(f);
    if (error) { setMsg({ mal: true, texto: error }); return; }
    const r = await hacer(() => pedirCerebro("cotizaciones", enviar(cuerpo)), () => "Creada en borrador: el correo ya está redactado, mira abajo.");
    if (r) setF((x) => ({ ...x, referencia: "", marca: "", cantidad: "1", licitacion: "", partida: "" }));
  };

  return (
    <main className="lic">
      <h1>Cotizaciones a proveedores</h1>
      <p className="meta">Cuando una referencia no tiene precio en las tarifas, se le pide cotización a un proveedor que la distribuya. El correo lo redacta siempre el sistema y lleva <strong>solo la referencia, la cantidad y el plazo de entrega</strong>: nunca el cliente, la licitación ni precios nuestros.</p>
      {msg && <p role={msg.mal ? "alert" : "status"} className={msg.mal ? "lic-error" : "aviso"}>{msg.texto}</p>}
      {lista === undefined && <p>Cargando…</p>}
      {lista !== undefined && lista !== null && (<>
        <section className="tarjeta" aria-label="Nueva cotización">
          <h2>Nueva cotización</h2>
          <div className="lic-fila">
            <input value={f.referencia} onChange={(e) => setF((x) => ({ ...x, referencia: e.target.value }))} placeholder="Referencia" aria-label="Referencia" maxLength={80} />
            <input value={f.marca} onChange={(e) => setF((x) => ({ ...x, marca: e.target.value }))} placeholder="Marca (para elegir proveedor; no sale en el correo)" aria-label="Marca" maxLength={60} size={34} />
            <input value={f.cantidad} onChange={(e) => setF((x) => ({ ...x, cantidad: e.target.value }))} placeholder="Cantidad" aria-label="Cantidad" size={6} inputMode="numeric" />
          </div>
          <div className="lic-fila">
            <select value={f.plazo_tipo} onChange={(e) => setF((x) => ({ ...x, plazo_tipo: e.target.value, plazo_valor: "" }))} aria-label="Tipo de plazo"><option value="dias">Plazo en días</option><option value="fecha">Fecha límite</option></select>
            <input value={f.plazo_valor} onChange={(e) => setF((x) => ({ ...x, plazo_valor: e.target.value }))} placeholder={f.plazo_tipo === "dias" ? "15" : "AAAA-MM-DD"} aria-label="Plazo de entrega" size={12} />
          </div>
          <div className="lic-fila">
            <input value={f.proveedor} onChange={(e) => setF((x) => ({ ...x, proveedor: e.target.value }))} placeholder="Proveedor" aria-label="Proveedor" maxLength={80} list="proveedores-sugeridos" />
            <datalist id="proveedores-sugeridos">{(sugeridos || contactos.map((c) => ({ proveedor: c.proveedor }))).map((p) => <option key={p.proveedor} value={p.proveedor} />)}</datalist>
            <button className="boton no" disabled={f.marca.trim().length < 2} onClick={buscarProveedores}>¿Quién distribuye esta marca?</button>
          </div>
          {sugeridos && <p className="meta">{sugeridos.length === 0 ? "Ningún proveedor guardado distribuye esa marca (mira «Proveedores y marcas» en Precios)." : <>Distribuyen la marca: {sugeridos.map((p, i) => <span key={p.proveedor}>{i ? " · " : ""}<button className="boton no" onClick={() => setF((x) => ({ ...x, proveedor: p.proveedor }))}>{p.proveedor}{p.email ? "" : " (sin correo)"}</button></span>)}</>}</p>}
          <fieldset>
            <legend>Cómo se envía (a elegir en cada caso)</legend>
            {Object.entries(MODO_COTIZACION).map(([k, v]) => <label key={k} style={{ display: "block" }}><input type="radio" name="modo" checked={f.modo === k} onChange={() => setF((x) => ({ ...x, modo: k }))} /> {v}</label>)}
          </fieldset>
          {f.licitacion && <p className="meta">Ligada a la licitación y a la partida de la que vienes (no sale en el correo).</p>}
          <button className="boton si" disabled={ocupado} onClick={crear}>Crear con el correo ya redactado</button>
        </section>

        <div className="lic-fila">
          <select value={estado} onChange={(e) => setEstado(e.target.value)} aria-label="Filtrar por estado"><option value="">Todas</option>{Object.entries(ESTADO_COTIZACION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </div>
        {lista.length === 0 && <p className="meta">No hay cotizaciones{estado ? " en ese estado" : " todavía"}.</p>}
        <ul className="lic-lista">{lista.map((c) => <Tarjeta key={c.id} c={c} hacer={hacer} ocupado={ocupado} />)}</ul>
        <Contactos contactos={contactos} hacer={hacer} ocupado={ocupado} />
      </>)}
    </main>
  );
}
