// Los 40 agentes tal y como salen en el anuncio: dónde se sientan, a qué puesto van y qué dicen allí.
// Los datos de cada uno (área, nivel, herramientas) son los de agents/<area>/<id>_<nombre>.yaml.
import type { Area, RosterEntry, StationId } from "../office/layout";

export interface AdAgent extends RosterEntry {
  va: StationId | "red";
  dice: string;
  herramientas: string[];
}

const A = (id: string, titulo: string, area: Area, autonomia: number, persona: boolean, herramientas: string[], va: StationId | "red", dice: string): AdAgent =>
  ({ id, titulo, area, autonomia, persona, herramientas, va, dice });

export const AGENTES: AdAgent[] = [
  A("01", "Centinela", "noc", 2, false, ["red.alarmas"], "red", "6 alarmas → 1 fallo real"),
  A("02", "Triaje", "noc", 2, false, ["tickets", "inventario"], "tickets", "TCK-0042 · prioridad 1"),
  A("03", "Bombero", "noc", 2, false, ["red.runbooks"], "red", "conmuto al respaldo ✓"),
  A("04", "Escalador", "noc", 2, false, ["notificaciones"], "guardia", "aviso a la guardia"),
  A("05", "Forense", "noc", 0, false, ["tickets", "red.historico"], "tickets", "causa raíz redactada"),
  A("06", "Guardián de SLA", "noc", 2, false, ["tickets", "contratos"], "negocio", "plazo con EMP-010: 40 min"),
  A("07", "Gestor de cambios", "noc", 0, false, ["cambios"], "aprobacion", "choque de ventanas detectado"),
  A("08", "Meteorólogo", "noc", 0, false, ["meteo_sim", "energia_sim"], "exterior", "sin tormenta ni corte de luz"),
  A("09", "Afinador de antenas", "movil", 1, false, ["red.kpis", "red.config"], "red", "inclinación −2° en CEL-118"),
  A("10", "Cazainterferencias", "movil", 0, false, ["red.kpis"], "red", "CEL-031 y CEL-032 se pisan"),
  A("11", "Planificador de eventos", "movil", 1, false, ["red.capacidad", "eventos"], "exterior", "concierto: +40 % capacidad"),
  A("12", "Ahorrador", "movil", 2, false, ["red.kpis", "red.config"], "red", "3 portadoras apagadas · 02:00"),
  A("13", "Auditor de vecindad", "movil", 1, false, ["red.vecinos"], "red", "vecina que faltaba, añadida"),
  A("14", "Analista de mediciones", "movil", 0, true, ["mediciones"], "archivo", "informe de cobertura listo"),
  A("15", "Diseñador de barrios", "fibra", 0, false, ["gis", "catastro_sim"], "archivo", "312 hogares · 9 cajas"),
  A("16", "Gestor de permisos", "fibra", 1, false, ["documentos"], "archivo", "solicitud de obra preparada"),
  A("17", "Doctor remoto", "fibra", 2, false, ["red.ont"], "red", "router reiniciado: sin técnico"),
  A("18", "Coordinador de contratas", "fibra", 1, true, ["ordenes", "fotos"], "negocio", "orden OT-0007 asignada"),
  A("19", "Cartógrafo", "fibra", 2, false, ["gis", "inventario"], "archivo", "mapa actualizado"),
  A("20", "Adivino", "fibra", 0, false, ["red.ont", "red.historico"], "red", "ONT-0412 fallará en 9 días"),
  A("21", "Previsor de capacidad", "core_red", 0, false, ["red.trafico"], "red", "L014 al 80 % en 6 semanas"),
  A("22", "Configurador", "core_red", 1, false, ["plantillas", "gemelo"], "gemelo", "gemelo ✓ · sin cortes"),
  A("23", "Auditor de configuraciones", "core_red", 0, false, ["red.config", "plantillas"], "red", "2 equipos fuera de estándar"),
  A("24", "Gestor de actualizaciones", "core_red", 1, false, ["inventario", "cambios"], "aprobacion", "firmware en 3 ventanas"),
  A("25", "Vigilante de rutas", "core_red", 2, false, ["red.bgp"], "red", "rutas en orden ✓"),
  A("26", "Preventa", "empresas", 1, false, ["catalogo", "red.capacidad"], "negocio", "oferta: 1 Gbps · 890 €/mes"),
  A("27", "Aprovisionador", "empresas", 1, false, ["red.config", "inventario"], "red", "circuito dado de alta"),
  A("28", "Soporte de 2.º nivel", "empresas", 2, false, ["tickets", "red"], "tickets", "resuelto sin escalar"),
  A("29", "Redactor de informes", "empresas", 2, false, ["red.kpis", "contratos"], "negocio", "38 informes enviados"),
  A("30", "Licitador", "empresas", 1, false, ["documentos"], "archivo", "pliego de 300 págs. resumido"),
  A("31", "Estratega 5G", "planificacion", 0, false, ["red.trafico", "mercado_sim"], "exterior", "4 emplazamientos nuevos"),
  A("32", "Analista de inversiones", "planificacion", 0, false, ["finanzas_sim"], "negocio", "retorno en 26 meses"),
  A("33", "Negociador de emplazamientos", "planificacion", 1, true, ["contratos"], "negocio", "renovación: borrador listo"),
  A("34", "Proyectista", "planificacion", 1, true, ["documentos"], "archivo", "proyecto para firmar"),
  A("35", "Espía", "planificacion", 0, false, ["mercado_sim"], "exterior", "la competencia cubre mejor TRI"),
  A("36", "Escudo", "seguridad", 2, false, ["red.trafico", "red.filtros"], "red", "ataque filtrado en 20 s"),
  A("37", "Cazavulnerabilidades", "seguridad", 0, false, ["inventario"], "archivo", "14 equipos afectados"),
  A("38", "Cumplidor", "seguridad", 1, true, ["documentos", "auditoria"], "archivo", "informe al regulador"),
  A("39", "Bibliotecario", "gestion", 2, false, ["documentos"], "archivo", "procedimiento actualizado"),
  A("40", "Director de orquesta", "gestion", 0, true, ["lectura:*", "panel"], "direccion", "resumen para dirección"),
];

export const NIVEL = ["Nivel 0 · observa y propone", "Nivel 1 · actúa con aprobación", "Nivel 2 · actúa solo (reversible)"];
