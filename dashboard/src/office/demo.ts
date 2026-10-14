// Oficina para la demo web (demo_web/), que no usa React ni la API: se compila a demo_web/oficina.js
// (npm run build:demo) y expone window.TelecoOficina. La demo le pasa cada fila de su auditoría.
import type { Tone } from "./actors";
import type { Area, StationId } from "./layout";
import { plan, type HumanEvent, type Step } from "./plan";
import { OfficeView, type HumanState } from "./view";

interface DemoAgent { id: string; name: string; area: string; level: number; persona: boolean }
interface DemoRow { agent: string; tipo: string; herramienta?: string; entrada?: string; resultado?: string; decision?: string; aprobadoPor?: string }
interface Fx { alarm?: boolean; kill?: boolean; night?: number; tickets?: number }

const FONTS = { display: '"Barlow Semi Condensed", Bahnschrift, "Arial Narrow", sans-serif', body: '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif', mono: '"IBM Plex Mono", monospace' };

function toStep(r: DemoRow): Step | null {
  const tool = r.herramienta || null;
  const base = { tool, decision: r.decision ?? "", result: r.resultado ?? "" };
  switch (r.tipo) {
    case "lectura": return { step: "lectura", ...base };
    case "acción": return { step: "accion", ...base, decision: /en cola/.test(base.decision) ? "en cola de aprobación" : base.decision };
    case "bloqueo": return { step: "bloqueo", ...base };
    case "gemelo": return { step: "gemelo", ...base };
    case "salida": return { step: "salida", ...base };
    case "tarea": return { step: "entrega", ...base, tool: null };
    case "error": return { step: "error", ...base };
    default: return null;
  }
}

export function mount(container: HTMLElement, roster: DemoAgent[]) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Oficina con los 40 agentes. Cada muñeco va al puesto de la herramienta que usa.");
  svg.style.display = "block";
  svg.style.width = "100%";
  svg.style.height = "auto";
  container.appendChild(svg);
  const view = new OfficeView(svg, roster.map((a) => ({ id: a.id, titulo: a.name, area: a.area as Area, persona: a.persona, autonomia: a.level })), FONTS);
  let humans: HumanEvent[] = [];
  let fx: Fx = {};
  const now = () => performance.now() / 1000;

  const loop = () => {
    const t = now();
    for (const a of view.actors.values()) {
      if (a.loc.k !== "desk" && t > a.freeAt + 2.2) a.home(t);
      a.trim(t);
    }
    humans = humans.filter((h) => h.t1 > t);
    const hs: Partial<Record<StationId, HumanState>> = {};
    let ring = false;
    for (const h of humans) if (h.t0 <= t) { hs[h.st] = { text: h.text, tone: h.tone }; if (h.st === "guardia") ring = true; }
    view.render(t, { ...fx, humans: hs, ring });
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);

  return {
    /** Una fila de la auditoría de la demo. */
    feed(r: DemoRow): void {
      const t = now();
      if (r.tipo === "humano") { humans.push({ st: "personas", t0: t, t1: t + 3, text: "✓ Cerrado", tone: "ok" }); return; }
      const a = view.actors.get(r.agent);
      if (!a) return;
      if (r.tipo === "acción" && r.aprobadoPor) {
        const ok = !/rechaz/.test(r.decision ?? "");
        const tone: Tone = ok ? "ok" : "crit";
        humans.push({ st: "aprobacion", t0: t, t1: t + 3, text: ok ? "✓ Aprobado" : "✗ Rechazado", tone });
        if (!ok) return;
      }
      if (r.tipo === "evento" && r.herramienta === "bus.publicar") {
        if (a.freeAt - t < 4) a.say(t, `✉ ${r.entrada ?? "evento"}`, "info", 0.9);
        return;
      }
      const s = toStep(r);
      if (s) plan(a, s, t, humans);
    },
    setFx(next: Fx): void { fx = { ...fx, ...next }; },
  };
}
