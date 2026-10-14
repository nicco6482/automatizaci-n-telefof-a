// Tipos y llamadas a la API del núcleo (api/main.py).

export interface Agent {
  id: string; slug: string; titulo: string; area: string; autonomia: number; nivel_efectivo: number;
  persona: boolean; disparadores: string[]; herramientas: string[]; escalado: string;
  limites: Record<string, number>; prompt: string; paused: boolean; runs: number;
  last_run_at: string | null; last_output: AgentOutput | null;
}
export interface AgentOutput {
  resumen: string; evidencias: string[]; accion_propuesta: string | null; confianza: number; requiere_persona: boolean;
}
export interface AuditEntry {
  id: number; at: string; agent: string; run_id: string | null; incident: string | null; step: string;
  tool: string | null; input: Record<string, unknown>; reasoning: string; result: string; decision: string;
  approved_by: string | null; tokens: number; cost_usd: number;
}
export interface Approval {
  id: string; created_at: string; agent: string; incident: string | null; tool: string; args: Record<string, unknown>;
  motive: string; rationale: string; evidence: string[]; impact: number; twin_ok: boolean | null; twin_detail: string;
  status: string; decided_at: string | null; decided_by: string | null; comment: string; result: string;
}
export interface Control {
  kill_switch: boolean; blast_radius: number; tokens_today: number; cost_today_usd: number;
  pending_approvals: number; agent_mode: string;
}
export interface BusEvent { id: string; topic: string; payload: Record<string, unknown>; incident: string | null; source: string; at: string | null }
export interface Fault { id: string; type: string; started_at: string; zone: string; node: string | null; detail: string }
export interface Summary { now: string; seed: number; nodes_without_service: string[]; active_faults: Fault[]; traffic_gbps: number; alarms_last_tick: number }

export interface Ticket {
  id: string; created_at: string; created_sim_at: string; priority: string; diagnosis: string; zone: string;
  node: string | null; group_id: string | null; codes: string[]; affected_ftth: number; enterprises: string[];
  status: string; notes: { at: string; text: string }[]; sla_alerted: boolean; closed_at: string | null;
}
export interface Page {
  id: string; created_at: string; ticket: string | null; person: string; summary: string; status: string;
  closed_at: string | null; closed_by: string | null; resolution: string;
}
export interface Task {
  id: string; created_at: string; agent: string; kind: string; title: string; detail: string; ref: string | null;
  assignee: string; status: string; closed_at: string | null; closed_by: string | null; resolution: string;
}
export interface Doc {
  id: string; created_at: string; kind: string; title: string; body: string; agent: string; status: string;
}
export interface Metrics {
  diagnosis_seconds_avg: number | null; diagnosis_samples: number; executed_outside_whitelist: number;
  actions_without_prior_audit: number; executed_actions: number; audit_rows: number;
  changes_executed: number; changes_without_twin_and_approval: number;
  false_alarms_total: number; false_alarms_filtered_pct: number; real_alarms_discarded: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* sin cuerpo */ }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}
const post = <T>(path: string, body: unknown) => req<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  agents: () => req<Agent[]>("/api/agents"),
  audit: (q: { agent?: string; incident?: string; step?: string; limit?: number }) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => { if (v !== undefined && v !== "") p.set(k, String(v)); });
    return req<AuditEntry[]>(`/api/audit?${p}`);
  },
  approvals: (status?: string) => req<Approval[]>(`/api/approvals${status ? `?status=${status}` : ""}`),
  approve: (id: string, comment: string) => post<Approval>(`/api/approvals/${id}/approve`, { comment }),
  reject: (id: string, comment: string) => post<Approval>(`/api/approvals/${id}/reject`, { comment }),
  control: () => req<Control>("/api/control"),
  killSwitch: (on: boolean) => post<Control>("/api/control/kill-switch", { on }),
  blastRadius: (value: number) => post<Control>("/api/control/blast-radius", { value }),
  resume: (slug: string) => post<{ paused: boolean }>(`/api/agents/${slug}/resume`, {}),
  events: () => req<BusEvent[]>("/api/events?count=150"),
  summary: () => req<Summary>("/api/sim/summary"),
  inject: (body: Record<string, unknown>) => post<Fault>("/api/sim/inject", body),
  tickets: () => req<Ticket[]>("/api/tickets"),
  pages: () => req<Page[]>("/api/pages"),
  closePage: (id: string, resolution: string) => post<Page>(`/api/pages/${id}/close`, { resolution }),
  requestChange: (body: Record<string, unknown>) => post<{ trace: string }>("/api/changes/request", body),
  metrics: () => req<Metrics>("/api/metrics"),
  tasks: () => req<Task[]>("/api/tasks"),
  documents: () => req<Doc[]>("/api/documents"),
  closeTask: (id: string, resolution: string) => post<Task>(`/api/tasks/${id}/close`, { resolution }),
  businessTopics: () => req<Record<string, string>>("/api/business"),
  business: (topic: string, body: Record<string, unknown>) => post<{ trace: string }>(`/api/business/${topic}`, body),
};
