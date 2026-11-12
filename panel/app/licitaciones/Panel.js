"use client";
import { useEffect, useMemo, useState } from "react";
import { Barras, Calendario, Cifra } from "./buscar/Dashboard";
import { Fallo, pedir, pedirCerebro } from "./cliente";
import { divisionEtiqueta, embudoGrupos, etiquetaEmbudo, fuentesGrupos, hoyMadrid, importeCorto, nombreFuente, plazosProximos, tasaExitoTexto, zonaEtiqueta } from "../../lib/licitaciones";

const n = (v) => new Intl.NumberFormat("es-ES").format(v ?? 0);

/** Panel de control de Licitaciones: lo abierto ahora (plazos, importe, sectores, zonas, organismos), el embudo propio y las fuentes del motor. Solo lee. */
export default function Panel() {
  const [st, setSt] = useState(null);
  const [error, setError] = useState(null);
  const [emb, setEmb] = useState(null);
  const [motor, setMotor] = useState(null);
  useEffect(() => {
    pedir("tenders/estadisticas?estado=abierta&estado=anuncio_previo").then(setSt).catch(setError);
    pedirCerebro("licitaciones/embudo/resumen?dias=30").then(setEmb).catch(() => setEmb(null));
    pedir("ops/status").then(setMotor).catch(() => setMotor(null));
  }, []);
  const prox = useMemo(() => (st ? plazosProximos(st.plazos, hoyMadrid()) : null), [st]);
  return (
    <section className="lic" aria-labelledby="lic-panel-t">
      <h2 id="lic-panel-t">Panel de control</h2>
      {error && <Fallo e={error} />}
      {!st && !error && <p className="meta" aria-busy="true">Calculando el panel…</p>}
      {st && (
        <>
          <div className="lic-cifras">
            <Cifra titulo="Abiertas ahora" valor={n(st.total)} nota="con plazo de presentación abierto" />
            <Cifra titulo="Vencen en 7 días" valor={n(prox.siete)} nota={`${n(prox.quince)} en 15 · ${n(prox.treinta)} en 30`} />
            <Cifra titulo="Importe en juego" valor={importeCorto(st.importe?.total)} nota="valor estimado sin IVA" />
            <Cifra titulo="Importe medio" valor={importeCorto(st.importe?.medio)} />
            {emb && <Cifra titulo="Tasa de éxito (30 d)" valor={emb.tasa_exito?.valor == null ? "—" : `${Math.round(emb.tasa_exito.valor * 100)} %`} nota={tasaExitoTexto(emb.tasa_exito)} />}
          </div>
          <Calendario plazos={st.plazos} />
          <div className="lic-graficos">
            {emb && <Barras titulo="Embudo propio" grupos={embudoGrupos(emb)} etiqueta={etiquetaEmbudo} vacio="Todavía no hay licitaciones en el embudo" />}
            <Barras titulo="Por sector (CPV)" grupos={st.cpv} etiqueta={divisionEtiqueta} />
            <Barras titulo="Por zona" grupos={st.zonas} etiqueta={zonaEtiqueta} />
            <Barras titulo="Principales organismos" grupos={st.compradores} mostrarImporte vacio="Sin organismos" />
            {motor && <Barras titulo="Expedientes por fuente" grupos={fuentesGrupos(motor)} etiqueta={nombreFuente} vacio="Todavía no hay fuentes ingeridas" />}
          </div>
        </>
      )}
    </section>
  );
}
