"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { accionEmbudo, avisoEstadoMotor, hayPeticionEnCurso, peticionViabilidad, puedePedirViabilidad, textoPedirViabilidad, viabilidadEtiqueta, diasDePeriodo, encajeClase, ESTADOS_EMBUDO, etiquetaEmbudo, fechaTexto, horasTexto, importeTexto, mensajeEmbudo, PERIODOS_EMBUDO, tasaExitoTexto } from "../../../lib/licitaciones";
import { pedirCerebro } from "../cliente";

const enviar = (cuerpo) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

function Cifra({ t, children }) {
  return <div className="lic-cifra"><span className="meta">{t}</span><strong>{children}</strong></div>;
}

function Resumen({ r }) {
  return (
    <section className="tarjeta" aria-label="Resumen del embudo">
      <div className="lic-cifras">
        {ESTADOS_EMBUDO.map(([k, nombre]) => <Cifra key={k} t={nombre}>{r.por_estado[k] ?? 0}</Cifra>)}
      </div>
      <p className="meta">En el periodo: {r.en_periodo.detectadas} detectadas · {r.en_periodo.presentadas} presentadas · {r.en_periodo.ganadas} ganadas · {r.en_periodo.perdidas} perdidas · {r.en_periodo.descartadas} descartadas</p>
      <dl className="lic-ficha">
        <div><dt>Tasa de éxito</dt><dd>{tasaExitoTexto(r.tasa_exito)}</dd></div>
        <div><dt>Horas hasta decidir ir o no ir (mediana)</dt><dd>{horasTexto(r.horas_hasta_decision_p50)}</dd></div>
        <div><dt>Motivos de pérdida</dt><dd>{r.motivos_perdida.length === 0 ? "—" : r.motivos_perdida.map((m) => `${m.etiqueta} (${m.total})`).join(" · ")}</dd></div>
      </dl>
    </section>
  );
}

function Fila({ x, transiciones, motivos, onCambio, onViabilidad }) {
  const [motivo, setMotivo] = useState("");
  const [pidiendoMotivo, setPidiendoMotivo] = useState(false);
  const [trabajando, setTrabajando] = useState(false);
  const cambiar = async (estado) => {
    if (estado === "perdida" && !pidiendoMotivo) { setPidiendoMotivo(true); return; }
    setTrabajando(true);
    try { await onCambio(x.id, estado, estado === "perdida" ? motivo : null); setPidiendoMotivo(false); setMotivo(""); }
    finally { setTrabajando(false); }
  };
  const destinos = transiciones[x.estado] || [];
  const peticion = peticionViabilidad(x);
  const pedir = async () => {
    if (x.viabilidad && !window.confirm("Ya hay un informe de viabilidad. ¿Pedir otro y sustituir el anterior?")) return;
    setTrabajando(true);
    try { await onViabilidad(x.id, Boolean(x.viabilidad)); }
    finally { setTrabajando(false); }
  };
  return (
    <li className="tarjeta lic-item">
      <span className="lic-fila">
        <span className={`lic-encaje ${encajeClase(x.encaje)}`} title="Encaje con 101.cat (0–100)">{x.encaje ?? "—"}</span>
        {x.motor_id ? <Link href={`/licitaciones/expedientes/${x.motor_id}`} className="titulo">{x.titulo}</Link> : <span className="titulo">{x.titulo}</span>}
      </span>
      <span className="meta">{[x.organismo, x.expediente].filter(Boolean).join(" · ")}</span>
      <span className="lic-fila">
        {x.importe != null && <span className="meta">{importeTexto({ valor: String(x.importe), moneda: "EUR", impuestos: "sin_iva" })}</span>}
        {x.fecha_limite && <span className="meta">Plazo: {fechaTexto(x.fecha_limite)}</span>}
        {x.motivo_perdida_texto && <span className="lic-etiqueta">{x.motivo_perdida_texto}</span>}
        {avisoEstadoMotor(x.estado_motor) && <span className="lic-etiqueta aviso">{avisoEstadoMotor(x.estado_motor)}</span>}
        {viabilidadEtiqueta(x.viabilidad) && <span className={`lic-etiqueta ${viabilidadEtiqueta(x.viabilidad).clase}`}>{viabilidadEtiqueta(x.viabilidad).texto}</span>}
      </span>
      {x.viabilidad?.informe && (
        <details className="lic-informe">
          <summary>Ver el informe de Viabilidad{x.viabilidad.motivo ? ` · ${x.viabilidad.motivo}` : ""}</summary>
          <p className="meta">Lo ha escrito un agente de IA el {fechaTexto(x.viabilidad.generado)} como ayuda: puede equivocarse y no decide nada. Ir o no ir lo decide una persona.</p>
          <pre className="lic-informe-texto">{x.viabilidad.informe}</pre>
        </details>
      )}
      {(puedePedirViabilidad(x) || peticion) && (
        <span className="lic-fila">
          {peticion?.estado === "en_curso" && <span className="meta" role="status" aria-busy="true">Viabilidad está preparando el informe… puede tardar unos minutos.</span>}
          {peticion?.estado === "error" && <span className="lic-etiqueta aviso" role="alert">{peticion.error}</span>}
          {puedePedirViabilidad(x) && <button className="boton no" disabled={trabajando} onClick={pedir}>{textoPedirViabilidad(x)}</button>}
        </span>
      )}
      {destinos.length > 0 && (
        <span className="lic-fila">
          {pidiendoMotivo ? (
            <>
              <select value={motivo} onChange={(e) => setMotivo(e.target.value)} aria-label="Motivo de la pérdida">
                <option value="">Motivo de la pérdida…</option>
                {Object.entries(motivos).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select>
              <button className="boton no" disabled={!motivo || trabajando} onClick={() => cambiar("perdida")}>Confirmar</button>
              <button className="boton no" disabled={trabajando} onClick={() => setPidiendoMotivo(false)}>Cancelar</button>
            </>
          ) : destinos.map((d) => <button key={d} className="boton no" disabled={trabajando} onClick={() => cambiar(d)}>{accionEmbudo(x.estado, d)}</button>)}
        </span>
      )}
    </li>
  );
}

export default function Embudo() {
  const [periodo, setPeriodo] = useState("30d");
  const [resumen, setResumen] = useState(null);
  const [lista, setLista] = useState(null);
  const [error, setError] = useState(null);

  const cargar = useCallback(async () => {
    setError(null);
    try {
      const [r, l] = await Promise.all([pedirCerebro(`licitaciones/embudo/resumen?dias=${diasDePeriodo(periodo)}`), pedirCerebro("licitaciones/embudo")]);
      setResumen(r); setLista(l);
    } catch (e) { setError(e); }
  }, [periodo]);
  useEffect(() => { cargar(); }, [cargar]);

  const cambiar = async (id, estado, motivo) => {
    setError(null);
    try { await pedirCerebro(`licitaciones/embudo/${id}/estado`, enviar({ estado, motivo_perdida: motivo })); await cargar(); }
    catch (e) { setError(e); }
  };

  const pedirViabilidad = async (id, reemplazar) => {
    setError(null);
    try { await pedirCerebro(`licitaciones/embudo/${id}/viabilidad`, enviar({ reemplazar })); await cargar(); }
    catch (e) { setError(e); }
  };

  // Mientras Viabilidad prepara un informe, la lista se refresca sola hasta que aparece (o falla).
  const esperando = hayPeticionEnCurso(lista?.items);
  useEffect(() => {
    if (!esperando) return undefined;
    const t = setInterval(cargar, 8000);
    return () => clearInterval(t);
  }, [esperando, cargar]);

  return (
    <div className="lic">
      <p className="lic-vuelve"><Link href="/licitaciones">← Licitaciones</Link></p>
      <div className="lic-fila">
        <h1>Embudo de licitaciones</h1>
        <select value={periodo} onChange={(e) => setPeriodo(e.target.value)} aria-label="Periodo">
          {PERIODOS_EMBUDO.map(([k, , t]) => <option key={k} value={k}>{t}</option>)}
        </select>
      </div>
      <p className="meta">Lo que 101.cat estudia, presenta, gana o pierde. Las cifras las calcula el panel, no la IA; presentarse y firmar siguen siendo decisiones de una persona.</p>
      {error && <p role="alert" className="lic-error">{mensajeEmbudo(error.status)}</p>}
      {!resumen && !error && <p className="meta" aria-busy="true">Cargando…</p>}
      {resumen && <Resumen r={resumen} />}
      {lista && ESTADOS_EMBUDO.map(([k]) => {
        const items = lista.items.filter((x) => x.estado === k);
        return (
          <section key={k} className="lic" aria-label={etiquetaEmbudo(k)}>
            <h2>{etiquetaEmbudo(k)} <span className="meta">· {items.length}</span></h2>
            {items.length === 0 ? <p className="meta">Ninguna.</p> : <ul className="lic-lista">{items.map((x) => <Fila key={x.id} x={x} transiciones={lista.transiciones} motivos={lista.motivos_perdida} onCambio={cambiar} onViabilidad={pedirViabilidad} />)}</ul>}
          </section>
        );
      })}
    </div>
  );
}
