// Dibujo de la oficina en SVG. Se construye una vez y en cada fotograma solo se mueven los muñecos,
// las luces y los bocadillos.
import { Actor, type Tone } from "./actors";
import {
  AREA, GATE_X, H, LANE_BOT, LANE_TOP, RED_W, RED_X, ROOMS, STATIONS, STATION_Y, W,
  seats, type Pt, type RosterEntry, type StationId,
} from "./layout";

const NS = "http://www.w3.org/2000/svg";
type Attrs = Record<string, string | number>;
function el<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Attrs = {}, parent?: Element): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (parent) parent.appendChild(e);
  return e;
}
function txt(parent: Element, x: number, y: number, s: string, attrs: Attrs = {}): SVGTextElement {
  const t = el("text", { x, y, ...attrs }, parent);
  t.textContent = s;
  return t;
}

export const TONE: Record<Tone, string> = { "": "#c9d3dc", ok: "#5cc28a", warn: "#e3a845", crit: "#f0775c", info: "#6ea6e6" };

export interface HumanState { text?: string; tone?: Tone; busy?: boolean }
export interface Fx {
  alarm?: boolean;            // la red tiene nodos caídos
  kill?: boolean;             // interruptor general
  night?: number;             // 0..1
  focus?: string[];           // agentes resaltados
  dim?: boolean;              // apaga a los que no están resaltados
  tickets?: number;           // notas en el tablón
  humans?: Partial<Record<StationId, HumanState>>;
  twin?: Tone;                // pantalla del gemelo
  ring?: boolean;             // teléfono de guardia sonando
  stamp?: number;             // 0..1 animación del sello en Aprobaciones
  pop?: (id: string) => number; // escala de aparición de cada agente (0 = oculto)
}

interface ActorEls {
  g: SVGGElement; legL: SVGGElement; legR: SVGGElement; armL: SVGGElement; armR: SVGGElement;
  ring: SVGEllipseElement; antenna: SVGCircleElement; body: SVGGElement;
  bubble: SVGGElement; bRect: SVGRectElement; bTail: SVGPathElement; bText: SVGTextElement; bKey: string;
  screen: SVGRectElement; lastY: number;
}

let measureCtx: CanvasRenderingContext2D | null = null;
function measure(s: string, font: string): number {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return s.length * 7;
  measureCtx.font = font;
  return measureCtx.measureText(s).width;
}

export interface ViewOpts { display: string; body: string; mono: string }

export class OfficeView {
  readonly actors = new Map<string, Actor>();
  private els = new Map<string, ActorEls>();
  private actorLayer: SVGGElement;
  private bubbleLayer: SVGGElement;
  private night: SVGRectElement;
  private leds: SVGCircleElement[] = [];
  private beams: SVGRectElement[] = [];
  private gatePanel: SVGRectElement;
  private notes: SVGRectElement[] = [];
  private twinScreen: SVGRectElement;
  private phoneRings: SVGGElement;
  private stampG: SVGGElement;
  private humanBubbles = new Map<StationId, { g: SVGGElement; rect: SVGRectElement; tail: SVGPathElement; text: SVGTextElement; key: string; x: number; y: number }>();
  private killBanner: SVGGElement;
  private order = "";
  readonly root: SVGGElement;

  constructor(readonly svg: SVGSVGElement, roster: RosterEntry[], private o: ViewOpts) {
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = "";
    this.root = el("g", {}, svg);
    const floor = el("g", {}, this.root);
    this.drawFloor(floor);
    const slots = seats(roster);
    const deskLayer = el("g", {}, this.root);
    const screens = new Map<string, SVGRectElement>();
    for (const s of slots) screens.set(s.id, this.drawDesk(deskLayer, s.desk, s.id, s.titulo, s.color, s.persona));
    const stations = el("g", {}, this.root);
    for (const st of STATIONS) this.drawStation(stations, st.id, st.x, st.label, st.human);
    this.gatePanel = el("rect", {}, stations);
    this.twinScreen = el("rect", {}, stations);
    this.phoneRings = el("g", {}, stations);
    this.stampG = el("g", {}, stations);
    this.drawRed(stations);
    this.drawGate(stations);
    this.drawSpecials();
    this.actorLayer = el("g", {}, this.root);
    this.night = el("rect", { x: 0, y: 0, width: W, height: H, fill: "#040913", opacity: 0, "pointer-events": "none" }, this.root);
    this.bubbleLayer = el("g", {}, this.root);
    this.killBanner = el("g", { opacity: 0 }, this.root);
    el("rect", { x: W / 2 - 300, y: STATION_Y - 34, width: 600, height: 68, rx: 12, fill: "#3a1b14", stroke: "#f0775c", "stroke-width": 3 }, this.killBanner);
    txt(this.killBanner, W / 2, STATION_Y + 10, "INTERRUPTOR GENERAL · TODOS EN NIVEL 0", { "text-anchor": "middle", fill: "#ffd9cf", "font-family": o.display, "font-size": 26, "font-weight": 700 });
    for (const s of slots) {
      const a = new Actor(s);
      this.actors.set(s.id, a);
      this.els.set(s.id, this.drawActor(s.id, s.color, s.persona, screens.get(s.id)!));
    }
    for (const st of STATIONS.filter((x) => x.human)) {
      const g = el("g", { opacity: 0 }, this.bubbleLayer);
      const rect = el("rect", { rx: 8, "stroke-width": 2 }, g);
      const tail = el("path", { "stroke-width": 2 }, g);
      const text = el("text", { "font-family": o.body, "font-size": 14, "font-weight": 600, fill: "#0f1722" }, g);
      this.humanBubbles.set(st.id, { g, rect, tail, text, key: "", x: st.x + 26, y: STATION_Y - 40 });
    }
  }

  // ---------- estáticos ----------
  private drawFloor(g: SVGGElement): void {
    const defs = el("defs", {}, this.svg);
    const pat = el("pattern", { id: "tiles", width: 40, height: 40, patternUnits: "userSpaceOnUse" }, defs);
    el("path", { d: "M40 0H0V40", fill: "none", stroke: "#ffffff", "stroke-opacity": 0.035 }, pat);
    const glow = el("radialGradient", { id: "glow" }, defs);
    el("stop", { offset: "0%", "stop-color": "#ffffff", "stop-opacity": 0.9 }, glow);
    el("stop", { offset: "100%", "stop-color": "#ffffff", "stop-opacity": 0 }, glow);
    el("rect", { x: 0, y: 0, width: W, height: H, fill: "#0f161f" }, g);
    el("rect", { x: 0, y: 296, width: W, height: 308, fill: "#16202b" }, g);
    el("rect", { x: 0, y: 296, width: W, height: 308, fill: "url(#tiles)" }, g);
    for (const y of [LANE_TOP, LANE_BOT]) el("line", { x1: 24, x2: RED_X, y1: y, y2: y, stroke: "#ffffff", "stroke-opacity": 0.06, "stroke-width": 2, "stroke-dasharray": "14 12" }, g);
    for (const r of ROOMS) {
      const a = AREA[r.area];
      el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, rx: 14, fill: "#1a2531", stroke: "#2c3a49", "stroke-width": 2 }, g);
      el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, rx: 14, fill: a.color, opacity: 0.05 }, g);
      el("rect", { x: r.x + 14, y: r.y + 12, width: 6, height: 20, rx: 3, fill: a.color }, g);
      txt(g, r.x + 28, r.y + 28, a.label.toUpperCase(), { fill: "#e9eef3", "font-family": this.o.display, "font-size": 17, "font-weight": 700, "letter-spacing": 1 });
      // puerta al pasillo
      el("rect", { x: r.doorX - 22, y: r.top ? r.y + r.h - 4 : r.y - 2, width: 44, height: 6, fill: "#16202b" }, g);
      el("rect", { x: r.doorX - 24, y: r.top ? r.y + r.h - 3 : r.y - 3, width: 4, height: 6, fill: a.color }, g);
      el("rect", { x: r.doorX + 20, y: r.top ? r.y + r.h - 3 : r.y - 3, width: 4, height: 6, fill: a.color }, g);
    }
  }

  private drawDesk(g: SVGGElement, d: Pt, id: string, titulo: string, color: string, persona: boolean): SVGRectElement {
    el("rect", { x: d.x - 30, y: d.y - 4, width: 60, height: 16, rx: 3, fill: "#2b3948" }, g);
    el("rect", { x: d.x - 14, y: d.y - 24, width: 28, height: 19, rx: 3, fill: "#0c121a", stroke: "#3b4b5d" }, g);
    const screen = el("rect", { x: d.x - 11, y: d.y - 21, width: 22, height: 13, rx: 1.5, fill: color, opacity: 0.25 }, g);
    el("rect", { x: d.x - 2, y: d.y - 5, width: 4, height: 2, fill: "#3b4b5d" }, g);
    void id;
    const short = titulo.length > 18 ? `${titulo.slice(0, 17)}…` : titulo;
    txt(g, d.x, d.y + 61, short, { "text-anchor": "middle", fill: "#a3b1bf", "font-family": this.o.body, "font-size": 10, "font-weight": 500 });
    if (persona) txt(g, d.x + 26, d.y + 8, "★", { fill: "#f5c542", "font-size": 11, "text-anchor": "middle" });
    return screen;
  }

  private human(g: SVGGElement, x: number, y: number, shirt: string): void {
    el("rect", { x: x - 12, y: y - 22, width: 24, height: 24, rx: 9, fill: shirt }, g);
    el("path", { d: `M${x - 4} ${y - 22} L${x} ${y - 12} L${x + 4} ${y - 22}`, stroke: "#e9eef3", "stroke-width": 1.6, fill: "none" }, g);
    el("rect", { x: x - 3.5, y: y - 13, width: 7, height: 8, rx: 1.5, fill: "#e9eef3" }, g);
    el("circle", { cx: x, cy: y - 32, r: 9.5, fill: "#f1c7a0" }, g);
    el("path", { d: `M${x - 9.8} ${y - 33} A9.8 9.8 0 0 1 ${x + 9.8} ${y - 33} Q${x + 4} ${y - 37} ${x - 9.8} ${y - 33}Z`, fill: "#3b2a20" }, g);
  }

  private plate(g: SVGGElement, x: number, label: string, human: boolean): void {
    const w = measure(label, `600 11px ${this.o.body}`) + 16 + (human ? 14 : 0);
    el("rect", { x: x - w / 2, y: STATION_Y + 36, width: w, height: 18, rx: 9, fill: "#0c121a", stroke: "#33414f" }, g);
    txt(g, x + (human ? 7 : 0), STATION_Y + 49, label, { "text-anchor": "middle", fill: "#d5dde5", "font-family": this.o.body, "font-size": 11, "font-weight": 600 });
    if (human) {
      const hx = x - w / 2 + 11;
      el("circle", { cx: hx, cy: STATION_Y + 42, r: 2.6, fill: "#f1c7a0" }, g);
      el("path", { d: `M${hx - 4} ${STATION_Y + 50} Q${hx} ${STATION_Y + 44} ${hx + 4} ${STATION_Y + 50}Z`, fill: "#f1c7a0" }, g);
    }
  }

  private desk(g: SVGGElement, x: number): void {
    el("rect", { x: x - 50, y: STATION_Y - 2, width: 100, height: 30, rx: 4, fill: "#3a4858" }, g);
    el("rect", { x: x - 50, y: STATION_Y - 2, width: 100, height: 5, rx: 2, fill: "#4b5b6d" }, g);
  }

  private drawStation(g: SVGGElement, id: StationId, x: number, label: string, human: boolean): void {
    const y = STATION_Y;
    const s = el("g", {}, g);
    switch (id) {
      case "direccion":
        el("rect", { x: x - 48, y: y - 44, width: 96, height: 58, rx: 5, fill: "#0c121a", stroke: "#3b4b5d", "stroke-width": 2 }, s);
        [0.5, 0.8, 0.35, 0.95, 0.65].forEach((h, i) => el("rect", { x: x - 38 + i * 15, y: y + 6 - h * 40, width: 10, height: h * 40, rx: 2, fill: ["#e8743b", "#4aa3df", "#4fbf84", "#9b7be0", "#e3b341"][i]!, opacity: 0.85 }, s));
        el("rect", { x: x - 4, y: y + 14, width: 8, height: 16, fill: "#3b4b5d" }, s);
        break;
      case "negocio":
        this.desk(s, x);
        el("rect", { x: x - 36, y: y - 20, width: 30, height: 20, rx: 3, fill: "#8a6a45" }, s);
        el("rect", { x: x - 27, y: y - 25, width: 12, height: 6, rx: 2, fill: "none", stroke: "#8a6a45", "stroke-width": 2.5 }, s);
        for (let i = 0; i < 4; i++) el("ellipse", { cx: x + 22, cy: y - 4 - i * 5, rx: 11, ry: 3.5, fill: "#e3b341", stroke: "#a8801f" }, s);
        el("rect", { x: x + 2, y: y - 14, width: 14, height: 12, fill: "#e9eef3", transform: `rotate(-8 ${x + 9} ${y - 8})` }, s);
        break;
      case "exterior":
        el("rect", { x: x - 48, y: y - 46, width: 96, height: 64, rx: 5, fill: "#1f3b57", stroke: "#4b5b6d", "stroke-width": 3 }, s);
        el("circle", { cx: x - 24, cy: y - 26, r: 9, fill: "#f5c542" }, s);
        el("path", { d: `M${x - 6} ${y - 12} q4 -12 14 -8 q6 -10 16 -2 q10 0 8 10 z`, fill: "#e9eef3", opacity: 0.9 }, s);
        el("path", { d: `M${x + 30} ${y + 14} L${x + 36} ${y - 30} L${x + 42} ${y + 14} M${x + 31} ${y - 14} H${x + 41} M${x + 33} ${y - 24} H${x + 39}`, stroke: "#9aa7b4", "stroke-width": 2, fill: "none" }, s);
        el("path", { d: `M${x - 44} ${y + 12} L${x - 30} ${y + 2} L${x - 18} ${y + 8} L${x - 4} ${y - 4}`, stroke: "#5cc28a", "stroke-width": 2.5, fill: "none" }, s);
        el("line", { x1: x, x2: x, y1: y - 46, y2: y + 18, stroke: "#4b5b6d", "stroke-width": 3 }, s);
        break;
      case "archivo":
        for (let i = 0; i < 3; i++) {
          const cx = x - 46 + i * 32;
          el("rect", { x: cx, y: y - 44, width: 28, height: 74, rx: 3, fill: "#3a4858", stroke: "#4b5b6d" }, s);
          for (let k = 0; k < 3; k++) {
            el("line", { x1: cx + 3, x2: cx + 25, y1: y - 20 + k * 24, y2: y - 20 + k * 24, stroke: "#2b3948", "stroke-width": 2 }, s);
            el("rect", { x: cx + 9, y: y - 36 + k * 24, width: 10, height: 4, rx: 2, fill: "#9aa7b4" }, s);
          }
        }
        break;
      case "personas":
        this.human(s, x + 26, y, "#5d6b7a");
        this.desk(s, x);
        el("rect", { x: x - 42, y: y - 12, width: 34, height: 12, rx: 2, fill: "#6b5a45" }, s);
        for (let i = 0; i < 3; i++) el("rect", { x: x - 39, y: y - 15 - i * 3, width: 28, height: 3, fill: "#e9eef3" }, s);
        break;
      case "guardia":
        this.human(s, x + 26, y, "#2f6d5a");
        this.desk(s, x);
        el("rect", { x: x - 34, y: y - 12, width: 26, height: 12, rx: 4, fill: "#15202a" }, s);
        el("path", { d: `M${x - 38} ${y - 14} q0 -10 9 -10 h8 q9 0 9 10`, stroke: "#15202a", "stroke-width": 5, fill: "none", "stroke-linecap": "round" }, s);
        break;
      case "tickets":
        el("rect", { x: x - 50, y: y - 46, width: 100, height: 72, rx: 4, fill: "#7a5a3a", stroke: "#5a4128", "stroke-width": 3 }, s);
        for (let i = 0; i < 8; i++) {
          const n = el("rect", { x: x - 42 + (i % 4) * 22, y: y - 38 + Math.floor(i / 4) * 28, width: 17, height: 20, rx: 1.5, fill: ["#f5d76e", "#f0a35e", "#f0775c", "#f5d76e"][i % 4]!, opacity: i < 3 ? 1 : 0 }, s);
          this.notes.push(n);
        }
        break;
      case "aprobacion":
        this.human(s, x + 26, y, "#1c5ea6");
        this.desk(s, x);
        el("rect", { x: x - 40, y: y - 6, width: 30, height: 6, fill: "#e9eef3" }, s);
        break;
      case "gemelo": {
        el("rect", { x: x - 50, y: y + 6, width: 100, height: 22, rx: 4, fill: "#2b3948" }, s);
        el("rect", { x: x - 46, y: y - 46, width: 92, height: 50, rx: 5, fill: "#0b2a31", stroke: "#3fd0d8", "stroke-width": 2 }, s);
        const nodes: [number, number][] = [[-30, -30], [-8, -36], [16, -26], [32, -34], [-22, -12], [6, -10], [28, -12]];
        for (const [a, b] of [[0, 1], [1, 2], [2, 3], [0, 4], [4, 5], [5, 6], [2, 6], [1, 5]] as const) {
          el("line", { x1: x + nodes[a]![0], y1: y + nodes[a]![1], x2: x + nodes[b]![0], y2: y + nodes[b]![1], stroke: "#3fd0d8", "stroke-width": 1.4, opacity: 0.7 }, s);
        }
        for (const [nx, ny] of nodes) el("circle", { cx: x + nx, cy: y + ny, r: 3, fill: "#9ff3f7" }, s);
        break;
      }
    }
    this.plate(s, x, label, human);
  }

  private drawRed(g: SVGGElement): void {
    el("rect", { x: RED_X, y: 312, width: RED_W, height: 276, rx: 14, fill: "#121b25", stroke: "#3b4b5d", "stroke-width": 2 }, g);
    txt(g, RED_X + RED_W / 2, 590 - 10, "SALA DE EQUIPOS · LA RED", { "text-anchor": "middle", fill: "#93a2b1", "font-family": this.o.display, "font-size": 12, "font-weight": 700, "letter-spacing": 1 });
    for (let i = 0; i < 3; i++) {
      const x = RED_X + 18 + i * 42;
      el("rect", { x, y: 422, width: 32, height: 80, rx: 3, fill: "#0b1118", stroke: "#3b4b5d" }, g);
      for (let k = 0; k < 7; k++) {
        el("rect", { x: x + 4, y: 428 + k * 10.5, width: 24, height: 7, rx: 1, fill: "#1e2b38" }, g);
        this.leds.push(el("circle", { cx: x + 23, cy: 431.5 + k * 10.5, r: 2, fill: "#5cc28a" }, g));
      }
    }
  }

  private drawGate(g: SVGGElement): void {
    for (const lane of [LANE_TOP, LANE_BOT]) {
      this.beams.push(el("rect", { x: GATE_X - 5, y: lane - 32, width: 10, height: 64, rx: 5, fill: "#6b7b8c", opacity: 0.35 }, g));
      el("rect", { x: GATE_X - 9, y: lane - 40, width: 18, height: 8, rx: 3, fill: "#4b5b6d" }, g);
      el("rect", { x: GATE_X - 9, y: lane + 32, width: 18, height: 8, rx: 3, fill: "#4b5b6d" }, g);
    }
    el("rect", { x: GATE_X - 17, y: LANE_TOP + 44, width: 34, height: LANE_BOT - LANE_TOP - 88, rx: 8, fill: "#0c121a", stroke: "#e8743b", "stroke-width": 2.5 }, g);
    txt(g, GATE_X, STATION_Y, "NÚCLEO DE CONTROL", {
      "text-anchor": "middle", "dominant-baseline": "middle", fill: "#f3efe7", "font-family": this.o.display, "font-size": 13, "font-weight": 700,
      "letter-spacing": 1.5, transform: `rotate(-90 ${GATE_X} ${STATION_Y})`,
    });
  }

  private drawSpecials(): void {
    const gx = GATE_X;
    this.gatePanel.setAttribute("x", String(gx - 17));
    this.gatePanel.setAttribute("y", String(LANE_TOP + 44));
    this.gatePanel.setAttribute("width", "34");
    this.gatePanel.setAttribute("height", String(LANE_BOT - LANE_TOP - 88));
    this.gatePanel.setAttribute("rx", "8");
    this.gatePanel.setAttribute("fill", "#e8743b");
    this.gatePanel.setAttribute("opacity", "0");
    const tw = STATIONS.find((s) => s.id === "gemelo")!.x;
    for (const [k, v] of Object.entries({ x: tw - 46, y: STATION_Y - 46, width: 92, height: 50, rx: 5, fill: "#5cc28a", opacity: 0 })) this.twinScreen.setAttribute(k, String(v));
    const gx2 = STATIONS.find((s) => s.id === "guardia")!.x - 21;
    for (let i = 0; i < 2; i++) el("path", { d: `M${gx2 - 14 - i * 6} ${STATION_Y - 30 - i * 4} q-6 8 0 16 M${gx2 + 14 + i * 6} ${STATION_Y - 30 - i * 4} q6 8 0 16`, stroke: "#f5c542", "stroke-width": 2.2, fill: "none" }, this.phoneRings);
    this.phoneRings.setAttribute("opacity", "0");
    const ax = STATIONS.find((s) => s.id === "aprobacion")!.x;
    el("rect", { x: ax - 34, y: STATION_Y - 30, width: 16, height: 10, rx: 2, fill: "#b8381f" }, this.stampG);
    el("rect", { x: ax - 29, y: STATION_Y - 44, width: 6, height: 15, rx: 2, fill: "#6b4a2a" }, this.stampG);
    el("circle", { cx: ax - 26, cy: STATION_Y - 46, r: 5, fill: "#6b4a2a" }, this.stampG);
  }

  private drawActor(id: string, color: string, persona: boolean, screen: SVGRectElement): ActorEls {
    const g = el("g", {}, this.actorLayer);
    el("ellipse", { cx: 0, cy: 0, rx: 12, ry: 4, fill: "#000", opacity: 0.35 }, g);
    const ring = el("ellipse", { cx: 0, cy: 0, rx: 21, ry: 7.5, fill: "none", stroke: color, "stroke-width": 3, opacity: 0 }, g);
    const legL = el("g", {}, g);
    el("rect", { x: -6.5, y: -15, width: 5.5, height: 15, rx: 2.5, fill: "#3a4656" }, legL);
    const legR = el("g", {}, g);
    el("rect", { x: 1, y: -15, width: 5.5, height: 15, rx: 2.5, fill: "#3a4656" }, legR);
    const body = el("g", {}, g);
    const armL = el("g", {}, body);
    el("rect", { x: -15.5, y: -31, width: 5, height: 13, rx: 2.5, fill: color }, armL);
    const armR = el("g", {}, body);
    el("rect", { x: 10.5, y: -31, width: 5, height: 13, rx: 2.5, fill: color }, armR);
    el("rect", { x: -11, y: -34, width: 22, height: 21, rx: 7, fill: color }, body);
    txt(body, 0, -19.5, String(Number(id)), { "text-anchor": "middle", fill: "#0f1722", "font-family": this.o.display, "font-size": 10, "font-weight": 700 });
    if (persona) {
      el("circle", { cx: 9, cy: -31, r: 5, fill: "#f5c542", stroke: "#0f1722", "stroke-width": 1 }, body);
      txt(body, 9, -28.6, "★", { "text-anchor": "middle", fill: "#0f1722", "font-size": 7 });
    }
    el("rect", { x: -10, y: -53, width: 20, height: 17, rx: 6, fill: "#e8eef4", stroke: "#b9c6d3" }, body);
    el("rect", { x: -7, y: -48, width: 14, height: 6, rx: 3, fill: "#13202c" }, body);
    el("circle", { cx: -3.2, cy: -45, r: 1.5, fill: color }, body);
    el("circle", { cx: 3.2, cy: -45, r: 1.5, fill: color }, body);
    el("line", { x1: 0, y1: -53, x2: 0, y2: -59, stroke: "#b9c6d3", "stroke-width": 1.6 }, body);
    const antenna = el("circle", { cx: 0, cy: -60.5, r: 2.8, fill: color }, body);
    const bubble = el("g", { opacity: 0 }, this.bubbleLayer);
    const bRect = el("rect", { rx: 8, "stroke-width": 2 }, bubble);
    const bTail = el("path", { "stroke-width": 2 }, bubble);
    const bText = el("text", { "font-family": this.o.body, "font-size": 13, "font-weight": 600, fill: "#0f1722" }, bubble);
    return { g, legL, legR, armL, armR, ring, antenna, body, bubble, bRect, bTail, bText, bKey: "", screen, lastY: 0 };
  }

  private paintBubble(b: { rect: SVGRectElement; tail: SVGPathElement; text: SVGTextElement }, text: string, tone: Tone, size: number): void {
    const wTxt = measure(text, `600 ${size}px ${this.o.body}`);
    const w = wTxt + 18, h = size + 13;
    b.rect.setAttribute("x", String(-w / 2));
    b.rect.setAttribute("y", String(-h - 8));
    b.rect.setAttribute("width", String(w));
    b.rect.setAttribute("height", String(h));
    b.rect.setAttribute("fill", "#f7f9fa");
    b.rect.setAttribute("stroke", TONE[tone]);
    b.tail.setAttribute("d", "M-6 -9 L0 0 L6 -9");
    b.tail.setAttribute("fill", "#f7f9fa");
    b.tail.setAttribute("stroke", TONE[tone]);
    b.text.setAttribute("x", String(-wTxt / 2));
    b.text.setAttribute("y", String(-8 - h / 2 + size * 0.36));
    b.text.textContent = text;
  }

  // ---------- fotograma ----------
  render(t: number, fx: Fx = {}): void {
    let gateTone: Tone = "";
    const ys: [number, string][] = [];
    const focus = new Set(fx.focus ?? []);
    for (const [id, a] of this.actors) {
      const e = this.els.get(id)!;
      const pose = a.pose(t);
      const swing = pose.walking ? Math.sin(pose.dist / 7) * 30 : 0;
      const bob = pose.walking ? Math.abs(Math.sin(pose.dist / 7)) * -1.6 : 0;
      const sc = fx.pop ? fx.pop(id) : 1;
      e.g.setAttribute("transform", `translate(${pose.p.x.toFixed(1)} ${pose.p.y.toFixed(1)}) scale(${sc.toFixed(3)})`);
      e.g.style.display = sc <= 0.001 ? "none" : "";
      e.legL.setAttribute("transform", `rotate(${swing.toFixed(1)} -3.7 -15)`);
      e.legR.setAttribute("transform", `rotate(${(-swing).toFixed(1)} 3.7 -15)`);
      e.armL.setAttribute("transform", `rotate(${(-swing * 0.8).toFixed(1)} -13 -30)`);
      e.armR.setAttribute("transform", `rotate(${(swing * 0.8).toFixed(1)} 13 -30)`);
      e.body.setAttribute("transform", `translate(0 ${bob.toFixed(2)})`);
      if (pose.tag === "gate" && pose.tone) gateTone = pose.tone;
      const atDesk = !pose.walking && Math.abs(pose.p.x - a.slot.seat.x) < 1 && Math.abs(pose.p.y - a.slot.seat.y) < 1;
      const isFocus = focus.has(id);
      const busy = !atDesk || isFocus;
      e.antenna.setAttribute("opacity", busy ? String(0.55 + 0.45 * Math.abs(Math.sin(t * 6 + Number(id)))) : "0.45");
      e.screen.setAttribute("opacity", atDesk ? "0.55" : "0.12");
      e.ring.setAttribute("opacity", isFocus ? String(0.55 + 0.45 * Math.sin(t * 5)) : "0");
      e.g.setAttribute("opacity", fx.dim && focus.size && !isFocus ? "0.28" : "1");
      ys.push([pose.p.y, id]);
      const b = a.bubble(t);
      if (b) {
        const key = `${b.text}|${b.tone}`;
        if (key !== e.bKey) { this.paintBubble({ rect: e.bRect, tail: e.bTail, text: e.bText }, b.text, b.tone, 13); e.bKey = key; }
        const k = Math.min(1, (t - b.t0) / 0.18, (b.t1 - t) / 0.18);
        e.bubble.setAttribute("opacity", String(Math.max(0, k)));
        e.bubble.setAttribute("transform", `translate(${pose.p.x.toFixed(1)} ${(pose.p.y - 66 - (1 - k) * 6).toFixed(1)})`);
      } else e.bubble.setAttribute("opacity", "0");
    }
    // orden de pintado por profundidad
    ys.sort((p, q) => p[0] - q[0]);
    const order = ys.map((y) => y[1]).join(",");
    if (order !== this.order) {
      for (const [, id] of ys) this.actorLayer.appendChild(this.els.get(id)!.g);
      this.order = order;
    }
    // núcleo de control
    const gc = fx.kill ? TONE.crit : gateTone ? TONE[gateTone] : "#6b7b8c";
    for (const b of this.beams) { b.setAttribute("fill", gc); b.setAttribute("opacity", gateTone || fx.kill ? "0.75" : "0.3"); }
    this.gatePanel.setAttribute("fill", gc);
    this.gatePanel.setAttribute("opacity", gateTone || fx.kill ? "0.28" : "0");
    // red
    this.leds.forEach((l, i) => {
      const bad = fx.alarm && (i % 3 === 0 || i % 5 === 1);
      l.setAttribute("fill", bad ? (Math.sin(t * 9 + i) > 0 ? "#f0775c" : "#5a1f14") : (Math.sin(t * 3 + i * 1.7) > 0.85 ? "#9ff3c0" : "#5cc28a"));
    });
    // tablón de tickets
    const nNotes = fx.tickets ?? 3;
    this.notes.forEach((n, i) => n.setAttribute("opacity", i < nNotes ? "1" : "0"));
    // gemelo
    this.twinScreen.setAttribute("fill", fx.twin ? TONE[fx.twin] : "#5cc28a");
    this.twinScreen.setAttribute("opacity", fx.twin ? String(0.25 + 0.15 * Math.sin(t * 8)) : "0");
    // guardia y sello
    this.phoneRings.setAttribute("opacity", fx.ring ? (Math.sin(t * 14) > 0 ? "1" : "0.2") : "0");
    const st = fx.stamp ?? 0;
    const lift = st > 0 ? Math.sin(Math.min(1, st) * Math.PI) * -16 : 0;
    this.stampG.setAttribute("transform", `translate(0 ${lift.toFixed(1)})`);
    // personas
    for (const [sid, hb] of this.humanBubbles) {
      const h = fx.humans?.[sid];
      if (h?.text) {
        const key = `${h.text}|${h.tone ?? ""}`;
        if (key !== hb.key) { this.paintBubble(hb, h.text, h.tone ?? "info", 14); hb.key = key; }
        hb.g.setAttribute("opacity", "1");
        hb.g.setAttribute("transform", `translate(${hb.x} ${hb.y})`);
      } else hb.g.setAttribute("opacity", "0");
    }
    this.night.setAttribute("opacity", String((fx.night ?? 0) * 0.42));
    this.killBanner.setAttribute("opacity", fx.kill ? "1" : "0");
    this.actorLayer.style.filter = fx.kill ? "grayscale(1) brightness(.8)" : "";
  }
}
