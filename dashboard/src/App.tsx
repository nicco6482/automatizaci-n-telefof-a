import { useCallback, useEffect, useState } from "react";
import { api, type Agent, type Approval, type AuditEntry, type BusEvent, type Control, type Metrics, type Page, type Summary, type Ticket } from "./api";

const FAULTS: [string, string][] = [
  ["caida_enlace", "Caída de enlace"], ["tarjeta_degradada", "Tarjeta degradada"], ["interferencia", "Interferencia"],
  ["ont_degradada", "ONT que se degrada"], ["ddos", "Ataque DDoS"], ["desvio_rutas", "Desvío de rutas (BGP)"],
  ["tormenta", "Tormenta y corte de luz"], ["corte_luz", "Corte de luz"],
];
const STEPS = ["", "evento", "lectura", "accion", "gemelo", "bloqueo", "aprobacion", "salida", "sistema", "error"];
const time = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("es-ES") : "—");

function decisionClass(d: string): string {
  if (/bloquead|ko|rechaz|pausa|inválida|fallida|fallo/.test(d)) return "crit";
  if (/cola|propuesta/.test(d)) return "warn";
  if (/ejecutada|ok|válida|leída|autorizada|aprobada/.test(d)) return "ok";
  return "";
}

function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []): [T | null, () => void, string | null] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fn().then((d) => { setData(d); setError(null); }).catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { load(); const t = setInterval(load, ms); return () => clearInterval(t); }, [load, ms]);
  return [data, load, error];
}

export default function App() {
  const [tab, setTab] = useState<"apr" | "avs" | "tck" | "aud" | "ag" | "chg">("apr");
  const [control, reloadControl, ctrlError] = usePoll<Control>(api.control, 2000);
  const [summary, reloadSummary] = usePoll<Summary>(api.summary, 2000);
  const [events, reloadEvents] = usePoll<BusEvent[]>(api.events, 2000);
  const [pending, reloadPending] = usePoll<Approval[]>(() => api.approvals(), 2000);
  const [pages, reloadPages] = usePoll<Page[]>(api.pages, 2000);
  const [metrics, reloadMetrics] = usePoll<Metrics>(api.metrics, 4000);
  const [notice, setNotice] = useState("");

  const refreshAll = () => { reloadControl(); reloadSummary(); reloadEvents(); reloadPending(); reloadPages(); reloadMetrics(); };
  const say = (msg: string) => { setNotice(msg); setTimeout(() => setNotice(""), 4000); };

  const toggleKill = async () => {
    if (!control) return;
    await api.killSwitch(!control.kill_switch);
    say(control.kill_switch ? "Interruptor desactivado: cada agente vuelve a su nivel." : "Interruptor activado: todos los agentes en nivel 0.");
    refreshAll();
  };

  const pendingCount = pending?.filter((a) => a.status === "pendiente").length ?? 0;
  const openPages = pages?.filter((p) => p.status === "abierto").length ?? 0;

  return (
    <div className="page">
      <header className="top">
        <div className="brand"><span className="mark" aria-hidden="true" /><div><b>teleco-agents</b><small>Panel del núcleo de control · red simulada</small></div></div>
        <div className="chips">
          <span className={`chip ${control?.agent_mode === "claude" ? "acc" : ""}`}>modo {control?.agent_mode ?? "…"}</span>
          <span className="chip">coste hoy {control ? `${control.cost_today_usd.toFixed(4)} $` : "…"}</span>
          <span className="chip">{control ? `${control.tokens_today.toLocaleString("es-ES")} tokens` : "…"}</span>
        </div>
        <BlastRadius control={control} onSaved={(v) => { say(`Radio de impacto: aprobación por encima de ${v} clientes.`); refreshAll(); }} />
        <button type="button" className="kill" aria-pressed={control?.kill_switch ?? false} onClick={toggleKill}>
          {control?.kill_switch ? "Interruptor activo: todos en nivel 0" : "Interruptor general"}
        </button>
      </header>
      {ctrlError && <p className="banner crit">No se puede contactar con la API: {ctrlError}</p>}
      {notice && <p className="banner">{notice}</p>}

      <section className="metrics">
        <Metric label="Aprobaciones pendientes" value={String(pendingCount)} tone={pendingCount ? "warn" : "ok"} />
        <Metric label="Nodos sin servicio" value={String(summary?.nodes_without_service.length ?? "—")} tone={summary?.nodes_without_service.length ? "crit" : "ok"} />
        <Metric label="Averías activas" value={String(summary?.active_faults.length ?? "—")} tone={summary?.active_faults.length ? "warn" : "ok"} />
        <Metric label="Tráfico" value={summary ? `${summary.traffic_gbps} Gbps` : "—"} />
        <Metric label="Reloj simulado" value={summary ? new Date(summary.now).toLocaleString("es-ES", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "—"} />
      </section>

      <section className="metrics goals" aria-label="Métricas de la especificación">
        <Metric label="Alarmas falsas filtradas" value={metrics && metrics.false_alarms_total ? `${metrics.false_alarms_filtered_pct} %` : "—"}
          goal={`${metrics?.false_alarms_total ?? 0} falsas · ${metrics?.real_alarms_discarded ?? 0} reales descartadas · objetivo ≥ 80 %`}
          tone={!metrics?.false_alarms_total ? "" : metrics.false_alarms_filtered_pct >= 80 ? "ok" : "crit"} />
        <Metric label="Tiempo de diagnóstico" value={metrics?.diagnosis_seconds_avg != null ? `${metrics.diagnosis_seconds_avg.toFixed(1)} s` : "—"}
          goal={`media de ${metrics?.diagnosis_samples ?? 0} incidencias · objetivo < 2 min`}
          tone={metrics?.diagnosis_seconds_avg == null ? "" : metrics.diagnosis_seconds_avg < 120 ? "ok" : "crit"} />
        <Metric label="Fuera de lista blanca ejecutadas" value={String(metrics?.executed_outside_whitelist ?? "—")}
          goal="objetivo 0" tone={metrics ? (metrics.executed_outside_whitelist === 0 ? "ok" : "crit") : ""} />
        <Metric label="Acciones sin rastro previo" value={String(metrics?.actions_without_prior_audit ?? "—")}
          goal={`${metrics?.executed_actions ?? 0} ejecutadas · ${metrics?.audit_rows ?? 0} registros · objetivo 0`}
          tone={metrics ? (metrics.actions_without_prior_audit === 0 ? "ok" : "crit") : ""} />
      </section>

      <main className="grid">
        <section className="panel">
          <div className="ph"><h2>Red simulada</h2><span className="muted">semilla {summary?.seed ?? "—"}</span></div>
          <Inject onDone={(msg) => { say(msg); refreshAll(); }} />
          <div className="body">
            <h3>Averías activas</h3>
            {summary?.active_faults.length ? summary.active_faults.map((f) => (
              <div className="row" key={f.id}><div className="hd"><b className="mono">{f.id}</b><span className="chip warn">{f.type}</span><span className="t">{time(f.started_at)}</span></div><div>{f.detail}</div></div>
            )) : <p className="muted">Ninguna. Inyecta una avería para ver trabajar a los agentes.</p>}
            <h3>Bus de eventos</h3>
            {(events ?? []).filter((e) => e.topic !== "cron.15min").slice(0, 40).map((e) => (
              <div className="row" key={e.id}><div className="hd"><span className="t mono">{time(e.at)}</span><span className="chip acc">{e.topic}</span>{e.incident && <code>{e.incident}</code>}<span className="muted">{String(e.payload.code ?? e.payload.ont ?? e.payload.target ?? "")}</span></div></div>
            ))}
          </div>
        </section>

        <section className="panel">
          <nav className="tabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === "apr"} onClick={() => setTab("apr")}>Aprobaciones<span className={`badge ${pendingCount ? "hot" : ""}`}>{pendingCount}</span></button>
            <button type="button" role="tab" aria-selected={tab === "avs"} onClick={() => setTab("avs")}>Avisos a guardia<span className={`badge ${openPages ? "hot" : ""}`}>{openPages}</span></button>
            <button type="button" role="tab" aria-selected={tab === "tck"} onClick={() => setTab("tck")}>Tickets</button>
            <button type="button" role="tab" aria-selected={tab === "aud"} onClick={() => setTab("aud")}>Auditoría</button>
            <button type="button" role="tab" aria-selected={tab === "ag"} onClick={() => setTab("ag")}>Agentes</button>
            <button type="button" role="tab" aria-selected={tab === "chg"} onClick={() => setTab("chg")}>Cambios</button>
          </nav>
          <div className="body">
            {tab === "apr" && <Approvals items={pending ?? []} onDecided={(m) => { say(m); refreshAll(); }} />}
            {tab === "avs" && <Pages items={pages ?? []} onDone={(m) => { say(m); refreshAll(); }} />}
            {tab === "tck" && <Tickets />}
            {tab === "aud" && <Audit />}
            {tab === "chg" && <ChangeForm now={summary?.now ?? null} onDone={(m) => { say(m); refreshAll(); }} />}
            {tab === "ag" && <Agents onChanged={(m) => { say(m); refreshAll(); }} />}
          </div>
        </section>
      </main>
      <footer>Red y clientes simulados: ningún sistema real. Los agentes solo actúan a través del núcleo de control; todo queda en la auditoría.</footer>
    </div>
  );
}

function Metric({ label, value, tone = "", goal }: { label: string; value: string; tone?: string; goal?: string }) {
  return <div className="metric" data-s={tone}><span className="lbl">{label}</span><span className="v">{value}</span>{goal && <span className="goal">{goal}</span>}</div>;
}

function Pages({ items, onDone }: { items: Page[]; onDone: (msg: string) => void }) {
  const [notes, setNotes] = useState<Record<string, string>>({});
  const open = items.filter((p) => p.status === "abierto");
  const closed = items.filter((p) => p.status !== "abierto").slice(0, 20);
  const close = async (p: Page) => {
    try {
      const r = await api.closePage(p.id, notes[p.id] || "Reparado en campo.");
      onDone(`${r.id} cerrado por ${r.closed_by}. El ticket ${r.ticket ?? ""} se cierra y el Forense redacta el informe.`);
    } catch (e) { onDone(`No se pudo cerrar ${p.id}: ${(e as Error).message}`); }
  };
  return (
    <>
      {!open.length && <p className="empty">Nadie está avisado ahora. El Escalador avisa aquí a la persona de guardia cuando una avería no se puede resolver en remoto. Solo una persona cierra el aviso.</p>}
      {open.map((p) => (
        <div className="appr" key={p.id}>
          <div className="hd"><b className="mono">{p.id}</b><span>{p.person}</span>{p.ticket && <code>{p.ticket}</code>}<span className="t mono">{time(p.created_at)}</span></div>
          <pre className="yaml wrap">{p.summary}</pre>
          <div className="act">
            <input id={`r_${p.id}`} aria-label={`Resolución de ${p.id}`} placeholder="Qué se hizo en campo (opcional)" value={notes[p.id] ?? ""} onChange={(e) => setNotes({ ...notes, [p.id]: e.target.value })} />
            <button type="button" className="primary" onClick={() => close(p)}>Reparado en campo, cerrar aviso</button>
          </div>
        </div>
      ))}
      {closed.length > 0 && <h3>Cerrados</h3>}
      {closed.map((p) => (
        <div className="row" key={p.id}><div className="hd"><span className="t mono">{time(p.closed_at)}</span><span className="chip ok">cerrado</span><b className="mono">{p.id}</b>{p.ticket && <code>{p.ticket}</code>}<span className="muted">por {p.closed_by}: {p.resolution}</span></div></div>
      ))}
    </>
  );
}

function Tickets() {
  const [tickets] = usePoll<Ticket[]>(api.tickets, 2500);
  if (!tickets?.length) return <p className="empty">Sin tickets. Inyecta una avería: Triaje abrirá uno con prioridad y diagnóstico.</p>;
  return (
    <>
      {tickets.map((t) => (
        <div className="row" key={t.id}>
          <div className="hd"><b className="mono">{t.id}</b><span className={`chip ${t.priority === "P1" ? "crit" : t.priority === "P2" ? "warn" : ""}`}>{t.priority}</span>
            <span className={`chip ${t.status === "cerrado" ? "ok" : t.status === "escalado" ? "warn" : "acc"}`}>{t.status}</span>
            {t.sla_alerted && <span className="chip crit">riesgo SLA</span>}<span className="t mono">{time(t.created_at)}</span></div>
          <div><b>{t.diagnosis}</b></div>
          <div className="muted">{t.zone}{t.node ? ` · ${t.node}` : ""} · {t.affected_ftth.toLocaleString("es-ES")} clientes FTTH · {t.enterprises.length} empresas · {t.codes.join(", ")}</div>
          <div className="mono muted notes">{t.notes.slice(-4).map((n, i) => <div key={i}>{time(n.at)} {n.text}</div>)}</div>
        </div>
      ))}
    </>
  );
}

function ChangeForm({ now, onDone }: { now: string | null; onDone: (msg: string) => void }) {
  const [node, setNode] = useState("ACC-CEN-1");
  const [zone, setZone] = useState("CEN");
  const [title, setTitle] = useState("Sustitución de tarjeta");
  const [start, setStart] = useState("2026-10-13T02:00");
  const [hours, setHours] = useState("2");
  const send = async () => {
    const s = new Date(`${start}:00Z`);
    const e = new Date(s.getTime() + (parseFloat(hours) || 1) * 3600_000);
    try {
      const r = await api.requestChange({ title, node: node || null, zone, starts_at: s.toISOString(), ends_at: e.toISOString() });
      onDone(`Petición ${r.trace} enviada: el Gestor de cambios busca conflictos (míralo en Auditoría).`);
    } catch (err) { onDone(`No se pudo pedir el cambio: ${(err as Error).message}`); }
  };
  return (
    <div className="form">
      <p className="muted">Pide una ventana de cambio. El Gestor de cambios (nivel 0) la compara con el calendario y dice si choca con otra. Reloj simulado: {now ? new Date(now).toISOString().slice(0, 16).replace("T", " ") : "—"} UTC. Hay cambios planificados las noches del 13, 14 y 15 de octubre.</p>
      <label>Título<input id="chg-title" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>Nodo<input id="chg-node" value={node} onChange={(e) => setNode(e.target.value.trim())} /></label>
      <label>Zona<select id="chg-zone" value={zone} onChange={(e) => setZone(e.target.value)}>{["CEN", "TRI", "CAR", "MAC", "NER", "EST", "REM", "SUR"].map((z) => <option key={z}>{z}</option>)}</select></label>
      <label>Inicio (UTC)<input id="chg-start" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} /></label>
      <label>Duración (h)<input id="chg-hours" type="number" min={0.5} step={0.5} value={hours} onChange={(e) => setHours(e.target.value)} /></label>
      <button type="button" className="primary" onClick={send}>Pedir ventana de cambio</button>
    </div>
  );
}

function BlastRadius({ control, onSaved }: { control: Control | null; onSaved: (v: number) => void }) {
  const [value, setValue] = useState("");
  useEffect(() => { if (control && value === "") setValue(String(control.blast_radius)); }, [control, value]);
  const save = async () => { const v = Math.max(0, parseInt(value, 10) || 0); await api.blastRadius(v); onSaved(v); };
  return (
    <label className="blast">Radio de impacto
      <input id="blast" type="number" min={0} step={50} value={value} onChange={(e) => setValue(e.target.value)} onBlur={save} onKeyDown={(e) => e.key === "Enter" && save()} />
      clientes
    </label>
  );
}

function Inject({ onDone }: { onDone: (msg: string) => void }) {
  const [type, setType] = useState("caida_enlace");
  const [backup, setBackup] = useState("si");
  const [error, setError] = useState("");
  const go = async () => {
    setError("");
    const body: Record<string, unknown> = { type };
    if (type === "caida_enlace" && backup !== "cualquiera") body.with_backup = backup === "si";
    try { const f = await api.inject(body); onDone(`${f.id}: ${f.detail}`); } catch (e) { setError((e as Error).message); }
  };
  return (
    <div className="inject">
      <select id="fault" aria-label="Tipo de avería" value={type} onChange={(e) => setType(e.target.value)}>{FAULTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
      {type === "caida_enlace" && (
        <select id="backup" aria-label="Respaldo" value={backup} onChange={(e) => setBackup(e.target.value)}>
          <option value="si">Nodo con respaldo</option><option value="no">Nodo sin respaldo</option><option value="cualquiera">Cualquier nodo</option>
        </select>
      )}
      <button type="button" className="primary" onClick={go}>Inyectar avería</button>
      {error && <span className="crit-text">{error}</span>}
    </div>
  );
}

function Approvals({ items, onDecided }: { items: Approval[]; onDecided: (msg: string) => void }) {
  const [comments, setComments] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const pend = items.filter((a) => a.status === "pendiente");
  const done = items.filter((a) => a.status !== "pendiente").slice(0, 20);
  const decide = async (a: Approval, ok: boolean) => {
    setBusy(a.id);
    try {
      const r = ok ? await api.approve(a.id, comments[a.id] ?? "") : await api.reject(a.id, comments[a.id] ?? "");
      onDecided(`${r.id} ${r.status}. ${r.result}`);
    } catch (e) { onDecided(`No se pudo decidir ${a.id}: ${(e as Error).message}`); }
    setBusy("");
  };
  return (
    <>
      {!pend.length && <p className="empty">No hay acciones esperando. Aquí llegan las de nivel 1, las que salen del catálogo cerrado y las que superan el radio de impacto, con su evidencia y el resultado en el gemelo.</p>}
      {pend.map((a) => (
        <div className="appr" key={a.id}>
          <div className="hd"><b className="mono">{a.id}</b><span>{a.agent}</span><span className="chip warn">{a.motive}</span><span className="t mono">{time(a.created_at)}</span>{a.incident && <code>{a.incident}</code>}</div>
          <div><code>{a.tool}</code> <span className="mono">{JSON.stringify(a.args)}</span></div>
          {a.rationale && <div className="muted">{a.rationale}</div>}
          {a.evidence.length > 0 && <ul>{a.evidence.map((e) => <li key={e}>{e}</li>)}</ul>}
          {a.twin_ok !== null && <div className={`twin ${a.twin_ok ? "" : "bad"}`}>{a.twin_detail}</div>}
          {a.impact > 0 && <div className="muted">Clientes afectados: <b>{a.impact.toLocaleString("es-ES")}</b></div>}
          <div className="act">
            <input id={`c_${a.id}`} aria-label={`Comentario para ${a.id}`} placeholder="Comentario (opcional)" value={comments[a.id] ?? ""} onChange={(e) => setComments({ ...comments, [a.id]: e.target.value })} />
            <button type="button" className="primary" disabled={busy === a.id} onClick={() => decide(a, true)}>Aprobar y ejecutar</button>
            <button type="button" className="no" disabled={busy === a.id} onClick={() => decide(a, false)}>Rechazar</button>
          </div>
        </div>
      ))}
      {done.length > 0 && <h3>Decididas</h3>}
      {done.map((a) => (
        <div className="row" key={a.id}><div className="hd"><span className="t mono">{time(a.decided_at)}</span><span className={`chip ${decisionClass(a.status)}`}>{a.status}</span><b className="mono">{a.id}</b><code>{a.tool}</code><span className="muted">por {a.decided_by}</span></div>{a.comment && <div className="muted">«{a.comment}»</div>}</div>
      ))}
    </>
  );
}

function Audit() {
  const [agent, setAgent] = useState("");
  const [incident, setIncident] = useState("");
  const [step, setStep] = useState("");
  const [rows] = usePoll<AuditEntry[]>(() => api.audit({ agent, incident, step, limit: 300 }), 2500, [agent, incident, step]);
  return (
    <>
      <div className="toolbar">
        <input id="aud-agent" aria-label="Agente" placeholder="Agente (p. ej. 00_sonda)" value={agent} onChange={(e) => setAgent(e.target.value.trim())} />
        <input id="aud-inc" aria-label="Incidente" placeholder="Incidente (INC-0001)" value={incident} onChange={(e) => setIncident(e.target.value.trim())} />
        <select id="aud-step" aria-label="Paso" value={step} onChange={(e) => setStep(e.target.value)}>{STEPS.map((s) => <option key={s} value={s}>{s || "Todos los pasos"}</option>)}</select>
        <span className="muted">{rows?.length ?? 0} filas · solo se añaden, nunca se borran</span>
      </div>
      <div className="tablewrap">
        <table className="audit">
          <thead><tr><th>Hora</th><th>Quién</th><th>Paso</th><th>Entrada → resultado</th><th>Decisión</th><th>Aprobó</th><th>Coste</th></tr></thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.id} className={r.step === "bloqueo" ? "bloq" : ""}>
                <td className="mono">{time(r.at)}</td>
                <td>{r.agent}{r.incident && <><br /><code className="muted">{r.incident}</code></>}</td>
                <td>{r.step}{r.tool && <><br /><code>{r.tool}</code></>}</td>
                <td className="res">{Object.keys(r.input).length > 0 && <span className="muted mono">{JSON.stringify(r.input).slice(0, 140)}<br /></span>}{r.result}{r.reasoning && <><br /><i className="muted">{r.reasoning}</i></>}</td>
                <td><span className={`chip ${decisionClass(r.decision)}`}>{r.decision}</span></td>
                <td>{r.approved_by ?? ""}</td>
                <td className="mono">{r.tokens ? <>{r.tokens.toLocaleString("es-ES")}<br />{r.cost_usd.toFixed(4)} $</> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Agents({ onChanged }: { onChanged: (msg: string) => void }) {
  const [agents, reload] = usePoll<Agent[]>(api.agents, 3000);
  const [open, setOpen] = useState<string | null>(null);
  if (!agents) return <p className="empty">Cargando agentes…</p>;
  if (!agents.length) return <p className="empty">No hay agentes cargados. Los 40 llegan por fases a partir de la Fase 1.</p>;
  return (
    <>
      {agents.map((a) => (
        <div className="agent" key={a.slug}>
          <button type="button" className="ag-head" aria-expanded={open === a.slug} onClick={() => setOpen(open === a.slug ? null : a.slug)}>
            <span className="mono muted">{a.id}</span><b>{a.titulo}</b>
            <span className={`lv lv${a.nivel_efectivo}`}>N{a.nivel_efectivo}</span>
            {a.persona && <span className="chip warn">persona</span>}
            {a.paused && <span className="chip crit">en pausa</span>}
            <span className="muted">{a.runs} ejecuciones · última {time(a.last_run_at)}</span>
          </button>
          {a.last_output && <div className="muted ag-last">{a.last_output.resumen}</div>}
          {open === a.slug && (
            <div className="ag-detail">
              {a.paused && <button type="button" onClick={async () => { await api.resume(a.slug); onChanged(`${a.slug} reanudado.`); reload(); }}>Reanudar</button>}
              <pre className="yaml">{[`id: ${a.slug}`, `area: ${a.area}`, `disparadores: [${a.disparadores.join(", ")}]`, "herramientas:  # lista blanca", ...a.herramientas.map((h) => `  - ${h}`), `autonomia: ${a.autonomia}`, `escalado: ${a.escalado}`, `limites: ${JSON.stringify(a.limites)}`].join("\n")}</pre>
              {a.last_output && <pre className="yaml">{JSON.stringify(a.last_output, null, 2)}</pre>}
              <details><summary>Prompt de sistema</summary><pre className="yaml wrap">{a.prompt}</pre></details>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
