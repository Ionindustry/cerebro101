"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { admiteResumen, ambitoTexto, canalDeAlertaTexto, canalesDe, competenciaGuardable, competidoresDeTexto, correoValido, DOMINIO_CORREO, esCompetencia, ganadoresTexto, TIPOS_ALERTA, vigilaTexto, encajeClase, EVENTOS_ALERTA, eventoEtiqueta, fechaTexto, filtroDeAlerta, filtroTexto, importeTexto, mensajeAlertas, sinLeerTexto } from "../../../lib/licitaciones";
import { pedirCerebro } from "../cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });

function Avisos({ avisos, onLeer }) {
  return (
    <section className="lic" aria-label="Avisos">
      <div className="lic-fila">
        <h2>Avisos <span className="meta">· {sinLeerTexto(avisos.sin_leer)}</span></h2>
        {avisos.sin_leer > 0 && <button className="boton no" onClick={() => onLeer(null)}>Marcar todos como leídos</button>}
      </div>
      {avisos.items.length === 0 ? <p className="meta">Todavía no ha saltado ninguna alerta. Cuando una licitación cumpla una de tus alertas aparecerá aquí.</p> : (
        <ul className="lic-lista">
          {avisos.items.map((x) => (
            <li key={x.id} className={`tarjeta lic-item${x.leido ? " lic-leido" : ""}`}>
              <span className="lic-fila">
                {x.encaje != null && <span className={`lic-encaje ${encajeClase(x.encaje)}`} title="Encaje con 101.cat (0–100)">{x.encaje}</span>}
                <Link href={`/licitaciones/expedientes/${x.motor_id}`} className="titulo">{x.titulo}</Link>
                {!x.leido && <span className="lic-etiqueta abierta">Nuevo</span>}
              </span>
              <span className="meta">{[x.organismo, `Alerta «${x.alerta}»`, eventoEtiqueta(x.tipo)].filter(Boolean).join(" · ")}</span>
              {ganadoresTexto(x.detalle).map((t, i) => <span key={i} className="meta"><strong>{t}</strong></span>)}
              <span className="lic-fila">
                {x.importe != null && <span className="meta">{importeTexto({ valor: String(x.importe), moneda: "EUR", impuestos: "sin_iva" })}</span>}
                {x.fecha_limite && <span className="meta">Plazo: {fechaTexto(x.fecha_limite)}</span>}
                <span className="meta">Aviso: {fechaTexto(x.creado)}</span>
                {!x.leido && <button className="boton no" onClick={() => onLeer([x.id])}>Marcar como leído</button>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const FORMULARIO_VACIO = { nombre: "", q: "", cpv: "", nuts: "", importeMin: "", importeMax: "", tipo: "licitacion", competidores: "", soloNuevos: false, comprador: "", eventos: ["licitacion.nueva"], ambito: "personal", departamento: "", canal: "panel", correo: "" };

function Formulario({ onCrear, trabajando }) {
  const [f, setF] = useState(FORMULARIO_VACIO);
  const poner = (k) => (ev) => setF((x) => ({ ...x, [k]: ev.target.value }));
  const canal = canalesDe(f.ambito).some(([k]) => k === f.canal) ? f.canal : "panel";       // «resumen_diario» solo para departamentos: al pasar a «Mía» vuelve a «panel»
  const correoMal = canal === "correo" && !correoValido(f.correo);
  const competencia = f.tipo === "competencia";
  const sinCriterios = competencia && !competenciaGuardable(f);
  const alternar = (e) => setF((x) => ({ ...x, eventos: x.eventos.includes(e) ? x.eventos.filter((y) => y !== e) : [...x.eventos, e] }));
  const enviarForm = async (ev) => {
    ev.preventDefault();
    if (await onCrear({ ...f, canal })) setF(FORMULARIO_VACIO);
  };
  return (
    <form className="tarjeta lic-form" onSubmit={enviarForm}>
      <h2>Nueva alerta</h2>
      <p className="meta">Avisa cuando llegue un evento de una licitación que cumpla estos criterios. También puedes crearla desde el buscador con «Guardar como alerta».</p>
      <div className="lic-campos">
        <label>Qué vigila
          <select value={f.tipo} onChange={poner("tipo")}>{TIPOS_ALERTA.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
        </label>
        {competencia && (
          <label>Competidores (NIF)
            <input type="text" value={f.competidores} onChange={poner("competidores")} placeholder="B12345678 A08000143 (vacío = cualquiera)" />
            <span className="ayuda">{f.competidores.trim() && competidoresDeTexto(f.competidores).length === 0 ? "No reconozco ningún NIF (9 letras o cifras)" : "Sin NIF, avisa de cualquier adjudicación del mercado que elijas abajo"}</span>
          </label>
        )}
        {competencia && competidoresDeTexto(f.competidores).length === 0 && (
          <label className="lic-check">
            <input type="checkbox" checked={f.soloNuevos} onChange={(ev) => setF((x) => ({ ...x, soloNuevos: ev.target.checked }))} /> Solo empresas nuevas en el mercado
            <span className="ayuda">Avisa solo si quien gana no había ganado antes nada en ese mercado (los CPV y la zona de abajo). Solo funciona cuando el motor tiene al menos un año de histórico; si no, no avisa.</span>
          </label>
        )}
        <label>Nombre<input type="text" value={f.nombre} onChange={poner("nombre")} maxLength={120} required placeholder="Videovigilancia en Girona" /></label>
        <label>Texto<input type="text" value={f.q} onChange={poner("q")} maxLength={200} placeholder="castellano o catalán" /></label>
        <label>CPV<input type="text" value={f.cpv} onChange={poner("cpv")} placeholder="32323500 72" /></label>
        <label>Zona (NUTS)<input type="text" value={f.nuts} onChange={poner("nuts")} placeholder="ES512" /></label>
        <label>Comprador (NIF)<input type="text" value={f.comprador} onChange={poner("comprador")} placeholder="P1708500E" /></label>
        <label>Importe mínimo (€)<input type="text" inputMode="decimal" value={f.importeMin} onChange={poner("importeMin")} /></label>
        <label>Importe máximo (€)<input type="text" inputMode="decimal" value={f.importeMax} onChange={poner("importeMax")} /></label>
        <label>De quién es
          <select value={f.ambito} onChange={poner("ambito")}>
            <option value="personal">Mía (solo yo la veo)</option>
            <option value="departamento">De un departamento</option>
          </select>
        </label>
        {f.ambito === "departamento" && <label>Departamento<input type="text" value={f.departamento} onChange={poner("departamento")} placeholder="licitaciones" required /><span className="ayuda">Solo su responsable o Dirección pueden crearla</span></label>}
        <label>Dónde avisa
          <select value={canal} onChange={poner("canal")}>{canalesDe(f.ambito).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
          <span className="ayuda">{f.ambito === "departamento" ? "El resumen lo ven Dirección y Licitaciones" : "El correo solo llega a direcciones de la empresa"}</span>
        </label>
        {canal === "correo" && (
          <label>Correo de destino
            <input type="email" value={f.correo} onChange={poner("correo")} required placeholder={`nombre@${DOMINIO_CORREO}`} maxLength={254} />
            <span className="ayuda">{correoMal && f.correo ? `Tiene que ser una dirección @${DOMINIO_CORREO}` : `Solo direcciones @${DOMINIO_CORREO}; los avisos salen cada pocos minutos`}</span>
          </label>
        )}
      </div>
      {competencia && <p className="meta">Una alerta de competencia avisa solo cuando se adjudica una licitación del mercado elegido (y una sola vez por licitación). Los datos de quién gana los publica la plataforma de contratación; solo se compara por NIF.</p>}
      {!competencia && <fieldset className="lic-estados">
        <legend>Avisar de</legend>
        {EVENTOS_ALERTA.map(([k, t]) => <label key={k}><input type="checkbox" checked={f.eventos.includes(k)} onChange={() => alternar(k)} />{t}</label>)}
      </fieldset>}
      <div className="lic-fila"><button className="boton si" type="submit" disabled={trabajando || (!competencia && f.eventos.length === 0) || correoMal || sinCriterios}>{trabajando ? "Guardando…" : "Guardar alerta"}</button></div>
    </form>
  );
}

export default function Alertas() {
  const [alertas, setAlertas] = useState(null);
  const [avisos, setAvisos] = useState(null);
  const [error, setError] = useState(null);
  const [trabajando, setTrabajando] = useState(false);

  const cargar = useCallback(async () => {
    try {
      const [a, v] = await Promise.all([pedirCerebro("licitaciones/alertas"), pedirCerebro("licitaciones/avisos?limite=50")]);
      setAlertas(a); setAvisos(v);
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { cargar(); }, [cargar]);

  const accion = async (ruta, cuerpo) => {
    setError(null); setTrabajando(true);
    try { await pedirCerebro(ruta, enviar(cuerpo)); await cargar(); return true; }
    catch (e) { setError(e); return false; }
    finally { setTrabajando(false); }
  };
  const crear = async (f) => {
    const filtro = filtroDeAlerta(f);
    return accion("licitaciones/alertas", {
      nombre: f.nombre, ambito: f.ambito, departamento: f.ambito === "departamento" ? f.departamento.trim().toLowerCase() : null, filtro,
      ...(f.tipo === "competencia" ? { tipo: "competencia", competidores: competidoresDeTexto(f.competidores), solo_nuevos: Boolean(f.soloNuevos) && competidoresDeTexto(f.competidores).length === 0 } : { eventos: f.eventos }),
      canal: f.canal,
      ...(f.canal === "correo" ? { correo_destino: f.correo.trim().toLowerCase() } : {}),
    });
  };

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link></p>
      <h1>Alertas</h1>
      {error && <p role="alert" className="lic-error">{mensajeAlertas(error.status)}</p>}
      {!alertas && !error && <p className="meta" aria-busy="true">Cargando…</p>}
      {avisos && <Avisos avisos={avisos} onLeer={(ids) => accion("licitaciones/avisos/leer", ids ? { ids } : {})} />}
      {alertas && (
        <section className="lic" aria-label="Mis alertas">
          <h2>Alertas guardadas <span className="meta">· {alertas.items.length}</span></h2>
          {alertas.items.length === 0 ? <p className="meta">Aún no tienes ninguna.</p> : (
            <ul className="lic-lista">
              {alertas.items.map((a) => (
                <li key={a.id} className="tarjeta lic-item">
                  <span className="lic-fila"><span className="titulo">{a.nombre}</span>{!a.activa && <span className="lic-etiqueta">En pausa</span>}<span className="lic-etiqueta">{ambitoTexto(a)}</span>{esCompetencia(a) && <span className="lic-etiqueta aviso">Competencia</span>}</span>
                  <span className="meta">{filtroTexto(a.filtro) || "—"}</span>
                  <span className="meta">{esCompetencia(a) ? `Avisa cuando gane ${vigilaTexto(a)}` : `Avisa de: ${a.eventos.map(eventoEtiqueta).join(", ")}`}{a.ultima_entrega ? ` · último aviso ${fechaTexto(a.ultima_entrega)}` : ""}{canalDeAlertaTexto(a) ? ` · ${canalDeAlertaTexto(a)}` : ""}</span>
                  {a.puede_cambiar && (
                    <span className="lic-fila">
                      <button className="boton no" disabled={trabajando} onClick={() => accion(`licitaciones/alertas/${a.id}`, { activa: !a.activa })}>{a.activa ? "Pausar" : "Reactivar"}</button>
                      {admiteResumen(a) && <button className="boton no" disabled={trabajando} onClick={() => accion(`licitaciones/alertas/${a.id}`, { canal: a.canal === "resumen_diario" ? "panel" : "resumen_diario" })}>{a.canal === "resumen_diario" ? "Quitar del resumen" : "Incluir en el resumen"}</button>}
                      {a.canal === "correo"
                        ? <button className="boton no" disabled={trabajando} onClick={() => accion(`licitaciones/alertas/${a.id}`, { canal: "panel" })}>Dejar de avisar por correo</button>
                        : <button className="boton no" disabled={trabajando} onClick={() => { const c = window.prompt(`¿A qué dirección @${DOMINIO_CORREO} enviar los avisos?`); if (c && correoValido(c)) accion(`licitaciones/alertas/${a.id}`, { canal: "correo", correo_destino: c.trim().toLowerCase() }); else if (c) window.alert(`Tiene que ser una dirección @${DOMINIO_CORREO}`); }}>Avisar por correo</button>}
                      <button className="boton no" disabled={trabajando} onClick={() => { if (window.confirm(`¿Borrar la alerta «${a.nombre}» y sus avisos?`)) accion(`licitaciones/alertas/${a.id}/borrar`); }}>Borrar</button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {alertas && <Formulario onCrear={crear} trabajando={trabajando} />}
    </div>
  );
}
