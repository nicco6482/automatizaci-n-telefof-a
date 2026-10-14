// De un paso de auditoría a un movimiento en la oficina: a qué puesto va el agente y qué dice al llegar.
// Lo usan el panel real (auditoría de la API) y la demo web (auditoría del motor en el navegador).
import type { Actor, Loc, Tone } from "./actors";
import { STATION, stationFor, type StationId } from "./layout";

export interface Step { step: string; tool: string | null; decision: string; result: string; topic?: string }
export interface HumanEvent { st: StationId; t0: number; t1: number; text: string; tone: Tone }
export interface Planned { place: string; text: string; tone: Tone }

export const PLACE: Record<StationId | "red" | "desk" | "gate", string> = {
  ...(Object.fromEntries(Object.values(STATION).map((s) => [s.id, s.label])) as Record<StationId, string>),
  red: "Sala de equipos", desk: "su mesa", gate: "Núcleo de control",
};

export const cut = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const toLoc = (d: StationId | "red"): Loc => (d === "red" ? { k: "red" } : { k: "st", id: d });

export function plan(a: Actor, r: Step, now: number, humans: HumanEvent[]): Planned | null {
  const short = r.tool ? r.tool.split(".").slice(1).join(".") || r.tool : "";
  const dest = stationFor(r.tool);
  const d = r.decision;
  const busy = a.freeAt - now > 7;
  const arrive = (end: number, dwell: number, st: StationId, text: string, tone: Tone = "info") => {
    if (STATION[st].human) humans.push({ st, t0: end - dwell, t1: end + 0.8, text, tone });
  };
  switch (r.step) {
    case "evento":
      if (busy) return null;
      a.say(now, `✉ ${r.topic ?? "evento"}`, "info", 1.0);
      return { place: PLACE.desk, text: `recibe ${r.topic ?? "un evento"}`, tone: "info" };
    case "lectura":
      if (!dest || busy) return null;
      a.go(now, toLoc(dest), { dwell: 0.9, text: `lee ${cut(short, 26)}` });
      return { place: PLACE[dest], text: `lee ${short}`, tone: "" };
    case "accion": {
      if (/bloquead/.test(d)) { a.blocked(now, `✗ ${cut(short, 22)}: bloqueada`); return { place: PLACE.gate, text: `${short}: bloqueada`, tone: "crit" }; }
      if (/cola/.test(d)) {
        const end = a.go(now, { k: "st", id: "aprobacion" }, { dwell: 1.5, text: `${cut(short, 22)} → aprobación`, tone: "warn" });
        arrive(end, 1.5, "aprobacion", "Lo reviso", "warn");
        return { place: PLACE.aprobacion, text: `${short} en cola de aprobación`, tone: "warn" };
      }
      if (/propuesta|pausa/.test(d)) { a.blocked(now, `${cut(short, 22)}: ${d}`); return { place: PLACE.gate, text: `${short}: ${d}`, tone: "warn" }; }
      if (!dest) return null;
      const end = a.go(now, toLoc(dest), { dwell: 1.3, text: `✓ ${cut(short, 26)}`, tone: "ok", gate: { tone: "ok" } });
      if (dest !== "red") arrive(end, 1.3, dest, dest === "guardia" ? "¡Voy!" : "Recibido");
      return { place: PLACE[dest], text: `${short}: ${d}`, tone: "ok" };
    }
    case "entrega": {
      const st: StationId = dest === "direccion" ? "direccion" : "personas";
      const end = a.go(now, { k: "st", id: st }, { dwell: 1.5, text: "borrador para una persona", tone: "info" });
      arrive(end, 1.5, st, "Lo firmo yo");
      return { place: PLACE[st], text: `entrega ${short || "un borrador"}`, tone: "info" };
    }
    case "gemelo": {
      const ok = /ok/.test(d) && !/ko/.test(d);
      a.go(now, { k: "st", id: "gemelo" }, { dwell: 1.4, text: ok ? "gemelo ✓" : "gemelo ✗", tone: ok ? "ok" : "crit" });
      return { place: PLACE.gemelo, text: ok ? "el gemelo acepta el cambio" : "el gemelo rechaza el cambio", tone: ok ? "ok" : "crit" };
    }
    case "bloqueo":
      a.blocked(now, "✗ bloqueado por el núcleo");
      return { place: PLACE.gate, text: cut(r.result, 80), tone: "crit" };
    case "aprobacion":
      humans.push({ st: "aprobacion", t0: now, t1: now + 3, text: d === "aprobada" ? "✓ Aprobado" : "✗ Rechazado", tone: d === "aprobada" ? "ok" : "crit" });
      return { place: PLACE.aprobacion, text: `una persona: ${d}`, tone: d === "aprobada" ? "ok" : "crit" };
    case "salida":
      a.home(now, { dwell: 2.2, text: cut(r.result || "listo", 44), tone: "ok" });
      return { place: PLACE.desk, text: cut(r.result, 110), tone: "ok" };
    case "error":
      a.say(now, "error", "crit", 1.5);
      return { place: PLACE.desk, text: cut(r.result, 80), tone: "crit" };
    default:
      return null;
  }
}
