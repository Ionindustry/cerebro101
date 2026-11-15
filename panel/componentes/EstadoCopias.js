"use client";
import { useCallback, useEffect, useState } from "react";
import { ajustesAEnvio, ajustesAFormulario, copiasResumen, resumenAjustesCopias } from "../lib/copias";

// La tarjeta «Copias de seguridad»: última copia (fecha, tamaño, si salió bien), si la restauración se ha probado y si hay que preocuparse (más de 3 días sin una buena).
// Los datos los anota el servidor al hacer la copia (scripts/copia_automatica.sh). Dirección ve además el botón «Configurar»: cuántas copias se conservan, una segunda ubicación y a los cuántos días se avisa.
export default function EstadoCopias() {
  const [e, setE] = useState(null);
  const [abierto, setAbierto] = useState(false);
  const [aj, setAj] = useState(null);            // ajustes del servidor (null = no se pueden ver: no es Dirección)
  const [form, setForm] = useState(null);        // el formulario abierto
  const [msg, setMsg] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const cargar = useCallback(() => fetch("/cerebro/salud/copias").then((r) => (r.ok ? r.json() : null)).then((d) => d && setE(d)).catch(() => {}), []);
  const cargarAjustes = useCallback(() => fetch("/cerebro/salud/copias/ajustes").then((r) => (r.ok ? r.json() : null)).then((d) => setAj(d)).catch(() => setAj(null)), []);
  useEffect(() => { cargar(); const t = setInterval(cargar, 300000); return () => clearInterval(t); }, [cargar]);
  useEffect(() => { if (abierto) cargarAjustes(); }, [abierto, cargarAjustes]);
  if (!e) return null;
  const r = copiasResumen(e);
  const color = { bien: "#2e7d4f", aviso: "#c98a0b", mal: "#b3261e" }[r.nivel];

  const guardar = async () => {
    const { cuerpo, error } = ajustesAEnvio(form);
    if (error) { setMsg({ mal: true, texto: error }); return; }
    setOcupado(true); setMsg(null);
    try {
      const res = await fetch("/cerebro/salud/copias/ajustes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) { setMsg({ mal: true, texto: typeof d.detail === "string" ? d.detail : "No se han podido guardar los ajustes." }); return; }
      setAj(d); setForm(null); setMsg({ mal: false, texto: "Guardado. Se aplica en la próxima copia (la de las 14:00)." }); cargar();
    } catch { setMsg({ mal: true, texto: "No se han podido guardar los ajustes. Inténtalo de nuevo." }); } finally { setOcupado(false); }
  };
  const campo = (clave, etiqueta, ayuda, props = {}) => (
    <label style={{ display: "block", marginBottom: 8 }}>{etiqueta}
      <input value={form[clave]} onChange={(ev) => setForm((f) => ({ ...f, [clave]: ev.target.value }))} disabled={ocupado} {...props} />
      <span className="ayuda" style={{ display: "block" }}>{ayuda}</span>
    </label>
  );
  const dias = aj?.valores?.dias_aviso ?? e.dias_limite;
  return (
    <div className="jev">
      <button className="jev-chip" aria-expanded={abierto} onClick={() => setAbierto((v) => !v)}>
        <i style={{ background: color }} aria-hidden="true" /> Copias de seguridad: <b>{r.titulo}</b>
      </button>
      {abierto && (
        <div className="jev-panel" role="region" aria-label="Estado de las copias de seguridad">
          <ul>{r.lineas.map((l) => <li key={l}><div>{l}</div></li>)}</ul>
          <p className="meta">Las hace el servidor cada día a las 14:00 (tarea de Windows «Cerebro - copia»){aj ? ` y se conservan las ${aj.valores.conservar} últimas` : ""}. Si pasan más de {dias} días sin una correcta, se avisa por correo a soporte@.</p>
          {r.ayuda && <p className="jev-ayuda">{r.ayuda}</p>}
          {msg && <p role={msg.mal ? "alert" : "status"} className={msg.mal ? "lic-error" : "aviso"}>{msg.texto}</p>}
          {aj && !form && <button className="boton no" onClick={() => { setForm(ajustesAFormulario(aj)); setMsg(null); }}>Configurar</button>}
          {aj && form && (
            <div aria-label="Configuración de las copias">
              <h3>Configurar las copias</h3>
              {campo("conservar", "Copias que se conservan en el servidor", "Entre 1 y 60. Las más antiguas se borran al hacer una nueva.", { inputMode: "numeric", size: 4 })}
              {campo("extra", "Segunda ubicación (otro disco, USB o unidad de red)", "Una carpeta que vea el servidor, por ejemplo /mnt/d/Copias101. Déjala vacía si no quieres segunda copia. Una copia en el mismo disco no te salva de que el disco falle.", { placeholder: "/mnt/d/Copias101", size: 40 })}
              {campo("conservar_extra", "Copias que se conservan en la segunda ubicación", "0 = no se borra nunca (crece sin parar). Si no, las últimas N.", { inputMode: "numeric", size: 4 })}
              {campo("dias_aviso", "Avisar a soporte@ si pasan estos días sin una copia correcta", "Entre 1 y 14.", { inputMode: "numeric", size: 4 })}
              <p className="meta">{resumenAjustesCopias(form)}</p>
              <div className="lic-fila">
                <button className="boton si" disabled={ocupado} onClick={guardar}>Guardar</button>
                <button className="boton no" disabled={ocupado} onClick={() => { setForm(null); setMsg(null); }}>Cancelar</button>
              </div>
              <p className="meta">La hora (14:00) no se cambia desde aquí: es la tarea de Windows «Cerebro - copia».</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
