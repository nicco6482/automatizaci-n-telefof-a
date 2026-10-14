// Oficina en directo: cada muñeco es un agente. Cuando la auditoría registra un paso, el agente
// se levanta y va al puesto de la herramienta que usa; para tocar la red pasa por el núcleo de control.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Agent, type Control, type Summary } from "./api";
import type { Tone } from "./office/actors";
import { AREA_LIST, type Area, type StationId } from "./office/layout";
import { plan, type HumanEvent } from "./office/plan";
import { OfficeView, type HumanState } from "./office/view";

const FONTS = { display: '"Barlow Semi Condensed", "Arial Narrow", sans-serif', body: '"IBM Plex Sans", system-ui, sans-serif', mono: '"IBM Plex Mono", monospace' };
interface FeedItem { key: number; at: string; who: string; color: string; place: string; text: string; tone: Tone }

export default function Office({ control, summary, controls }: { control: Control | null; summary: Summary | null; controls: ReactNode }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const viewRef = useRef<OfficeView | null>(null);
  const lastId = useRef<number | null>(null);
  const humans = useRef<HumanEvent[]>([]);
  const fxRef = useRef({ alarm: false, kill: false, night: 0, tickets: 0 });
  const [agents, setAgents] = useState<Agent[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);

  useEffect(() => { api.agents().then(setAgents).catch(() => undefined); }, []);

  useEffect(() => {
    if (!svgRef.current || !agents.length) return;
    viewRef.current = new OfficeView(svgRef.current, agents.map((a) => ({ id: a.id, titulo: a.titulo, area: a.area as Area, persona: a.persona, autonomia: a.autonomia })), FONTS);
    let raf = 0;
    const loop = () => {
      const v = viewRef.current;
      if (v) {
        const now = performance.now() / 1000;
        for (const a of v.actors.values()) {
          if (a.loc.k !== "desk" && now > a.freeAt + 2.2) a.home(now);
          a.trim(now);
        }
        humans.current = humans.current.filter((h) => h.t1 > now);
        const hs: Partial<Record<StationId, HumanState>> = {};
        let ring = false;
        for (const h of humans.current) if (h.t0 <= now) { hs[h.st] = { text: h.text, tone: h.tone }; if (h.st === "guardia") ring = true; }
        v.render(now, { ...fxRef.current, humans: hs, ring });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [agents]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const rows = await api.audit({ limit: 120 });
        const v = viewRef.current;
        if (!alive || !v) return;
        const newest = rows[0]?.id ?? 0;
        if (lastId.current === null) { lastId.current = newest; return; }
        const fresh = rows.filter((r) => r.id > (lastId.current ?? 0)).reverse();
        lastId.current = Math.max(lastId.current, newest);
        const now = performance.now() / 1000;
        const items: FeedItem[] = [];
        fresh.forEach((r, i) => {
          const id = r.agent.slice(0, 2);
          const a = v.actors.get(id);
          if (!a) return;
          const p = plan(a, { step: r.step, tool: r.tool, decision: r.decision, result: r.result, topic: r.step === "evento" ? String(r.input.topic ?? "evento") : undefined }, now + i * 0.05, humans.current);
          const ag = agents.find((x) => x.id === id);
          if (p && r.step !== "evento") items.push({ key: r.id, at: new Date(r.at).toLocaleTimeString("es-ES"), who: `${id} ${ag?.titulo ?? r.agent}`, color: AREA_LIST.find((x) => x.id === ag?.area)?.color ?? "#9aa7b4", ...p });
        });
        if (items.length) setFeed((f) => [...items.reverse(), ...f].slice(0, 40));
      } catch { /* la API se reintenta en el siguiente ciclo */ }
    };
    const timer = setInterval(tick, 1200);
    void tick();
    return () => { alive = false; clearInterval(timer); };
  }, [agents]);

  useEffect(() => {
    const t = setInterval(() => { api.tickets().then((ts) => { fxRef.current.tickets = ts.filter((x) => x.status !== "cerrado").length; }).catch(() => undefined); }, 3000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const hour = summary ? new Date(summary.now).getUTCHours() : 12;
    fxRef.current.alarm = Boolean(summary?.nodes_without_service.length || summary?.active_faults.length);
    fxRef.current.night = hour >= 22 || hour < 7 ? 0.7 : 0;
    fxRef.current.kill = Boolean(control?.kill_switch);
  }, [summary, control]);

  return (
    <section className="office">
      <div className="office-stage">
        <svg ref={svgRef} role="img" aria-label="Oficina con los 40 agentes. Cada muñeco va al puesto de la herramienta que usa." />
        <div className="office-legend">
          <span><i className="rb" />agente de IA (el número es su id)</span>
          <span><i className="st">★</i>su trabajo acaba en una persona</span>
          <span><i className="hm" />persona</span>
          <span>Para tocar la red, todos pasan por el <b>núcleo de control</b>.</span>
        </div>
      </div>
      <aside className="office-side">
        <h2>Haz que trabajen</h2>
        {controls}
        <h3>Qué está haciendo cada uno</h3>
        {!feed.length && <p className="muted">Inyecta una avería o publica un evento de negocio: verás a los agentes levantarse e ir a su puesto.</p>}
        <ol className="feed">
          {feed.map((f) => (
            <li key={f.key} data-s={f.tone}>
              <span className="t mono">{f.at}</span>
              <b style={{ borderColor: f.color }}>{f.who}</b>
              <span className="muted">→ {f.place}</span>
              <span>{f.text}</span>
            </li>
          ))}
        </ol>
      </aside>
    </section>
  );
}
