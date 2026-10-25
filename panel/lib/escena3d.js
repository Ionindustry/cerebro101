// Oficina 3D con three.js: luz y sombras suaves, grises claros, agentes como cápsulas negras y coral como señal de actividad.
// Solo se carga en el navegador. El estado de los agentes se actualiza con `actualizar()` sin reconstruir la escena.
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { COLOR, SALA, distribucion } from "./oficina.js";

const ALTO_MURO = 1.5;
const DIR_CAMARA = new THREE.Vector3(1, 0.8, 1).normalize();       // vista isométrica desde el frente-derecha
const c = (hex) => new THREE.Color(hex);

export function crearOficina({ contenedor, departamentos, alSeleccionarAgente, alSeleccionarSala, alPasarPor }) {
  const dist = distribucion(departamentos);
  const ancho = () => contenedor.clientWidth || 800, alto = () => contenedor.clientHeight || 500;

  // --- Render ---------------------------------------------------------------------------------------------------------------------
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(ancho(), alto());
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.04;
  renderer.domElement.style.cssText = "display:block;width:100%;height:100%;touch-action:none";
  contenedor.appendChild(renderer.domElement);

  const escena = new THREE.Scene();
  escena.background = c(COLOR.fondo);
  escena.fog = new THREE.Fog(COLOR.fondo, 95, 230);

  const camara = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 400);
  const centro = new THREE.Vector3(dist.centro.x, 0, dist.centro.z);
  camara.position.copy(centro).addScaledVector(DIR_CAMARA, 120);

  const controles = new OrbitControls(camara, renderer.domElement);
  controles.target.copy(centro);
  controles.enableDamping = true;
  controles.dampingFactor = 0.09;
  controles.screenSpacePanning = true;
  controles.minPolarAngle = THREE.MathUtils.degToRad(28);
  controles.maxPolarAngle = THREE.MathUtils.degToRad(68);
  controles.minAzimuthAngle = Math.PI / 4 - THREE.MathUtils.degToRad(55);
  controles.maxAzimuthAngle = Math.PI / 4 + THREE.MathUtils.degToRad(55);
  controles.minZoom = 0.5;
  controles.maxZoom = 40;
  controles.zoomSpeed = 0.9;

  // --- Luz ------------------------------------------------------------------------------------------------------------------------
  escena.add(new THREE.HemisphereLight(0xffffff, 0xd9d9e0, 1.15));
  const sol = new THREE.DirectionalLight(0xffffff, 2.3);
  sol.position.set(centro.x - 40, 70, centro.z + 34);
  sol.target.position.copy(centro);
  sol.castShadow = true;
  const radio = Math.max(dist.ancho, dist.fondo) * 0.78;
  Object.assign(sol.shadow.camera, { left: -radio, right: radio, top: radio, bottom: -radio, near: 10, far: 220 });
  sol.shadow.mapSize.set(4096, 4096);
  sol.shadow.bias = -0.0004;
  sol.shadow.normalBias = 0.04;
  sol.shadow.radius = 5;
  escena.add(sol, sol.target);

  // --- Materiales -----------------------------------------------------------------------------------------------------------------
  const mat = {
    suelo: new THREE.MeshStandardMaterial({ color: COLOR.suelo, roughness: 0.95 }),
    borde: new THREE.MeshStandardMaterial({ color: "#d4d4d9", roughness: 0.95 }),
    sala: new THREE.MeshStandardMaterial({ color: COLOR.sala, roughness: 0.92 }),
    blanco: new THREE.MeshStandardMaterial({ color: COLOR.blanco, roughness: 0.85 }),
    mesa: new THREE.MeshStandardMaterial({ color: COLOR.mesa, roughness: 0.7 }),
    gris: new THREE.MeshStandardMaterial({ color: "#c9c9cf", roughness: 0.8 }),
    oscuro: new THREE.MeshStandardMaterial({ color: "#26262b", roughness: 0.6 }),
    agente: new THREE.MeshPhysicalMaterial({ color: COLOR.tinta, roughness: 0.34, metalness: 0.05, clearcoat: 0.9, clearcoatRoughness: 0.2 }),
    arbol: new THREE.MeshStandardMaterial({ color: COLOR.arbol, roughness: 0.95, flatShading: true }),
    tronco: new THREE.MeshStandardMaterial({ color: "#bdbdc4", roughness: 0.9 }),
    linea: new THREE.LineBasicMaterial({ color: COLOR.linea }),
    lineaSel: new THREE.LineBasicMaterial({ color: COLOR.senal }),
  };
  const sombrea = (m, emite = true, recibe = true) => { m.castShadow = emite; m.receiveShadow = recibe; return m; };
  const poner = (geo, material, x, y, z, { emite = true, recibe = true } = {}) => {
    const m = sombrea(new THREE.Mesh(geo, material), emite, recibe);
    m.position.set(x, y, z);
    m.matrixAutoUpdate = false;
    m.updateMatrix();
    escena.add(m);
    return m;
  };

  // --- Suelo y salas ---------------------------------------------------------------------------------------------------------------
  const margen = 3.2, espesor = 1.4;
  poner(new RoundedBoxGeometry(dist.ancho + margen * 2, espesor, dist.fondo + margen * 2, 4, 0.45), mat.suelo, dist.centro.x, -espesor / 2, dist.centro.z, { emite: false });
  const lineasSala = new Map();
  const carteles = new Map();                                     // id de sala → { mesh, ctx, tex, nombre, n, sel }
  const ANCHO_CARTEL = SALA - 0.6, CW = 2048, CH = 240;

  // El nombre del departamento va escrito en su pared del fondo: se redibuja cuando cambia el número de agentes trabajando o la sala elegida
  function dibujarCartel(c) {
    const g = c.ctx;
    g.clearRect(0, 0, CW, CH);
    g.textBaseline = "middle";
    g.fillStyle = c.n ? COLOR.senal : "#bdbdc4";
    g.beginPath(); g.arc(78, CH / 2, 22, 0, Math.PI * 2); g.fill();
    let px = 132;
    const info = c.n ? `${c.n} trabajando` : "";
    g.font = "600 70px system-ui, 'Segoe UI', Roboto, sans-serif";
    const anchoInfo = info ? g.measureText(info).width + 70 : 0;
    let tam = 132;
    g.font = `700 ${tam}px system-ui, 'Segoe UI', Roboto, sans-serif`;
    const texto = c.nombre.toUpperCase();
    while (g.measureText(texto).width > CW - px - anchoInfo - 40 && tam > 60) { tam -= 4; g.font = `700 ${tam}px system-ui, 'Segoe UI', Roboto, sans-serif`; }
    g.fillStyle = "#16161a";
    g.fillText(texto, px, CH / 2 + 4);
    if (info) {
      g.font = "600 70px system-ui, 'Segoe UI', Roboto, sans-serif";
      g.fillStyle = COLOR.senal; g.textAlign = "right";
      g.fillText(info, CW - 50, CH / 2 + 4); g.textAlign = "left";
    }
    if (c.sel) { g.fillStyle = COLOR.senal; g.fillRect(40, CH - 22, CW - 80, 10); }
    c.tex.needsUpdate = true;
  }
  function crearCartel(sala, x, y, z) {
    const canvas = document.createElement("canvas");
    canvas.width = CW; canvas.height = CH;
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(ANCHO_CARTEL, ANCHO_CARTEL * CH / CW), new THREE.MeshBasicMaterial({ map: tex, transparent: true, toneMapped: false }));
    mesh.position.set(x, y, z);
    mesh.matrixAutoUpdate = false; mesh.updateMatrix();
    mesh.userData.sala = sala.id;
    escena.add(mesh);
    const c = { mesh, ctx: canvas.getContext("2d"), tex, nombre: sala.nombre, n: 0, sel: false };
    dibujarCartel(c);
    carteles.set(sala.id, c);
  }
  for (const s of dist.salas) {
    const placa = poner(new THREE.BoxGeometry(SALA, 0.14, SALA), mat.sala, s.x + SALA / 2, 0.07, s.z + SALA / 2, { emite: false });
    placa.userData.sala = s.id;
    const borde = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(SALA, 0.14, SALA)), mat.linea);
    borde.position.copy(placa.position);
    escena.add(borde);
    lineasSala.set(s.id, borde);
    // muros bajos al fondo (los dos lados lejanos), con hueco de puerta
    const g = 0.24;
    const tramo = (x0, z0, w, d) => poner(new RoundedBoxGeometry(w, ALTO_MURO, d, 2, 0.05), mat.blanco, s.x + x0 + w / 2, ALTO_MURO / 2 + 0.14, s.z + z0 + d / 2);
    tramo(0, 0, SALA, g);                                       // pared del fondo, entera: lleva el nombre del departamento
    crearCartel(s, s.x + SALA / 2, 0.14 + ALTO_MURO * 0.52, s.z + g + 0.01);
    tramo(0, 0, g, SALA * 0.44); tramo(0, SALA * 0.56, g, SALA * 0.44);
  }

  // --- Árboles (jardines y bordes), como los del render ----------------------------------------------------------------------------
  const arbol = (x, z, r) => {
    poner(new THREE.CylinderGeometry(r * 0.1, r * 0.14, r * 0.9, 8), mat.tronco, x, r * 0.45, z, { recibe: false });
    poner(new THREE.IcosahedronGeometry(r, 1), mat.arbol, x, r * 1.55, z);
  };
  for (const j of dist.jardines) {
    for (const [dx, dz, r] of [[2.0, 2.2, 1.05], [6.0, 1.9, 1.35], [3.8, 5.8, 1.15], [7.0, 6.6, 0.9], [1.5, 6.9, 0.85]]) arbol(j.x + dx, j.z + dz, r);
  }
  for (let k = 0; k < 9; k++) arbol(-1.9, k * 4.7 + 1.5, 0.7 + (k % 3) * 0.12);
  for (let k = 0; k < 8; k++) arbol(k * 5.6 + 2, -1.9, 0.65 + (k % 2) * 0.2);

  // --- Mesas y agentes -------------------------------------------------------------------------------------------------------------
  const geoCapsula = new THREE.CapsuleGeometry(0.2, 0.62, 10, 20);
  const geoAnillo = new THREE.TorusGeometry(0.34, 0.035, 8, 40);
  const geoPunto = new THREE.SphereGeometry(0.1, 16, 12);
  const geoBanda = new THREE.TorusGeometry(0.205, 0.028, 8, 28);
  const geoPantalla = new THREE.PlaneGeometry(0.5, 0.3);
  const agentes = new Map();
  const dianas = [];

  for (const a of dist.agentes) {
    const { x, z } = a.mesa;
    // mesa: tablero con esquinas redondeadas, dos paneles laterales, monitor y teclado (sin silla: el agente ocupa su sitio)
    poner(new RoundedBoxGeometry(1.3, 0.07, 0.66, 2, 0.025), mat.mesa, x + 0.65, 0.78, z + 0.33);
    poner(new THREE.BoxGeometry(0.05, 0.64, 0.58), mat.gris, x + 0.1, 0.46, z + 0.33);
    poner(new THREE.BoxGeometry(0.05, 0.64, 0.58), mat.gris, x + 1.2, 0.46, z + 0.33);
    poner(new THREE.CylinderGeometry(0.035, 0.05, 0.2, 10), mat.oscuro, x + 0.65, 0.92, z + 0.2);
    poner(new RoundedBoxGeometry(0.56, 0.34, 0.035, 2, 0.012), mat.oscuro, x + 0.65, 1.14, z + 0.2);
    const pantalla = new THREE.Mesh(geoPantalla, new THREE.MeshStandardMaterial({ color: "#1d1d21", emissive: "#000", roughness: 0.4 }));
    pantalla.position.set(x + 0.65, 1.14, z + 0.2 + 0.0195);
    pantalla.matrixAutoUpdate = false; pantalla.updateMatrix();
    escena.add(pantalla);
    poner(new RoundedBoxGeometry(0.4, 0.02, 0.13, 1, 0.008), mat.gris, x + 0.65, 0.83, z + 0.45);

    // agente: cápsula negra de pie delante de su mesa, en el puesto de la silla
    const grupo = new THREE.Group();
    grupo.position.set(a.pos.x, 0.14, a.pos.z);
    const escala = a.director ? 1.22 : 1;
    const cuerpo = sombrea(new THREE.Mesh(geoCapsula, mat.agente));
    cuerpo.position.y = 0.51 * escala;
    cuerpo.scale.y = escala;
    cuerpo.userData.agente = a.id;
    grupo.add(cuerpo);
    dianas.push(cuerpo);
    if (a.director) {
      const banda = new THREE.Mesh(geoBanda, new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.5 }));
      banda.rotation.x = Math.PI / 2; banda.position.y = 0.66 * escala;
      grupo.add(banda);
    }
    const punto = new THREE.Mesh(geoPunto, new THREE.MeshStandardMaterial({ color: COLOR.senal, emissive: COLOR.senal, emissiveIntensity: 1.1 }));
    punto.position.y = 1.18 * escala + 0.22; punto.visible = false;
    grupo.add(punto);
    const anillo = new THREE.Mesh(geoAnillo, new THREE.MeshBasicMaterial({ color: COLOR.ambar, transparent: true }));
    anillo.rotation.x = Math.PI / 2; anillo.position.y = 0.03; anillo.visible = false;
    grupo.add(anillo);
    escena.add(grupo);
    agentes.set(a.id, { ...a, grupo, cuerpo, punto, anillo, pantalla, estado: "reposo", fase: Math.random() * 6.28 });
  }

  // --- Capa HTML sobre la escena (solo el nombre del agente elegido) ---------------------------------------------------------------
  const capa = document.createElement("div");
  capa.className = "of3-capa";
  contenedor.appendChild(capa);
  const nombreAgente = document.createElement("div");
  nombreAgente.className = "of3-nombre";
  nombreAgente.hidden = true;
  capa.appendChild(nombreAgente);
  let seleccionado = null;
  const marca = new THREE.Mesh(new THREE.TorusGeometry(0.46, 0.04, 8, 48), new THREE.MeshBasicMaterial({ color: COLOR.senal }));
  marca.rotation.x = Math.PI / 2; marca.visible = false;
  escena.add(marca);

  // --- Cámara: encuadre, foco animado ---------------------------------------------------------------------------------------------
  const v = new THREE.Vector3();
  const limites = () => {                                  // esquinas de la oficina para calcular el zoom que la encuadra entera
    const pts = [[-margen, -margen], [dist.ancho + margen, -margen], [dist.ancho + margen, dist.fondo + margen], [-margen, dist.fondo + margen]];
    return pts.map(([x, z]) => new THREE.Vector3(x, 0, z));
  };
  function encuadre() {
    camara.updateMatrixWorld();
    const inv = camara.matrixWorldInverse;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of limites()) { v.copy(p).applyMatrix4(inv); minX = Math.min(minX, v.x); maxX = Math.max(maxX, v.x); minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y); }
    for (const y of [-1.4, 4]) for (const p of limites()) { v.set(p.x, y, p.z).applyMatrix4(inv); minY = Math.min(minY, v.y); maxY = Math.max(maxY, v.y); }
    return { w: maxX - minX, h: maxY - minY };
  }
  function ajustar() {
    const W = ancho(), H = alto(), asp = W / H;
    renderer.setSize(W, H);
    const base = 30;                                        // altura visible con zoom 1: unidades del frustum
    Object.assign(camara, { left: -base * asp, right: base * asp, top: base, bottom: -base });
    camara.updateProjectionMatrix();
    const e = encuadre();
    zoomCompleto = Math.min((2 * base * asp) / (e.w * 1.0), (2 * base) / (e.h * 1.03));
    if (!enfoque) { camara.zoom = zoomCompleto; camara.updateProjectionMatrix(); }
    controles.minZoom = zoomCompleto * 0.6;
    controles.maxZoom = zoomCompleto * 22;
  }
  let zoomCompleto = 1, enfoque = null, anim = null;

  function volarA(objetivo, zoom, ms = 800) {
    anim = { t0: performance.now(), ms, desde: { t: controles.target.clone(), z: camara.zoom, p: camara.position.clone() }, a: { t: objetivo.clone(), z: zoom } };
  }
  const ease = (k) => 1 - Math.pow(1 - k, 3);

  // El panel lateral tapa la derecha de la escena: el objetivo se desplaza para que lo enfocado quede en el centro de lo visible
  function conPanel(objetivo, zoom) {
    const derecha = new THREE.Vector3().setFromMatrixColumn(camara.matrixWorld, 0);
    const pxPorUnidad = (alto() / 60) * zoom;                 // el frustum mide 60 unidades de alto con zoom 1
    const panel = ancho() > 900 ? 330 : 0;
    return objetivo.clone().addScaledVector(derecha, panel / 2 / pxPorUnidad);
  }
  function enfocarSala(id) {
    const s = dist.salas.find((x) => x.id === id);
    if (!s) return;
    enfoque = { tipo: "sala", id };
    seleccionado = null;
    const z = zoomCompleto * 2.5;
    volarA(conPanel(new THREE.Vector3(s.centro.x, 0.6, s.centro.z), z), z);
    resaltarSala(id);
  }
  function enfocarAgente(id) {
    const a = agentes.get(id);
    if (!a) return;
    enfoque = { tipo: "agente", id };
    seleccionado = id;
    const z = zoomCompleto * 5.5;
    volarA(conPanel(new THREE.Vector3(a.grupo.position.x, 0.8, a.grupo.position.z), z), z);
    resaltarSala(a.sala);
  }
  function vistaGeneral() {
    enfoque = null; seleccionado = null;
    volarA(centro, zoomCompleto);
    resaltarSala(null);
  }
  function resaltarSala(id) {
    for (const [sid, l] of lineasSala) l.material = sid === id ? mat.lineaSel : mat.linea;
    for (const [sid, c] of carteles) { const sel = sid === id; if (sel !== c.sel) { c.sel = sel; dibujarCartel(c); } }
  }

  // --- Interacción ---------------------------------------------------------------------------------------------------------------
  const rayo = new THREE.Raycaster(), p2 = new THREE.Vector2();
  let hover = null, arrastre = null;
  const alPuntero = (ev) => {
    const r = renderer.domElement.getBoundingClientRect();
    p2.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    rayo.setFromCamera(p2, camara);
    return rayo.intersectObjects(dianas, false)[0]?.object.userData.agente || null;
  };
  renderer.domElement.addEventListener("pointermove", (ev) => {
    if (ev.buttons) return;
    const id = alPuntero(ev);
    if (id !== hover) { hover = id; renderer.domElement.style.cursor = id ? "pointer" : ""; }
    const r = contenedor.getBoundingClientRect();
    alPasarPor?.(id, ev.clientX - r.left, ev.clientY - r.top);
  });
  renderer.domElement.addEventListener("pointerleave", () => { hover = null; alPasarPor?.(null); });
  renderer.domElement.addEventListener("pointerdown", (ev) => { arrastre = { x: ev.clientX, y: ev.clientY }; });
  renderer.domElement.addEventListener("pointerup", (ev) => {
    if (!arrastre || Math.hypot(ev.clientX - arrastre.x, ev.clientY - arrastre.y) > 5) return;       // un arrastre mueve la cámara, no selecciona
    const id = alPuntero(ev);
    if (id) alSeleccionarAgente?.(id);
    else {
      // clic en el suelo de una sala
      const hit = rayo.intersectObjects(escena.children.filter((o) => o.userData.sala), false)[0];
      if (hit) alSeleccionarSala?.(hit.object.userData.sala);
    }
  });
  controles.addEventListener("start", () => { anim = null; });          // si la persona mueve la cámara, se cancela el vuelo

  // --- Bucle ---------------------------------------------------------------------------------------------------------------------
  const inicio = performance.now();
  const proyectar = (pos, el, dx = 0, dy = 0) => {
    v.copy(pos).project(camara);
    const visible = v.z < 1;
    el.style.transform = `translate(-50%,-50%) translate(${((v.x + 1) / 2) * ancho() + dx}px, ${((1 - v.y) / 2) * alto() + dy}px)`;
    el.style.visibility = visible ? "visible" : "hidden";
  };
  let vivo = true;
  renderer.setAnimationLoop(() => {
    if (!vivo || document.hidden) return;
    const t = (performance.now() - inicio) / 1000;
    if (anim) {
      const k = Math.min(1, (performance.now() - anim.t0) / anim.ms), e = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 1 : ease(k);
      const nuevo = anim.desde.t.clone().lerp(anim.a.t, e);
      const delta = nuevo.clone().sub(controles.target);
      controles.target.copy(nuevo); camara.position.add(delta);
      camara.zoom = anim.desde.z + (anim.a.z - anim.desde.z) * e;
      camara.updateProjectionMatrix();
      if (k >= 1) anim = null;
    }
    for (const a of agentes.values()) {
      const t0 = t + a.fase;
      if (a.estado === "trabajando") { a.cuerpo.position.y = (a.director ? 0.62 : 0.51) + Math.sin(t0 * 5) * 0.03; a.punto.position.y += (Math.sin(t0 * 6) * 0.004); a.punto.scale.setScalar(1 + Math.sin(t0 * 6) * 0.25); }
      else if (a.estado === "esperando") { const s = 1 + ((t0 * 0.8) % 1) * 0.5; a.anillo.scale.set(s, s, s); a.anillo.material.opacity = 1 - ((t0 * 0.8) % 1); }
      else a.cuerpo.position.y = a.director ? 0.62 : 0.51;
    }
    if (seleccionado) { const a = agentes.get(seleccionado); marca.visible = true; marca.position.set(a.grupo.position.x, 0.17, a.grupo.position.z); marca.scale.setScalar(1 + Math.sin(t * 4) * 0.06); }
    else marca.visible = false;
    controles.update();
    if (seleccionado) {
      const a = agentes.get(seleccionado);
      nombreAgente.hidden = false;
      v.copy(a.grupo.position); v.y += 2.2;
      proyectar(v, nombreAgente);
    } else nombreAgente.hidden = true;
    renderer.render(escena, camara);
  });

  const observador = new ResizeObserver(() => ajustar());
  observador.observe(contenedor);
  ajustar();
  camara.zoom = zoomCompleto; camara.updateProjectionMatrix();

  return {
    actualizar(estados) {                                  // estados: { id: { estado, detalle } }
      let trabajando = new Map();
      for (const a of agentes.values()) {
        const s = estados[a.id]?.estado || "reposo";
        if (s !== a.estado) {
          a.estado = s;
          const m = a.pantalla.material;
          if (s === "trabajando") { m.color.set(COLOR.senal); m.emissive.set(COLOR.senal); m.emissiveIntensity = 0.9; }
          else if (s === "esperando") { m.color.set(COLOR.ambar); m.emissive.set(COLOR.ambar); m.emissiveIntensity = 0.7; }
          else { m.color.set("#1d1d21"); m.emissive.set("#000000"); m.emissiveIntensity = 0; }
          a.punto.visible = s === "trabajando"; a.anillo.visible = s === "esperando";
          if (s === "trabajando") a.punto.material.emissive.set(COLOR.senal);
        }
        if (s === "trabajando") trabajando.set(a.sala, (trabajando.get(a.sala) || 0) + 1);
      }
      for (const [id, c] of carteles) {
        const n = trabajando.get(id) || 0;
        if (n !== c.n) { c.n = n; dibujarCartel(c); }
      }
    },
    enfocarSala, enfocarAgente, vistaGeneral,
    nombreSeleccionado(texto) { nombreAgente.textContent = texto || ""; },
    capturar: () => renderer.domElement.toDataURL("image/png"),
    destruir() {
      vivo = false;
      renderer.setAnimationLoop(null);
      observador.disconnect();
      controles.dispose();
      escena.traverse((o) => { o.geometry?.dispose?.(); const m = o.material; (Array.isArray(m) ? m : m ? [m] : []).forEach((x) => x.dispose?.()); });
      renderer.dispose();
      renderer.domElement.remove();
      capa.remove();
    },
  };
}
