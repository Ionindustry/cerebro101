"""Correo con el servidor propio: IMAP para leer y guardar borradores, SMTP para enviar.

- leer_bandeja y preparar_borrador son internas: el borrador aparece en la carpeta de
  borradores del departamento y una persona puede revisarlo en su cliente de correo.
- enviar tiene impacto externo: solo se ejecuta tras aprobación.
- Las comunicaciones comerciales llevan siempre el pie de baja (LSSI).
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import smtplib
import ssl
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import make_msgid, parsedate_to_datetime

from .base import Herramienta, registrar
from .integraciones import config, credenciales


def construir_mensaje(remitente: str, para: list[str] | str, asunto: str, cuerpo: str,
                      comercial: bool = False, pie: str = "", responder_a: str | None = None) -> EmailMessage:
    m = EmailMessage()
    m["From"] = remitente
    m["To"] = ", ".join(para) if isinstance(para, list) else para
    m["Subject"] = asunto
    m["Message-ID"] = make_msgid(domain=remitente.split("@")[-1])
    if responder_a:
        m["In-Reply-To"] = responder_a
        m["References"] = responder_a
    if comercial:
        if not pie:
            raise ValueError("Una comunicación comercial necesita el pie de baja")
        cuerpo = f"{cuerpo.rstrip()}\n\n--\n{pie}"
    m.set_content(cuerpo)
    return m


def _texto(cabecera: str | None) -> str:
    return str(make_header(decode_header(cabecera))) if cabecera else ""


def resumir_mensaje(uid: str, crudo: bytes, max_caracteres: int = 4000) -> dict:
    m = email.message_from_bytes(crudo)
    cuerpo = ""
    partes = m.walk() if m.is_multipart() else [m]
    for p in partes:
        if p.get_content_type() == "text/plain" and not p.get_filename():
            carga = p.get_payload(decode=True) or b""
            cuerpo = carga.decode(p.get_content_charset() or "utf-8", errors="replace")
            break
    try:
        fecha = parsedate_to_datetime(m["Date"]).isoformat() if m["Date"] else None
    except (TypeError, ValueError):
        fecha = None
    return {"id": uid, "de": _texto(m["From"]), "asunto": _texto(m["Subject"]), "fecha": fecha,
            "message_id": m["Message-ID"], "texto": cuerpo[:max_caracteres]}


def _imap(departamento: str) -> imaplib.IMAP4_SSL:
    c = config()["correo"]["imap"]
    usuario, clave = credenciales("CORREO", departamento)
    conexion = imaplib.IMAP4_SSL(c["host"], c["puerto"], ssl_context=ssl.create_default_context())
    conexion.login(usuario, clave)
    return conexion


def _leer(departamento: str, carpeta: str, no_leidos: bool, limite: int) -> list[dict]:
    conexion = _imap(departamento)
    try:
        conexion.select(carpeta, readonly=True)          # solo lectura: no marca nada como leído
        _, datos = conexion.uid("search", None, "UNSEEN" if no_leidos else "ALL")
        uids = datos[0].split()[-limite:]
        mensajes = []
        for uid in reversed(uids):
            _, partes = conexion.uid("fetch", uid, "(BODY.PEEK[])")
            mensajes.append(resumir_mensaje(uid.decode(), partes[0][1]))
        return mensajes
    finally:
        conexion.logout()


def _guardar_borrador(departamento: str, mensaje: EmailMessage) -> str:
    conexion = _imap(departamento)
    try:
        carpeta = config()["correo"]["carpeta_borradores"]
        conexion.append(carpeta, "\\Draft", imaplib.Time2Internaldate(time.time()), mensaje.as_bytes())
        return mensaje["Message-ID"]
    finally:
        conexion.logout()


def _enviar(departamento: str, mensaje: EmailMessage) -> str:
    c = config()["correo"]["smtp"]
    usuario, clave = credenciales("CORREO", departamento)
    with smtplib.SMTP(c["host"], c["puerto"], timeout=60) as s:
        if c.get("starttls", True):
            s.starttls(context=ssl.create_default_context())
        s.login(usuario, clave)
        s.send_message(mensaje)
    return mensaje["Message-ID"]


async def leer_bandeja(departamento: str, carpeta: str = "INBOX", no_leidos: bool = True, limite: int = 20) -> list[dict]:
    return await asyncio.to_thread(_leer, departamento, carpeta, no_leidos, limite)


async def preparar_borrador(departamento: str, para: list[str] | str, asunto: str, cuerpo: str,
                            comercial: bool = False, responder_a: str | None = None) -> dict:
    usuario, _ = credenciales("CORREO", departamento)
    m = construir_mensaje(usuario, para, asunto, cuerpo, comercial, config()["correo"]["pie_comercial"], responder_a)
    return {"borrador": await asyncio.to_thread(_guardar_borrador, departamento, m)}


async def enviar(departamento: str, para: list[str] | str, asunto: str, cuerpo: str,
                 comercial: bool = False, responder_a: str | None = None) -> dict:
    usuario, _ = credenciales("CORREO", departamento)
    m = construir_mensaje(usuario, para, asunto, cuerpo, comercial, config()["correo"]["pie_comercial"], responder_a)
    return {"enviado": await asyncio.to_thread(_enviar, departamento, m)}


registrar(Herramienta(
    nombre="correo",
    descripcion="Correo de la empresa (servidor propio). Marca comercial=true en cualquier mensaje promocional.",
    operaciones={"leer_bandeja": leer_bandeja, "preparar_borrador": preparar_borrador, "enviar": enviar},
    externas=frozenset({"enviar"}),
    ayuda={"leer_bandeja": "lee los correos (solo lectura; no los marca como leídos)",
           "preparar_borrador": "guarda un borrador en la carpeta de borradores; no envía nada",
           "enviar": "envía el correo"},
    ejemplos={"leer_bandeja": {"no_leidos": True, "limite": 10}},
))
