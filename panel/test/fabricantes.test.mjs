import test from "node:test";
import assert from "node:assert/strict";
import { comandoAutorizarRanking, estadoDominio, ventasTexto } from "../lib/fabricantes.js";

test("ventasTexto distingue «sin dato» de cero", () => {
  assert.equal(ventasTexto(null), "sin dato");
  assert.equal(ventasTexto(""), "sin dato");
  assert.match(ventasTexto(0), /^0,0 M USD$/);
  assert.match(ventasTexto(420.9).replace(/\s/g, " "), /^420,9 M USD$/);
});

test("estadoDominio y comando de autorizar", () => {
  assert.equal(estadoDominio({ autorizado: true, dominio: "a.com" }), "autorizado");
  assert.equal(estadoDominio({ comprobado: true, dominio: "a.com" }), "comprobado: falta autorizar");
  assert.equal(estadoDominio({ en_directorio: true, dominio: "a.com" }), "en el directorio, sin comprobar");
  assert.equal(estadoDominio({ dominio: "a.com" }), "no está en el directorio");
  assert.equal(estadoDominio({ dominio: "" }), "sin web");
  const s = [{ fabricantes: [{ dominio: "a.com", comprobado: true }, { dominio: "b.com", comprobado: true, autorizado: true }, { dominio: "a.com", comprobado: true }, { dominio: "c.com" }] }];
  assert.equal(comandoAutorizarRanking(s), "python3 scripts/fichas_autorizar.py a.com");
  assert.equal(comandoAutorizarRanking([]), "");
});
