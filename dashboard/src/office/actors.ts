// Movimiento de los muñecos. Todo es función del tiempo: cada viaje se planifica con su hora de salida
// y la posición en cualquier instante se calcula, así la escena se puede pintar fotograma a fotograma.
import { GATE_X, RED_STAND_X, STATION, type Pt, type Slot, type StationId } from "./layout";

export type Loc = { k: "desk" } | { k: "st"; id: StationId } | { k: "red" } | { k: "gate" };
export type Tone = "" | "ok" | "warn" | "crit" | "info";
export interface Bubble { t0: number; t1: number; text: string; tone: Tone }
interface Seg { t0: number; t1: number; pts: Pt[]; cum: number[]; len: number; d0: number; tag: string; tone: Tone }

export interface GoOpts {
  dwell?: number; text?: string; tone?: Tone; speed?: number; dur?: number;
  gate?: { text?: string; tone?: Tone; dwell?: number };
}
export interface Pose { p: Pt; walking: boolean; dist: number; tag: string; tone: Tone }

const SPEED = 320;

function locKey(l: Loc): string {
  return l.k === "st" ? `st:${l.id}` : l.k;
}

export class Actor {
  segs: Seg[] = [];
  bubbles: Bubble[] = [];
  freeAt = 0;
  loc: Loc = { k: "desk" };
  private dist = 0;
  private last: Pt;

  constructor(readonly slot: Slot) {
    this.last = slot.seat;
  }

  /** Camino desde un sitio hasta el pasillo (en ese orden). */
  private anchors(l: Loc): Pt[] {
    const s = this.slot;
    const lane = s.lane;
    switch (l.k) {
      case "desk":
        return [s.seat, { x: s.gapX, y: s.seat.y }, { x: s.gapX, y: s.room.aisleY }, { x: s.room.doorX, y: s.room.aisleY }, { x: s.room.doorX, y: lane }];
      case "st": {
        const x = STATION[l.id].x + s.off;
        return [{ x, y: s.stand }, { x, y: lane }];
      }
      case "red": {
        const x = RED_STAND_X + s.off * 0.8;
        const y = s.room.top ? 404 : 522;
        return [{ x, y }, { x, y: lane }];
      }
      case "gate":
        return [{ x: GATE_X, y: lane }];
    }
  }

  private route(from: Loc, to: Loc): Pt[] {
    if (locKey(from) === locKey(to)) return [this.last];
    const pts = [...this.anchors(from), ...this.anchors(to).reverse()];
    return pts.filter((p, i) => i === 0 || p.x !== pts[i - 1]!.x || p.y !== pts[i - 1]!.y);
  }

  private push(t0: number, t1: number, pts: Pt[], tag: string, tone: Tone = ""): void {
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1]! + Math.hypot(pts[i]!.x - pts[i - 1]!.x, pts[i]!.y - pts[i - 1]!.y));
    const len = cum[cum.length - 1] ?? 0;
    this.segs.push({ t0, t1, pts, cum, len, d0: this.dist, tag, tone });
    this.dist += len;
    this.last = pts[pts.length - 1] ?? this.last;
  }

  private walk(t: number, pts: Pt[], speed: number, dur?: number): number {
    let len = 0;
    for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i]!.x - pts[i - 1]!.x, pts[i]!.y - pts[i - 1]!.y);
    if (len < 0.5) return t;
    const d = dur ?? len / speed;
    this.push(t, t + d, pts, "walk");
    return t + d;
  }

  private stay(t0: number, dwell: number, tag: string, text?: string, tone: Tone = ""): number {
    if (dwell <= 0) return t0;
    this.push(t0, t0 + dwell, [this.last], tag, tone);
    if (text) this.bubbles.push({ t0, t1: t0 + dwell, text, tone });
    return t0 + dwell;
  }

  /** Planifica un viaje. Si el destino es la sala de equipos, se para antes en el núcleo de control. */
  go(at: number, to: Loc, o: GoOpts = {}): number {
    let t = Math.max(at, this.freeAt);
    const speed = o.speed ?? SPEED;
    const viaGate = to.k === "red" && this.loc.k !== "red" && this.loc.k !== "gate";
    if (viaGate) {
      const pts = this.route(this.loc, { k: "gate" });
      const rest = this.anchors(to).reverse();
      const total = Math.max(1, pathLen(pts) + pathLen([pts[pts.length - 1]!, ...rest]));
      t = this.walk(t, pts, speed, o.dur !== undefined ? (o.dur * pathLen(pts)) / total : undefined);
      t = this.stay(t, o.gate?.dwell ?? 0.45, "gate", o.gate?.text, o.gate?.tone ?? "ok");
      this.loc = { k: "gate" };
      t = this.walk(t, [this.last, ...rest], speed, o.dur !== undefined ? (o.dur * pathLen([this.last, ...rest])) / total : undefined);
    } else {
      t = this.walk(t, this.route(this.loc, to), speed, o.dur);
    }
    this.loc = to;
    t = this.stay(t, o.dwell ?? 0, locKey(to), o.text, o.tone ?? "");
    this.freeAt = t;
    return t;
  }

  /** Distancia que recorrería ahora mismo hasta un sitio (para calcular a qué hora salir). */
  distTo(to: Loc): number {
    if (to.k === "red" && this.loc.k !== "red" && this.loc.k !== "gate") {
      const pts = this.route(this.loc, { k: "gate" });
      return pathLen(pts) + pathLen([pts[pts.length - 1]!, ...this.anchors(to).reverse()]);
    }
    return pathLen(this.route(this.loc, to));
  }

  /** Va al núcleo de control y se le cierra el paso: vuelve a su mesa. */
  blocked(at: number, text: string, o: { dur?: number; dwell?: number; speed?: number } = {}): number {
    const t = this.go(at, { k: "gate" }, { dwell: o.dwell ?? 1.4, text, tone: "crit", dur: o.dur, speed: o.speed });
    return t;
  }

  /** Bocadillo sin moverse (al recibir un evento, al terminar…). */
  say(at: number, text: string, tone: Tone = "", dwell = 1.6): number {
    const t = Math.max(at, this.freeAt);
    this.freeAt = this.stay(t, dwell, locKey(this.loc), text, tone);
    return this.freeAt;
  }

  home(at: number, o: GoOpts = {}): number {
    return this.go(at, { k: "desk" }, o);
  }

  pose(t: number): Pose {
    const segs = this.segs;
    if (!segs.length || t < segs[0]!.t0) return { p: this.slot.seat, walking: false, dist: 0, tag: "desk", tone: "" };
    let s = segs[segs.length - 1]!;
    for (let i = segs.length - 1; i >= 0; i--) {
      if (segs[i]!.t0 <= t) { s = segs[i]!; break; }
    }
    if (t >= s.t1 || s.pts.length < 2) {
      const p = s.pts[s.pts.length - 1]!;
      return { p, walking: false, dist: s.d0 + s.len, tag: t < s.t1 ? s.tag : "", tone: t < s.t1 ? s.tone : "" };
    }
    const d = ((t - s.t0) / (s.t1 - s.t0)) * s.len;
    let i = 1;
    while (i < s.cum.length - 1 && s.cum[i]! < d) i++;
    const a = s.pts[i - 1]!, b = s.pts[i]!;
    const segLen = s.cum[i]! - s.cum[i - 1]!;
    const f = segLen > 0 ? (d - s.cum[i - 1]!) / segLen : 1;
    return { p: { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f }, walking: true, dist: s.d0 + d, tag: "walk", tone: "" };
  }

  bubble(t: number): Bubble | null {
    for (let i = this.bubbles.length - 1; i >= 0; i--) {
      const b = this.bubbles[i]!;
      if (b.t0 <= t && t < b.t1) return b;
    }
    return null;
  }

  /** En directo: olvida lo que ya pasó para que las listas no crezcan sin fin. */
  trim(now: number): void {
    const keep = (x: { t1: number }) => x.t1 >= now - 2;
    if (this.segs.length > 40) this.segs = this.segs.filter(keep);
    if (this.bubbles.length > 20) this.bubbles = this.bubbles.filter(keep);
  }
}

function pathLen(pts: Pt[]): number {
  let len = 0;
  for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i]!.x - pts[i - 1]!.x, pts[i]!.y - pts[i - 1]!.y);
  return len;
}
