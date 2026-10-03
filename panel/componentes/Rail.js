"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const SECCIONES = [
  { ruta: "/", nombre: "Jarvis" },
  { ruta: "/aprobaciones", nombre: "Aprobaciones" },
  { ruta: "/agentes", nombre: "Agentes" },
];

export default function Rail() {
  const ruta = usePathname();
  const [pendientes, setPendientes] = useState(0);
  useEffect(() => {
    const cargar = () => fetch("/cerebro/aprobaciones").then((r) => (r.ok ? r.json() : [])).then((l) => setPendientes(l.length)).catch(() => {});
    cargar();
    const t = setInterval(cargar, 30000);
    return () => clearInterval(t);
  }, []);
  return (
    <nav className="rail" aria-label="Secciones">
      <div className="marca">101<span>.cat</span></div>
      {SECCIONES.map((s) => (
        <Link key={s.ruta} href={s.ruta} aria-current={ruta === s.ruta ? "page" : undefined}>
          {s.nombre}
          {s.ruta === "/aprobaciones" && pendientes > 0 && <span className="contador" aria-label={`${pendientes} pendientes`}>{pendientes}</span>}
        </Link>
      ))}
    </nav>
  );
}
