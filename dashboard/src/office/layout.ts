// Plano de la oficina: ocho salas (una por área), un pasillo con los puestos de trabajo
// y, al fondo, la sala de equipos (la red), a la que solo se entra por el núcleo de control.

export const W = 1600;
export const H = 900;

export type Area = "noc" | "movil" | "fibra" | "core_red" | "empresas" | "planificacion" | "seguridad" | "gestion";
export interface AreaInfo { id: Area; label: string; color: string }
export const AREA_LIST: AreaInfo[] = [
  { id: "noc", label: "Operaciones de red", color: "#e8743b" },
  { id: "movil", label: "Red móvil", color: "#4aa3df" },
  { id: "fibra", label: "Fibra (FTTH)", color: "#4fbf84" },
  { id: "core_red", label: "Núcleo y transporte", color: "#9b7be0" },
  { id: "empresas", label: "Clientes empresa", color: "#e3b341" },
  { id: "planificacion", label: "Planificación", color: "#e06c9f" },
  { id: "seguridad", label: "Seguridad", color: "#e05656" },
  { id: "gestion", label: "Gestión", color: "#8fb3c9" },
];
export const AREA = Object.fromEntries(AREA_LIST.map((a) => [a.id, a])) as Record<Area, AreaInfo>;

export interface Pt { x: number; y: number }

export type StationId = "direccion" | "negocio" | "exterior" | "archivo" | "personas" | "guardia" | "tickets" | "aprobacion" | "gemelo";
export interface Station { id: StationId; label: string; x: number; human: boolean }
export const STATIONS: Station[] = [
  { id: "direccion", label: "Dirección", x: 92, human: false },
  { id: "negocio", label: "Contratos y finanzas", x: 243, human: false },
  { id: "exterior", label: "Meteo · energía · mercado", x: 394, human: false },
  { id: "archivo", label: "Archivo e inventario", x: 545, human: false },
  { id: "personas", label: "Bandeja de personas", x: 696, human: true },
  { id: "guardia", label: "Guardia", x: 847, human: true },
  { id: "tickets", label: "Tickets", x: 998, human: false },
  { id: "aprobacion", label: "Aprobaciones", x: 1149, human: true },
  { id: "gemelo", label: "Gemelo digital", x: 1300, human: false },
];
export const STATION = Object.fromEntries(STATIONS.map((s) => [s.id, s])) as Record<StationId, Station>;

// Pasillo y puestos
export const LANE_TOP = 338;
export const LANE_BOT = 562;
export const STATION_Y = 450;
export const STAND_TOP = 400;
export const STAND_BOT = 540;
// Núcleo de control y sala de equipos
export const GATE_X = 1393;
export const RED_X = 1428;
export const RED_W = W - 24 - RED_X;
export const RED_STAND_X = 1502;

// Salas
export const RW = 376;
export const RH = 270;
const GAP = 16;
const M = 24;
export interface Room { area: Area; x: number; y: number; w: number; h: number; top: boolean; doorX: number; aisleY: number }
export const ROOMS: Room[] = AREA_LIST.map((a, i) => {
  const top = i < 4;
  const x = M + (i % 4) * (RW + GAP);
  const y = top ? 16 : H - 16 - RH;
  return { area: a.id, x, y, w: RW, h: RH, top, doorX: x + RW - 54, aisleY: top ? y + RH - 26 : y + 50 };
});
export const ROOM = Object.fromEntries(ROOMS.map((r) => [r.area, r])) as Record<Area, Room>;

export interface RosterEntry { id: string; titulo: string; area: Area; persona: boolean; autonomia: number }

export interface Slot {
  id: string; titulo: string; area: Area; color: string; persona: boolean; autonomia: number;
  desk: Pt; seat: Pt; gapX: number; room: Room; lane: number; stand: number; off: number;
}

export function seats(roster: RosterEntry[]): Slot[] {
  const out: Slot[] = [];
  for (const a of AREA_LIST) {
    const list = roster.filter((r) => r.area === a.id).sort((p, q) => p.id.localeCompare(q.id));
    const room = ROOM[a.id];
    const n = list.length;
    const rows = n > 4 ? 2 : 1;
    const cols = Math.max(1, Math.ceil(n / rows));
    const colW = RW / cols;
    const rowY = room.top
      ? (rows === 1 ? [room.y + 110] : [room.y + 70, room.y + 158])
      : (rows === 1 ? [room.y + 120] : [room.y + 88, room.y + 176]);
    list.forEach((r, i) => {
      const row = Math.floor(i / cols);
      const col = i % cols;
      const inRow = row === rows - 1 ? n - row * cols : cols;
      const x = room.x + (col + 0.5) * colW + ((cols - inRow) * colW) / 2;
      const desk = { x, y: rowY[row] ?? rowY[0] ?? room.y };
      const seat = { x, y: desk.y + 46 };
      out.push({
        id: r.id, titulo: r.titulo, area: r.area, color: a.color, persona: r.persona, autonomia: r.autonomia,
        desk, seat, gapX: col === cols - 1 && cols > 1 ? x - colW / 2 : x + colW / 2, room,
        lane: room.top ? LANE_TOP : LANE_BOT, stand: room.top ? STAND_TOP : STAND_BOT,
        off: ((Number(r.id) % 5) - 2) * 13,
      });
    });
  }
  return out;
}

// A qué puesto va cada herramienta (nombre canónico «servidor.grupo.herramienta»).
export function stationFor(tool: string | null): StationId | "red" | null {
  if (!tool) return null;
  const server = tool.split(".")[0] ?? "";
  if (tool === "panel.entregar_resumen") return "direccion";
  switch (server) {
    case "red": return "red";
    case "tickets": return "tickets";
    case "notificaciones": return "guardia";
    case "gemelo": return "gemelo";
    case "cambios": return "aprobacion";
    case "contratos": case "finanzas_sim": case "ordenes": return "negocio";
    case "meteo_sim": case "energia_sim": case "mercado_sim": case "eventos": return "exterior";
    case "auditoria": case "panel": return "direccion";
    default: return "archivo";
  }
}
