"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { textoVersion } from "../lib/version";

const SECCIONES = [
  { ruta: "/", nombre: "ARES" },
  { ruta: "/hoy", nombre: "Hoy" },
  { ruta: "/oficina", nombre: "Oficina" },
  { ruta: "/licitaciones", nombre: "Licitaciones" },
  { ruta: "/aprobaciones", nombre: "Aprobaciones" },
  { ruta: "/precios", nombre: "Precios" },
  { ruta: "/cotizaciones", nombre: "Cotizaciones" },
  { ruta: "/ventas", nombre: "Ventas" },
  { ruta: "/agentes", nombre: "Agentes" },
];

export default function Rail({ version }) {
  const ruta = usePathname();
  const [pendientes, setPendientes] = useState(0);
  const [urgentes, setUrgentes] = useState(0);
  const [usuario, setUsuario] = useState("");
  const [versionApi, setVersionApi] = useState(null);
  useEffect(() => {
    fetch("/auth/yo").then((r) => (r.ok ? r.json() : null)).then((d) => d && setUsuario(d.usuario)).catch(() => {});
  }, []);
  useEffect(() => {
    fetch("/cerebro/salud").then((r) => (r.ok ? r.json() : null)).then((d) => d && setVersionApi(d.version ?? null)).catch(() => {});
  }, []);
  useEffect(() => {
    const cargar = () => fetch("/cerebro/aprobaciones")
      .then((r) => { if (r.status === 401) { window.location.href = "/auth/login"; return []; } return r.ok ? r.json() : []; })
      .then((l) => setPendientes(l.length)).catch(() => {});
    cargar();
    const t = setInterval(cargar, 30000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const cargar = () => fetch("/cerebro/hoy").then((r) => (r.ok ? r.json() : null)).then((d) => d && setUrgentes(d.urgentes || 0)).catch(() => {});
    cargar();
    const t = setInterval(cargar, 60000);
    return () => clearInterval(t);
  }, []);
  return (
    <nav className="rail" aria-label="Secciones">
      <div className="marca">101<span>.cat</span></div>
      {SECCIONES.map((s) => (
        <Link key={s.ruta} href={s.ruta} aria-current={ruta === s.ruta || (s.ruta !== "/" && ruta.startsWith(s.ruta + "/")) ? "page" : undefined}>
          {s.nombre}
          {s.ruta === "/hoy" && urgentes > 0 && <span className="contador" aria-label={`${urgentes} urgentes`}>{urgentes}</span>}
          {s.ruta === "/aprobaciones" && pendientes > 0 && <span className="contador" aria-label={`${pendientes} pendientes`}>{pendientes}</span>}
        </Link>
      ))}
      <small className="version" title={textoVersion(version, versionApi).aviso || "Versión del código en uso"}>{textoVersion(version, versionApi).texto}{textoVersion(version, versionApi).aviso && " ⚠"}</small>
      {usuario && (
        <div className="sesion">
          <span>{usuario}</span>
          <a href="/auth/logout">Salir</a>
        </div>
      )}
    </nav>
  );
}
