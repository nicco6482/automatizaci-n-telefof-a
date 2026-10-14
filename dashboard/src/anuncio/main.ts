// Anuncio de teleco-agents. Toda la animación es función del tiempo de la narración:
// en la web sigue al audio; en modo render (?render) se pinta fotograma a fotograma con window.__seek(t).
import "./anuncio.css";
import guion from "./guion.json";
import { AGENTES, NIVEL, type AdAgent } from "./agentes";
import { OfficeView, type Fx, type HumanState } from "../office/view";
import type { Actor, Loc, Tone } from "../office/actors";
import { AREA, AREA_LIST, H, RED_STAND_X, ROOM, STATION, W, type Area, type Pt, type StationId } from "../office/layout";

interface LineT { start: number; end: number }
interface SceneT { id: string; start: number; end: number; lineas: LineT[] }
interface Tiempos { total: number; escenas: SceneT[] }
interface GLine { texto: string; agente?: string; cue?: string }
interface GScene { id: string; area?: string; lineas: GLine[] }
type Rect = [number, number, number, number];

const FONTS = { display: "Bahnschrift, 'Segoe UI', Arial, sans-serif", body: "'Segoe UI', system-ui, Arial, sans-serif", mono: "'Cascadia Mono', Consolas, monospace" };
const RENDER = new URLSearchParams(location.search).has("render");
const BASE = "anuncio/";

// ---------- utilidades ----------
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const ease = (x: number) => (x < 0.5 ? 2 * x * x : 1 - (-2 * x + 2) ** 2 / 2);
const easeOut = (x: number) => 1 - (1 - x) ** 3;
const back = (x: number) => { const c = 1.9; return x <= 0 ? 0 : x >= 1 ? 1 : 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2; };
const win = (t: number, a: number, b: number, f = 0.5) => Math.min(clamp01((t - a) / f), clamp01((b - t) / f));
const $ = <T extends HTMLElement = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
function h(tag: string, cls: string, parent: HTMLElement, html = ""): HTMLElement {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html) e.innerHTML = html;
  parent.appendChild(e);
  return e;
}
const fmt = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
const OV = { x: W / 2, y: 400, z: 0.88 };

interface Key { t: number; x: number; y: number; z: number; d: number }
class Cam {
  private keys: Key[] = [];
  private starts: Key[] = [];
  add(t: number, x: number, y: number, z: number, d = 1.0): void { this.keys.push({ t, x, y, z, d }); }
  done(): void {
    this.keys.sort((a, b) => a.t - b.t);
    this.starts = [];
    this.keys.forEach((k, i) => {
      if (i === 0) { this.starts.push(k); return; }
      const p = this.keys[i - 1]!;
      this.starts.push(this.blend(this.starts[i - 1]!, p, (k.t - p.t) / p.d));
    });
  }
  private blend(a: Key, b: Key, p: number): Key {
    const e = ease(clamp01(p));
    return { t: b.t, x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, z: a.z + (b.z - a.z) * e, d: b.d };
  }
  at(t: number): Key {
    let i = 0;
    for (let k = 0; k < this.keys.length; k++) if (this.keys[k]!.t <= t) i = k;
    const k = this.keys[i]!;
    return this.blend(this.starts[i] ?? k, k, (t - k.t) / k.d);
  }
}

// ---------- arranque ----------
async function boot(): Promise<void> {
  const T = (await (await fetch(`${BASE}tiempos.json`)).json()) as Tiempos;
  const G = guion as { escenas: GScene[] };
  const sc = (id: string): SceneT => T.escenas.find((s) => s.id === id)!;
  const ln = (id: string, i: number): LineT => sc(id).lineas[i]!;
  const rects: Record<string, Record<string, Rect>> = {};
  for (const n of ["panel", "aprobaciones", "tareas", "oficina"]) {
    const raw = await (await fetch(`${BASE}shots/${n}.json`)).text();
    rects[n] = JSON.parse(raw.slice(raw.indexOf("{"))) as Record<string, Rect>;
  }
  rects.auditoria = { tabla: [639, 98, 944, 760] };

  const stage = $("#stage");
  // ===== oficina =====
  const officeSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  officeSvg.id = "office";
  stage.appendChild(officeSvg);
  const view = new OfficeView(officeSvg, AGENTES, FONTS);
  const act = (id: string): Actor => view.actors.get(id)!;
  const ag = (id: string): AdAgent => AGENTES.find((a) => a.id === id)!;
  const toLoc = (d: StationId | "red"): Loc => (d === "red" ? { k: "red" } : { k: "st", id: d });
  const standPt = (a: Actor, d: StationId | "red"): Pt =>
    d === "red" ? { x: RED_STAND_X + a.slot.off * 0.8, y: a.slot.room.top ? 404 : 522 } : { x: STATION[d].x + a.slot.off, y: a.slot.stand };
  /** Planifica que el agente llegue a un sitio a una hora concreta. */
  function arrive(id: string, d: StationId | "red", tArr: number, dwell: number, text?: string, tone: Tone = "", speed = 560, gate?: { text?: string; tone?: Tone; dwell?: number }): void {
    const a = act(id);
    const walk = a.distTo(toLoc(d)) / speed;
    const gd = d === "red" ? (gate?.dwell ?? 0.35) : 0;
    a.go(tArr - walk - gd, toLoc(d), { dur: walk, dwell, text, tone, gate: { tone: "ok", ...gate, dwell: gd } });
  }
  const home = (id: string, at: number, speed = 620) => act(id).home(at, { speed });

  const cam = new Cam();
  const fxAt: ((t: number, fx: Fx) => void)[] = [];
  const humanAt: ((t: number, hs: Partial<Record<StationId, HumanState>>) => void)[] = [];

  // --- equipo: aparecen los 40 y cuatro van a trabajar
  const eq = sc("equipo");
  cam.add(0, OV.x, OV.y, 1.05, 0.1);
  cam.add(eq.start, OV.x, OV.y, 1.05, 0.1);
  cam.add(eq.start + 0.3, OV.x, OV.y, OV.z, 3.0);
  const order = AGENTES.map((a) => a.id);
  const popAt = (id: string) => ln("equipo", 0).start + 0.1 + order.indexOf(id) * 0.075;
  {
    const l2 = ln("equipo", 2);
    const dl = l2.end - l2.start;
    arrive("19", "archivo", l2.start + dl * 0.42, 2.6, "inventario al día", "ok");
    arrive("02", "tickets", l2.start + dl * 0.6, 2.2, "TCK-0041 abierto", "ok");
    arrive("22", "gemelo", l2.start + dl * 0.75, 1.9, "gemelo ✓", "ok");
    arrive("01", "red", l2.end + 0.1, 1.4, "alarmas revisadas", "ok");
    for (const id of ["19", "02", "22", "01"]) home(id, eq.end - 0.2, 700);
  }

  // --- control
  const ct = sc("control");
  {
    const [l0, l1, l2, l3, l4, l5] = ct.lineas as [LineT, LineT, LineT, LineT, LineT, LineT];
    cam.add(ct.start - 0.2, 1150, 450, 1.75, 1.4);
    act("25").go(l0.start - 0.2, { k: "gate" }, { dur: l1.start - l0.start + 0.2 });
    act("25").say(l1.start, "permiso ✓ · nivel 2 ✓ · 0 clientes afectados ✓", "ok", l1.end - l1.start + 0.1);
    act("25").go(l1.end + 0.1, { k: "red" }, { speed: 420, dwell: 1.2, text: "rutas revisadas", tone: "ok" });
    const walk35 = act("35").distTo({ k: "gate" }) / 520;
    act("35").go(l2.start + 0.35 - walk35, { k: "gate" }, { dur: walk35, dwell: l2.end - l2.start + 0.1, text: "✗ red.config: no está en su lista", tone: "crit" });
    home("35", l2.end + 0.25, 600);
    home("25", l3.start, 700);
    arrive("22", "gemelo", l3.start + 0.5, l3.end - l3.start, "probar_config: gemelo ✓", "ok", 520);
    fxAt.push((t, fx) => { if (t >= l3.start + 0.5 && t < l4.start) fx.twin = "ok"; });
    arrive("22", "aprobacion", l4.start + 0.35, l4.end - l4.start + 0.9, "aplicar_config → aprobación", "warn", 520);
    humanAt.push((t, hs) => { if (t >= l4.start + 0.6 && t < l5.start + 0.6) hs.aprobacion = { text: "✓ Aprobado", tone: "ok" }; });
    fxAt.push((t, fx) => { if (t >= l4.start + 0.6) fx.stamp = clamp01((t - l4.start - 0.6) / 0.6); });
    home("22", l5.start + 0.6, 700);
    cam.add(l5.start, OV.x, OV.y, OV.z, 1.0);
    fxAt.push((t, fx) => { if (t >= l5.start + 0.5 && t < ct.end - 0.1) fx.kill = true; });
  }

  // --- áreas: cada agente va a su puesto
  const areaScenes = G.escenas.filter((s) => s.area);
  for (const g of areaScenes) {
    const s = sc(g.id);
    const room = ROOM[g.area as Area];
    const rc = { x: room.x + room.w / 2, y: room.top ? room.y + room.h / 2 + 50 : room.y + room.h / 2 - 50 };
    cam.add(s.start - 0.1, rc.x, rc.y, 2.0, 1.1);
    const ids = AGENTES.filter((a) => a.area === g.area).map((a) => a.id);
    fxAt.push((t, fx) => { if (t >= s.start && t < (s.lineas[1]?.start ?? s.end)) { fx.focus = ids; fx.dim = true; } });
    g.lineas.forEach((gl, i) => {
      if (!gl.agente) return;
      const l = s.lineas[i]!;
      const next = s.lineas[i + 1]?.start ?? s.end;
      const id = gl.agente;
      const a = act(id);
      const d = ag(id).va;
      const dur = next - l.start;
      const sp = standPt(a, d);
      const bx0 = Math.min(a.slot.seat.x, sp.x) - 170, bx1 = Math.max(a.slot.seat.x, sp.x) + 170;
      const by0 = Math.min(a.slot.seat.y, sp.y) - 150, by1 = Math.max(a.slot.seat.y, sp.y) + 110;
      const z = Math.max(1.0, Math.min(2.2, W / (bx1 - bx0), H / (by1 - by0)));
      cam.add(l.start - 0.25, (bx0 + bx1) / 2, (by0 + by1) / 2, z, Math.min(1.0, dur * 0.45));
      const walkEnd = l.start + Math.min(1.7, dur * 0.55);
      arrive(id, d, walkEnd, Math.max(0.6, next + 0.35 - walkEnd), ag(id).dice, "ok", Math.max(420, a.distTo(toLoc(d)) / (walkEnd - l.start - 0.1)));
      home(id, next + 0.4, 760);
      fxAt.push((t, fx) => { if (t >= l.start - 0.1 && t < next) { fx.focus = [id]; fx.dim = true; } });
    });
  }

  // --- personas
  const pe = sc("personas");
  const PERSONAS = AGENTES.filter((a) => a.persona).map((a) => a.id);
  cam.add(pe.start - 0.2, OV.x, OV.y, OV.z, 1.2);
  fxAt.push((t, fx) => { if (t >= pe.start && t < pe.end) { fx.focus = PERSONAS; fx.dim = true; } });
  {
    const l1 = ln("personas", 1);
    PERSONAS.forEach((id, i) => {
      const d: StationId = id === "40" ? "direccion" : "personas";
      arrive(id, d, l1.start + 1.2 + i * 0.45, Math.max(0.8, pe.end - (l1.start + 1.2 + i * 0.45) - 0.4), "borrador para firmar", "info", 640);
      home(id, pe.end + 0.2, 760);
    });
    humanAt.push((t, hs) => { if (t >= l1.start + 1.2 && t < pe.end) hs.personas = { text: "Lo firmo yo ✍", tone: "info" }; });
  }

  // --- incidente de madrugada
  const inc = sc("incidente");
  {
    const L = inc.lineas;
    cam.add(inc.start - 0.2, 980, 450, 1.22, 1.4);
    fxAt.push((t, fx) => {
      fx.night = Math.max(fx.night ?? 0, win(t, inc.start + 0.2, inc.end - 0.6, 1.2));
      if (t >= L[0]!.start + 1.6 && t < L[6]!.start + 1.2) fx.alarm = true;
      if (t >= L[2]!.start + 0.5 && t < L[6]!.end) fx.tickets = 4;
      if (t >= L[5]!.start + 0.6 && t < L[6]!.start + 0.6) fx.ring = true;
    });
    arrive("01", "red", L[1]!.start + 0.5, L[1]!.end - L[1]!.start + 0.3, "6 alarmas → 1 grupo", "ok", 620, { text: "✓", dwell: 0.3 });
    arrive("02", "tickets", L[2]!.start + 0.4, 2.2, "TCK-0042 · P1", "ok", 620);
    arrive("08", "exterior", L[3]!.start + 0.5, 2.0, "sin tormenta ✓", "ok", 620);
    arrive("03", "red", L[4]!.start + 0.7, L[4]!.end - L[4]!.start, "sin respaldo ✗", "crit", 640, { text: "✓", dwell: 0.3 });
    arrive("04", "guardia", L[5]!.start + 0.6, L[5]!.end - L[5]!.start + 0.4, "aviso: TCK-0042", "warn", 640);
    humanAt.push((t, hs) => { if (t >= L[5]!.start + 0.9 && t < L[6]!.start + 1.4) hs.guardia = { text: t < L[6]!.start ? "¡Voy!" : "✓ Reparado", tone: t < L[6]!.start ? "warn" : "ok" }; });
    arrive("05", "tickets", L[6]!.start + 1.1, L[6]!.end - L[6]!.start + 0.3, "causa raíz: fibra cortada", "ok", 640);
    for (const id of ["01", "02", "08", "03", "04", "05"]) home(id, L[7]!.start - 0.2, 700);
    cam.add(L[7]!.start, OV.x, OV.y, OV.z, 1.6);
  }

  // --- cierre: la oficina trabajando sola
  const ci = sc("cierre");
  {
    cam.add(ci.start - 0.3, W / 2, H / 2, 1.12, 0.6);
    cam.add(ci.start + 0.3, W / 2 + 120, H / 2, 0.98, ci.end - ci.start);
    let seed = 7;
    const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    const pool = AGENTES.filter((_, i) => i % 3 === 0);
    pool.forEach((a, i) => {
      const t0 = ci.start + 0.3 + i * 0.55 + rnd();
      act(a.id).go(t0, toLoc(a.va), { speed: 300, dwell: 1.5 + rnd() * 1.5, text: a.dice, tone: "ok" });
      act(a.id).home(t0 + 5 + rnd() * 2, { speed: 300 });
    });
  }
  cam.done();

  // ===== capas HTML =====
  const intro = h("div", "layer intro", stage, `
    <svg class="net" viewBox="0 0 1920 1080"></svg>
    <div class="logo"><span class="mark"></span><div><b>teleco-agents</b><small>40 agentes de IA · una red que se opera sola</small></div></div>`);
  const netSvg = intro.querySelector("svg")!;
  const nodes: [number, number][] = [];
  { let s = 3; const r = () => { s = (s * 48271) % 2147483647; return s / 2147483647; };
    for (let i = 0; i < 46; i++) nodes.push([120 + r() * 1680, 90 + r() * 900]); }
  const edges: [number, number, SVGLineElement][] = [];
  nodes.forEach((p, i) => nodes.forEach((q, j) => {
    if (j <= i || Math.hypot(p[0] - q[0], p[1] - q[1]) > 260) return;
    const l = document.createElementNS("http://www.w3.org/2000/svg", "line");
    l.setAttribute("x1", String(p[0])); l.setAttribute("y1", String(p[1])); l.setAttribute("x2", String(q[0])); l.setAttribute("y2", String(q[1]));
    netSvg.appendChild(l); edges.push([i, j, l]);
  }));
  const dots = nodes.map((p) => {
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", String(p[0])); c.setAttribute("cy", String(p[1])); c.setAttribute("r", "5");
    netSvg.appendChild(c); return c;
  });

  // problema
  const prob = h("div", "layer problem", stage, `
    <div class="pc"><span>ALARMAS HOY</span><b id="pcount">0</b><em id="pnoise">el 87 % son ruido</em></div>
    <div class="clock" id="pclock">18:00</div>
    <svg viewBox="0 0 1920 1080" id="psvg"></svg>`);
  const psvg = prob.querySelector<SVGSVGElement>("#psvg")!;
  psvg.innerHTML = `
    <rect x="0" y="820" width="1920" height="260" fill="#0f161f"/>
    <rect x="560" y="690" width="800" height="40" rx="6" fill="#3a4858"/>
    <rect x="600" y="730" width="24" height="120" fill="#2b3948"/><rect x="1296" y="730" width="24" height="120" fill="#2b3948"/>
    ${[640, 860, 1080].map((x) => `<rect x="${x}" y="470" width="200" height="130" rx="8" fill="#0c121a" stroke="#3b4b5d" stroke-width="4"/><rect x="${x + 10}" y="480" width="180" height="110" rx="4" fill="#3a1b14"/><rect x="${x + 90}" y="600" width="20" height="90" fill="#3b4b5d"/>`).join("")}
    <g id="phone" opacity="0"><rect x="1180" y="664" width="70" height="26" rx="8" fill="#15202a"/><path d="M1170 662 q0 -22 22 -22 h26 q22 0 22 22" stroke="#15202a" stroke-width="10" fill="none" stroke-linecap="round"/>
      <path d="M1150 630 q-12 16 0 32 M1270 630 q12 16 0 32" stroke="#f5c542" stroke-width="5" fill="none"/></g>
    <g id="eng" transform="translate(960 905) scale(5.2)">
      <rect x="-15" y="-20" width="30" height="40" rx="8" fill="#2b3948"/>
      <rect x="-13" y="-24" width="26" height="28" rx="10" fill="#5d6b7a"/>
      <g id="ehead"><circle cx="0" cy="-34" r="10" fill="#f1c7a0"/><path d="M-10.2 -33 A10.2 10.2 0 1 1 10.2 -33 Q0 -27 -10.2 -33Z" fill="#3b2a20"/></g>
    </g>
    <g id="alarms"></g>
    <rect id="pdark" x="0" y="0" width="1920" height="1080" fill="#040913" opacity="0"/>`;
  const alarmsG = psvg.querySelector("#alarms")!;
  const pr = sc("problema");
  const NA = 150;
  const alarms = Array.from({ length: NA }, (_, i) => {
    let s = i * 7919 + 13; const r = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
    const mon = i % 3;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.innerHTML = `<path d="M0 -16 L15 12 L-15 12 Z" fill="${r() < 0.8 ? "#e3a845" : "#f0775c"}" stroke="#0f161f" stroke-width="2"/><rect x="-1.6" y="-6" width="3.2" height="10" fill="#0f161f"/><circle cx="0" cy="8" r="1.8" fill="#0f161f"/>`;
    alarmsG.appendChild(g);
    const col = Math.floor(r() * 22);
    const t0 = pr.start + 0.4 + i * 0.075 + r() * 0.2;
    return { g, t0, x0: 740 + mon * 220, y0: 535, x1: 120 + col * 76 + (r() - 0.5) * 30, y1: 880 - Math.floor(i / 22) * 17 - r() * 8, rot: (r() - 0.5) * 80 };
  });

  // panel web (capturas reales)
  const ui = h("div", "layer ui", stage, `
    <div class="browser"><div class="bar"><i></i><i></i><i></i><span class="url">localhost:8000 · teleco-agents</span></div>
      <div class="vp"><div class="zoom" id="zoom"></div><div class="hl" id="hl"></div></div></div>
    <div class="cursor" id="cursor"><svg viewBox="0 0 24 24"><path d="M3 2 L20 13 L12 14 L8 22 Z" fill="#fff" stroke="#0f1722" stroke-width="1.6"/></svg></div>
    <div class="ripple" id="ripple"></div><div class="toast" id="toast"></div><div class="lock" id="lock">🔒 solo se añaden · nunca se borran</div>`);
  const zoom = $("#zoom");
  const shotImgs: Record<string, HTMLImageElement> = {};
  const addImg = (key: string, src: string) => { const im = h("img", "", zoom) as HTMLImageElement; im.src = src; shotImgs[key] = im; };
  for (const n of ["panel", "aprobaciones", "auditoria", "tareas"]) addImg(n, `${BASE}shots/${n}.jpg`);
  for (let i = 0; i < 40; i++) addImg(`of${i}`, `${BASE}shots/oficina_${String(i).padStart(2, "0")}.jpg`);
  const VW = 1440, VH = 900, S0 = 0.9, VX = (1920 - VW) / 2, VY = 108;
  interface UiBeat { t: number; shot: string; focus?: Rect; z?: number; hl?: Rect; cur?: [number, number]; click?: number; toast?: [string, string] }
  const beats: UiBeat[] = [];
  const uiCam = new Cam();
  const center = (r: Rect): [number, number] => [r[0] + r[2] / 2, r[1] + r[3] / 2];
  {
    const p = sc("panel"), [p0, p1, p2] = p.lineas as [LineT, LineT, LineT];
    uiCam.add(0, 800, 500, 1, 0.1);
    uiCam.add(p.start, 800, 500, 1.0, 0.1);
    const m = rects.panel!.metricas!, k = rects.panel!.interruptor!;
    uiCam.add(p1.start - 0.2, ...center(m), 1.55, 1.0);
    uiCam.add(p2.start, ...center(k), 1.9, 1.1);
    beats.push({ t: p.start, shot: "panel" }, { t: p1.start, shot: "panel", hl: m }, { t: p2.start + 0.4, shot: "panel", hl: k, cur: center(k) },
      { t: p2.start + 1.9, shot: "panel", hl: k, cur: center(k), click: p2.start + 1.9, toast: ["Interruptor activo: los 40 agentes en nivel 0", "crit"] });
    void p0;
    const a = sc("aprobaciones"), [a0, a1] = a.lineas as [LineT, LineT];
    const card = rects.aprobaciones!.tarjeta!, btn = rects.aprobaciones!.boton!;
    uiCam.add(a.start - 0.1, ...center(card), 1.45, 0.1);
    uiCam.add(a1.start - 0.3, ...center(btn), 1.85, 0.9);
    beats.push({ t: a0.start - 0.3, shot: "aprobaciones", hl: card }, { t: a1.start, shot: "aprobaciones", hl: btn, cur: center(btn) },
      { t: a1.start + 0.7, shot: "aprobaciones", hl: btn, cur: center(btn), click: a1.start + 0.7, toast: ["Aprobado: el núcleo lo ejecuta y lo audita", "ok"] });
    const au = sc("auditoria"), [u0, u1] = au.lineas as [LineT, LineT];
    const tab = rects.auditoria!.tabla!;
    uiCam.add(au.start - 0.1, 1110, 420, 1.35, 0.1);
    uiCam.add(au.start + 0.2, 1110, 560, 1.5, au.end - au.start);
    beats.push({ t: u0.start - 0.3, shot: "auditoria", hl: tab }, { t: u1.start, shot: "auditoria", hl: tab });
    const ba = sc("bandejas"), [b0, b1] = ba.lineas as [LineT, LineT];
    const task = rects.tareas!.tarea!, tb = rects.tareas!.boton!;
    uiCam.add(ba.start - 0.1, ...center(task), 1.5, 0.1);
    uiCam.add(b1.start, ...center(tb), 1.8, 0.9);
    beats.push({ t: b0.start - 0.3, shot: "tareas", hl: task }, { t: b1.start, shot: "tareas", hl: tb, cur: center(tb) },
      { t: b1.start + 0.9, shot: "tareas", hl: tb, cur: center(tb), click: b1.start + 0.9, toast: ["Solo una persona cierra esta tarea", "ok"] });
    const of = sc("oficina_web");
    const st = rects.oficina!.stage!;
    uiCam.add(of.start - 0.1, 800, 500, 1.0, 0.1);
    uiCam.add(of.start + 0.2, ...center(st), 1.28, of.end - of.start);
    beats.push({ t: of.start - 0.3, shot: "oficina" });
    uiCam.done();
  }

  // resultados
  const res = h("div", "layer results", stage, `<div class="kick2">Resultados del prototipo</div><div class="cards"></div><p class="foot">En la demo: 98,8 % de alarmas falsas filtradas · 0 cambios sin gemelo ni aprobación · 0 acciones sin rastro previo</p>`);
  const RES: [number, string, string, string][] = [
    [126, "", "escenarios de prueba", "cada uno repetido 5 veces"],
    [191, "", "pruebas superadas", "suite completa, 0 fallos"],
    [1.4, " s", "diagnóstico medio", "de una avería, en la demo"],
    [0, "", "acciones fuera de control", "ni fuera de permisos, ni sin auditoría"],
  ];
  const resCards = RES.map(([, , t, d]) => {
    const c = h("div", "rc", res.querySelector<HTMLElement>(".cards")!, `<b>0</b><span>${t}</span><small>${d}</small>`);
    return c;
  });

  // cierre
  const closing = h("div", "layer closing", stage, `
    <div class="logo big"><span class="mark"></span><div><b>teleco-agents</b></div></div>
    <p class="l1">Tus ingenieros dejan de repetir<br>y empiezan a decidir.</p>
    <p class="l2">La red trabaja sola.<br><em>Las personas siguen al mando.</em></p>
    <div class="cta">Pide tu piloto →</div>
    <div class="url">nicco6482.github.io/automatizaci-n-telefof-a</div>`);

  // rótulos
  const kicker = h("div", "kicker", stage);
  const areaChips = h("div", "areas", stage, AREA_LIST.map((a) => `<span style="--c:${a.color}">${a.label}</span>`).join(""));
  const card = h("div", "acard", stage);
  const subs = h("div", "subs", stage);
  const prog = h("div", "prog", stage);
  const fade = h("div", "fade", stage);
  const KICK: Record<string, string> = {
    problema: "El problema", equipo: "Tu nuevo equipo · 40 agentes", control: "El núcleo de control",
    personas: "Trabajo que acaba en una persona", incidente: "En acción · 03:00 · caída de enlace",
    panel: "El panel web", aprobaciones: "El panel web · aprobaciones", auditoria: "El panel web · auditoría",
    bandejas: "El panel web · bandejas de personas", oficina_web: "La oficina, en directo",
  };
  const lineText: { t0: number; t1: number; text: string; agent?: string }[] = [];
  G.escenas.forEach((g) => g.lineas.forEach((gl, i) => {
    const l = sc(g.id).lineas[i]!;
    lineText.push({ t0: l.start, t1: l.end + 0.3, text: gl.texto, agent: gl.agente });
  }));
  let lastSub = "", lastCard = "", lastKick = "";

  // ===== fotograma =====
  function render(t: number): void {
    const cur = T.escenas.find((s) => t >= s.start && t < s.end) ?? T.escenas[T.escenas.length - 1]!;
    // capas
    const officeOn = Math.max(win(t, sc("equipo").start, sc("incidente").end, 0.6), win(t, ci.start, T.total + 5, 0.6));
    officeSvg.style.opacity = String(officeOn);
    intro.style.opacity = String(win(t, -1, sc("intro").end + 0.2, 0.6));
    prob.style.opacity = String(win(t, pr.start, pr.end + 0.2, 0.5));
    ui.style.opacity = String(win(t, sc("panel").start, sc("oficina_web").end + 0.2, 0.5));
    res.style.opacity = String(win(t, sc("resultados").start, sc("resultados").end + 0.2, 0.5));
    closing.style.opacity = String(win(t, ci.start + 0.2, T.total + 5, 0.8));
    fade.style.opacity = String(clamp01((t - (T.total - 1.0)) / 1.0) + clamp01(1 - t / 0.6));

    // intro
    if (+intro.style.opacity > 0) {
      const i0 = sc("intro");
      edges.forEach(([i, j, l], k) => {
        const s = clamp01((t - 0.3 - k * 0.012) / 0.7);
        const len = Math.hypot(nodes[i]![0] - nodes[j]![0], nodes[i]![1] - nodes[j]![1]);
        l.setAttribute("stroke-dasharray", `${len}`);
        l.setAttribute("stroke-dashoffset", String(len * (1 - s)));
        l.setAttribute("opacity", String(0.35 + 0.25 * Math.sin(t * 2 + k)));
      });
      dots.forEach((d, k) => d.setAttribute("opacity", String(clamp01((t - 0.1 - k * 0.03) / 0.3))));
      const lg = intro.querySelector<HTMLElement>(".logo")!;
      const p = easeOut(clamp01((t - (i0.lineas[1]!.start - 0.4)) / 0.8));
      lg.style.opacity = String(p);
      lg.style.transform = `translateY(${(1 - p) * 30}px) scale(${0.96 + 0.04 * p})`;
    }
    // problema
    if (+prob.style.opacity > 0) {
      const [l0, l1, l2] = pr.lineas as [LineT, LineT, LineT];
      for (const a of alarms) {
        if (t < a.t0) { a.g.setAttribute("opacity", "0"); continue; }
        const p = clamp01((t - a.t0) / 0.7);
        const x = a.x0 + (a.x1 - a.x0) * p, y = a.y0 + (a.y1 - a.y0) * p - Math.sin(p * Math.PI) * 140;
        a.g.setAttribute("opacity", "1");
        a.g.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${(a.rot * p).toFixed(1)}) scale(${(0.6 + 0.6 * p).toFixed(2)})`);
      }
      $("#pcount").textContent = fmt(Math.floor(4812 * easeOut(clamp01((t - l0.start) / (l1.end - l0.start)))));
      $("#pnoise").style.opacity = String(clamp01((t - l0.end + 1.2) / 0.5));
      const hr = 18 + 9 * clamp01((t - l1.start) / (l2.start + 0.6 - l1.start));
      const hh = Math.floor(hr) % 24, mm = Math.floor((hr % 1) * 60 / 15) * 15;
      $("#pclock").textContent = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
      psvg.querySelector("#pdark")!.setAttribute("opacity", String(0.5 * clamp01((t - l2.start + 0.5) / 1)));
      psvg.querySelector("#phone")!.setAttribute("opacity", t > l2.start + 0.8 ? (Math.sin(t * 16) > 0 ? "1" : "0.3") : "0");
      psvg.querySelector("#ehead")!.setAttribute("transform", `rotate(${(-16 * clamp01((t - l1.start) / 3)).toFixed(1)} 0 -24)`);
    }
    // oficina
    if (officeOn > 0) {
      const k = cam.at(t);
      const z = k.z, hw = W / 2 / z, hh = H / 2 / z;
      const cx = z >= 1 ? Math.max(hw, Math.min(W - hw, k.x)) : k.x, cy = z >= 1 ? Math.max(hh, Math.min(H - hh, k.y)) : k.y;
      view.root.setAttribute("transform", `translate(${W / 2} ${H / 2}) scale(${z.toFixed(4)}) translate(${(-cx).toFixed(2)} ${(-cy).toFixed(2)})`);
      const fx: Fx = {
        pop: (id) => (t < sc("equipo").start ? 0 : back(clamp01((t - popAt(id)) / 0.45))),
        tickets: 3,
      };
      for (const f of fxAt) f(t, fx);
      const hs: Partial<Record<StationId, HumanState>> = {};
      for (const f of humanAt) f(t, hs);
      fx.humans = hs;
      view.render(t, fx);
    }
    // panel web
    if (+ui.style.opacity > 0) {
      let b: UiBeat | undefined;
      for (const x of beats) if (x.t <= t) b = x;
      b ??= beats[0]!;
      const of = sc("oficina_web");
      let shot = b.shot;
      if (shot === "oficina") shot = `of${Math.floor(Math.max(0, t - of.start) * 7.5) % 40}`;
      for (const [k2, im] of Object.entries(shotImgs)) im.style.display = k2 === shot ? "block" : "none";
      const k = uiCam.at(t);
      const z = k.z, hw = 800 / z, hh = 500 / z;
      const cx = Math.max(hw, Math.min(1600 - hw, k.x)), cy = Math.max(hh, Math.min(1000 - hh, k.y));
      zoom.style.transform = `translate(${VW / 2}px, ${VH / 2}px) scale(${S0 * z}) translate(${-cx}px, ${-cy}px)`;
      const toScreen = (x: number, y: number): [number, number] => [VX + VW / 2 + (x - cx) * S0 * z, VY + VH / 2 + (y - cy) * S0 * z];
      const hl = $("#hl");
      if (b.hl) {
        const [x, y] = toScreen(b.hl[0], b.hl[1]);
        hl.style.cssText = `opacity:${clamp01((t - b.t) / 0.3)};left:${x - VX - 8}px;top:${y - VY - 8}px;width:${b.hl[2] * S0 * z + 16}px;height:${b.hl[3] * S0 * z + 16}px`;
      } else hl.style.opacity = "0";
      const cu = $("#cursor"), rp = $("#ripple"), to = $("#toast");
      if (b.cur) {
        const prev = beats[beats.indexOf(b) - 1];
        const from = prev?.cur ?? [b.cur[0] + 260, b.cur[1] + 220];
        const p = ease(clamp01((t - b.t) / 0.7));
        const [x, y] = toScreen(from[0] + (b.cur[0] - from[0]) * p, from[1] + (b.cur[1] - from[1]) * p);
        cu.style.cssText = `opacity:1;left:${x}px;top:${y}px`;
      } else cu.style.opacity = "0";
      if (b.click !== undefined && b.cur) {
        const q = clamp01((t - b.click) / 0.6);
        const [x, y] = toScreen(b.cur[0], b.cur[1]);
        rp.style.cssText = `opacity:${1 - q};left:${x}px;top:${y}px;transform:translate(-50%,-50%) scale(${0.3 + q * 1.6})`;
      } else rp.style.opacity = "0";
      if (b.toast) {
        to.textContent = b.toast[0];
        to.dataset.s = b.toast[1];
        to.style.opacity = String(clamp01((t - (b.click ?? b.t) - 0.15) / 0.3));
      } else to.style.opacity = "0";
      const au = sc("auditoria");
      $("#lock").style.opacity = String(win(t, au.lineas[1]!.start, au.end, 0.3));
    }
    // resultados
    if (+res.style.opacity > 0) {
      const rs = sc("resultados");
      resCards.forEach((c, i) => {
        const l = rs.lineas[i]!;
        const p = clamp01((t - l.start + 0.2) / 0.5);
        c.style.opacity = String(p);
        c.style.transform = `translateY(${(1 - easeOut(p)) * 40}px)`;
        const [v, suf] = RES[i]!;
        const n = v * easeOut(clamp01((t - l.start) / 1.1));
        c.querySelector("b")!.textContent = (Number.isInteger(v) ? fmt(Math.round(n)) : n.toFixed(1).replace(".", ",")) + suf;
      });
    }
    // cierre
    if (+closing.style.opacity > 0) {
      const L = ci.lineas;
      const show = (sel: string, t0: number) => {
        const e = closing.querySelector<HTMLElement>(sel)!;
        const p = easeOut(clamp01((t - t0) / 0.6));
        e.style.opacity = String(p);
        e.style.transform = `translateY(${(1 - p) * 24}px)`;
      };
      show(".logo", ci.start + 0.2); show(".l1", L[0]!.start + 0.6); show(".l2", L[1]!.start); show(".cta", L[2]!.start - 0.2); show(".url", L[2]!.start + 0.3);
    }
    // rótulos
    const area = G.escenas.find((g) => g.id === cur.id)?.area;
    const kick = area ? `Los 40 agentes · ${AREA[area as Area].label}` : (KICK[cur.id] ?? "");
    if (kick !== lastKick) { kicker.innerHTML = kick ? `<i></i>${kick}` : ""; lastKick = kick; }
    kicker.style.opacity = kick ? String(win(t, cur.start, cur.end, 0.35)) : "0";
    areaChips.style.opacity = area ? String(win(t, cur.start, cur.end, 0.35)) : "0";
    areaChips.querySelectorAll("span").forEach((s, i) => s.classList.toggle("on", AREA_LIST[i]!.id === area));
    const line = lineText.find((l) => t >= l.t0 && t < l.t1);
    const sub = line?.text ?? "";
    if (sub !== lastSub) { subs.textContent = sub; lastSub = sub; }
    subs.style.opacity = sub ? String(Math.min(clamp01((t - line!.t0) / 0.15), clamp01((line!.t1 - t) / 0.15))) : "0";
    const aid = line?.agent ?? "";
    if (aid !== lastCard && aid) {
      const a = ag(aid);
      const ar = AREA[a.area];
      const dest = a.va === "red" ? "Sala de equipos (pasando por el núcleo)" : STATION[a.va].label;
      card.style.setProperty("--c", ar.color);
      const ac = act(aid), sp = standPt(ac, a.va);
      card.classList.toggle("left", (ac.slot.seat.x + sp.x) / 2 > W * 0.55);
      card.innerHTML = `<div class="num">${a.id}</div><div class="info"><small>${ar.label}</small><h3>${a.titulo}${a.persona ? ' <span class="star">★ entrega a una persona</span>' : ""}</h3>
        <div class="lvl">${NIVEL[a.autonomia]}</div><div class="tools">${a.herramientas.map((x) => `<code>${x}</code>`).join("")}</div><div class="goes">Va a: <b>${dest}</b></div></div>`;
    }
    if (aid) lastCard = aid;
    const cl = lineText.find((l) => l.agent && t >= l.t0 - 0.2 && t < l.t1 + 0.3);
    card.style.opacity = cl ? String(Math.min(clamp01((t - cl.t0 + 0.2) / 0.25), clamp01((cl.t1 + 0.3 - t) / 0.25))) : "0";
    card.style.transform = `translateX(${(1 - clamp01(+card.style.opacity * 1.2)) * 30}px)`;
    prog.style.width = `${(t / T.total) * 100}%`;
  }

  // ===== reproducción =====
  const fit = () => { const s = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = `translate(-50%, -50%) scale(${s})`; };
  addEventListener("resize", fit); fit();
  const imgs = [...stage.querySelectorAll("img")];
  await Promise.all(imgs.map((im) => im.decode().catch(() => undefined)));
  await document.fonts.ready;
  render(RENDER ? 0 : 7.6); // en la web, la portada hace de cartel
  const w = window as unknown as { __seek: (t: number) => void; __total: number; __ready: boolean };
  w.__seek = (t: number) => render(t);
  w.__total = T.total;
  w.__ready = true;
  if (RENDER) { $("#play").remove(); return; }
  const audio = $<HTMLAudioElement>("#audio");
  const play = $("#play");
  let raf = 0;
  const loop = () => { render(audio.currentTime); if (!audio.paused) raf = requestAnimationFrame(loop); };
  play.addEventListener("click", () => {
    play.classList.add("hide");
    if (audio.ended) audio.currentTime = 0;
    void audio.play().then(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(loop); });
  });
  audio.addEventListener("pause", () => { play.classList.remove("hide"); render(audio.currentTime); });
  addEventListener("keydown", (e) => { if (e.code === "Space") { e.preventDefault(); if (audio.paused) play.click(); else audio.pause(); } });
}

void boot();
