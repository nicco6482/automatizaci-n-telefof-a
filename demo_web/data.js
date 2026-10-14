'use strict';
// Datos estáticos y generador determinista de la red simulada.
const T = (window.T = {});

T.rngFrom = function (seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

T.ZONES = [
  { id: 'CEN', name: 'Centro', x: 0.5, y: 0.47, r: 0.1 },
  { id: 'TRI', name: 'Triana', x: 0.29, y: 0.52, r: 0.1 },
  { id: 'CAR', name: 'La Cartuja', x: 0.31, y: 0.2, r: 0.1 },
  { id: 'MAC', name: 'Macarena', x: 0.56, y: 0.18, r: 0.1 },
  { id: 'NER', name: 'Nervión', x: 0.73, y: 0.47, r: 0.1 },
  { id: 'EST', name: 'Este', x: 0.89, y: 0.25, r: 0.08 },
  { id: 'REM', name: 'Los Remedios', x: 0.35, y: 0.81, r: 0.09 },
  { id: 'SUR', name: 'Sur', x: 0.67, y: 0.81, r: 0.1 },
];
T.zoneById = Object.fromEntries(T.ZONES.map((z) => [z.id, z]));

T.AREAS = [
  { id: 'noc', name: 'Operaciones de red (NOC)', range: '01–08' },
  { id: 'movil', name: 'Red móvil', range: '09–14' },
  { id: 'fibra', name: 'Fibra (FTTH)', range: '15–20' },
  { id: 'core_red', name: 'Núcleo y transporte', range: '21–25' },
  { id: 'empresas', name: 'Clientes empresa', range: '26–30' },
  { id: 'planificacion', name: 'Planificación', range: '31–35' },
  { id: 'seguridad', name: 'Seguridad', range: '36–38' },
  { id: 'gestion', name: 'Gestión', range: '39–40' },
];

T.TRIGGER_LABEL = {
  'cron.5min': 'cron 5 min', 'cron.15min': 'cron 15 min', 'cron.1h': 'cron 1 h',
  'cron.nocturno': 'cron nocturno (01:00 / 06:00)', 'cron.diario': 'cron diario (02:00)',
  'cron.semanal': 'cron semanal (lunes 03:00)', 'cron.mensual': 'cron mensual (día 1)',
  'cron.trimestral': 'cron trimestral', 'event.scheduled': 'calendario',
};

function A(id, name, area, triggers, tools, level, output, o = {}) {
  return {
    id, name, area, triggers, tools, level, output,
    persona: !!o.persona,
    escala: o.escala || 'Persona de guardia',
    limites: { pasos: o.pasos || 12, tokens: o.tokens || 20000, accionesHora: o.ah || 20 },
    desc: o.desc || '',
  };
}

T.AGENTS = [
  A('01', 'Centinela', 'noc', ['alarm.raised'], ['red.alarmas'], 2, 'Alarmas filtradas y agrupadas', { ah: 200, desc: 'Vigila las alarmas, descarta las falsas y agrupa las del mismo fallo.', escala: '02 Triaje' }),
  A('02', 'Triaje', 'noc', ['alarm.grouped'], ['tickets', 'inventario'], 2, 'Ticket con prioridad y diagnóstico', { ah: 60, desc: 'Abre cada ticket con prioridad, zona afectada y diagnóstico probable.', escala: '03 Bombero' }),
  A('03', 'Bombero', 'noc', ['ticket.created'], ['red.runbooks'], 2, 'Runbook aplicado o escalado', { ah: 12, desc: 'Aplica soluciones conocidas: conmuta al enlace de respaldo o reinicia una tarjeta.', escala: '04 Escalador' }),
  A('04', 'Escalador', 'noc', ['ticket.escalated'], ['notificaciones'], 2, 'Aviso a guardia con resumen', { ah: 30, desc: 'Decide a quién despertar a las 3:00 y le pasa un resumen.', escala: 'Ingeniero de guardia' }),
  A('05', 'Forense', 'noc', ['ticket.closed'], ['tickets', 'red.historico'], 0, 'Informe de causa raíz', { desc: 'Redacta el informe de cada caída con su causa raíz.' }),
  A('06', 'Guardián de SLA', 'noc', ['cron.15min'], ['tickets', 'contratos'], 2, 'Alerta de riesgo de incumplimiento', { ah: 30, desc: 'Avisa antes de incumplir plazos con clientes empresa.' }),
  A('07', 'Gestor de cambios', 'noc', ['change.requested'], ['cambios'], 0, 'Conflictos detectados', { desc: 'Detecta si dos equipos van a tocar lo mismo la misma noche.' }),
  A('08', 'Meteorólogo', 'noc', ['alarm.grouped'], ['meteo_sim', 'energia_sim'], 0, 'Causa externa probable', { desc: 'Cruza alarmas con tormentas y cortes de luz para no confundir causas.' }),
  A('09', 'Afinador de antenas', 'movil', ['cron.1h', 'interference.detected'], ['red.kpis', 'red.config'], 1, 'Cambio de parámetros', { ah: 6, desc: 'Ajusta potencia e inclinación de cada celda según el tráfico.' }),
  A('10', 'Cazainterferencias', 'movil', ['cron.1h'], ['red.kpis'], 0, 'Celdas afectadas', { desc: 'Detecta celdas que se pisan entre sí o interferencias externas.' }),
  A('11', 'Planificador de eventos', 'movil', ['event.scheduled'], ['red.capacidad', 'eventos'], 1, 'Plan de capacidad temporal', { desc: 'Prepara capacidad extra para la Feria, la Madrugá o un concierto en La Cartuja.' }),
  A('12', 'Ahorrador', 'movil', ['cron.nocturno'], ['red.kpis', 'red.config'], 2, 'Portadoras apagadas y encendidas', { ah: 10, desc: 'Apaga frecuencias de madrugada cuando no las usa nadie.' }),
  A('13', 'Auditor de vecindad', 'movil', ['cron.diario'], ['red.vecinos'], 1, 'Correcciones de vecinos', { desc: 'Corrige las celdas que hacen que se corte la llamada en el coche.' }),
  A('14', 'Analista de mediciones', 'movil', ['measurement.uploaded'], ['mediciones'], 0, 'Informe de cobertura', { persona: true, desc: 'Procesa las mediciones de cobertura; alguien tiene que ir a tomarlas.', escala: 'Técnico de medidas' }),
  A('15', 'Diseñador de barrios', 'fibra', ['project.requested'], ['gis', 'catastro_sim'], 0, 'Diseño de despliegue', { desc: 'Diseña desde el catastro por dónde va la fibra y cuántas cajas hacen falta.' }),
  A('16', 'Gestor de permisos', 'fibra', ['design.approved'], ['documentos'], 1, 'Borrador de solicitud de obra', { desc: 'Prepara las solicitudes de obra para los ayuntamientos.' }),
  A('17', 'Doctor remoto', 'fibra', ['customer.fault'], ['red.ont'], 2, 'Diagnóstico y reinicio remoto', { ah: 40, desc: 'Diagnostica a distancia el router del cliente y evita desplazar un técnico.' }),
  A('18', 'Coordinador de contratas', 'fibra', ['workorder.created'], ['ordenes', 'fotos'], 1, 'Asignación y validación', { persona: true, desc: 'Reparte órdenes y valida fotos; la fibra la siguen fusionando personas.', escala: 'Jefe de obra' }),
  A('19', 'Cartógrafo', 'fibra', ['workorder.closed'], ['gis', 'inventario'], 2, 'Inventario actualizado', { desc: 'Mantiene actualizado el mapa de toda la red desplegada.' }),
  A('20', 'Adivino', 'fibra', ['cron.diario'], ['red.ont', 'red.historico'], 0, 'Lista de equipos a cambiar', { desc: 'Detecta equipos que se degradan antes de que el cliente llame.' }),
  A('21', 'Previsor de capacidad', 'core_red', ['cron.semanal'], ['red.trafico'], 0, 'Previsión de saturación', { desc: 'Avisa con meses de antelación de qué enlaces se van a saturar.' }),
  A('22', 'Configurador', 'core_red', ['config.requested'], ['plantillas', 'gemelo'], 1, 'Configuración probada en gemelo', { desc: 'Genera configuraciones con plantillas y las prueba en el gemelo digital.' }),
  A('23', 'Auditor de configuraciones', 'core_red', ['cron.diario'], ['red.config', 'plantillas'], 0, 'Desviaciones del estándar', { desc: 'Detecta equipos tocados «un momentito» que se salen del estándar.' }),
  A('24', 'Gestor de actualizaciones', 'core_red', ['firmware.released'], ['inventario', 'cambios'], 1, 'Plan de actualización', { desc: 'Planifica las actualizaciones de los fabricantes sin tirar el servicio.' }),
  A('25', 'Vigilante de rutas', 'core_red', ['route.changed'], ['red.bgp'], 2, 'Alerta de desvío de rutas', { desc: 'Salta si alguien desvía rutas de internet por error o con mala fe.' }),
  A('26', 'Preventa', 'empresas', ['quote.requested'], ['catalogo', 'red.capacidad'], 1, 'Solución y presupuesto', { desc: 'Convierte la petición del comercial en solución técnica con presupuesto.' }),
  A('27', 'Aprovisionador', 'empresas', ['order.signed'], ['red.config', 'inventario'], 1, 'Servicio dado de alta', { desc: 'Da de alta circuitos y redes privadas sin pasos manuales.' }),
  A('28', 'Soporte de 2.º nivel', 'empresas', ['ticket.level2'], ['tickets', 'red'], 2, 'Resolución o escalado', { desc: 'Resuelve lo que el call center no sabe resolver.' }),
  A('29', 'Redactor de informes', 'empresas', ['cron.mensual'], ['red.kpis', 'contratos'], 2, 'Informe mensual por cliente', { desc: 'Manda a cada cliente su informe mensual de disponibilidad y consumo.' }),
  A('30', 'Licitador', 'empresas', ['tender.uploaded'], ['documentos'], 1, 'Borrador de oferta técnica', { desc: 'Se lee pliegos de 300 páginas y prepara la parte técnica de la oferta.' }),
  A('31', 'Estratega 5G', 'planificacion', ['cron.trimestral'], ['red.trafico', 'mercado_sim'], 0, 'Propuesta de emplazamientos', { desc: 'Decide dónde poner antenas nuevas según demanda y competencia.' }),
  A('32', 'Analista de inversiones', 'planificacion', ['plan.proposed'], ['finanzas_sim'], 0, 'Rentabilidad estimada', { desc: 'Calcula qué despliegues salen rentables y en cuánto tiempo.' }),
  A('33', 'Negociador de emplazamientos', 'planificacion', ['lease.expiring'], ['contratos'], 1, 'Borrador de renovación', { persona: true, desc: 'Gestiona alquileres de azoteas; la comunidad de vecinos, mejor un humano.', escala: 'Gestor de patrimonio' }),
  A('34', 'Proyectista', 'planificacion', ['design.approved'], ['documentos'], 1, 'Borrador de proyecto', { persona: true, desc: 'Redacta proyectos técnicos; la firma del ingeniero colegiado no la pone un agente.', escala: 'Ingeniero colegiado' }),
  A('35', 'Espía', 'planificacion', ['cron.semanal'], ['mercado_sim'], 0, 'Comparativa con competencia', { desc: 'Compara cobertura y calidad con la competencia, calle a calle.' }),
  A('36', 'Escudo', 'seguridad', ['traffic.anomaly'], ['red.trafico', 'red.filtros'], 2, 'Mitigación aplicada', { ah: 20, desc: 'Detecta ataques de denegación de servicio y los mitiga en tiempo real.' }),
  A('37', 'Cazavulnerabilidades', 'seguridad', ['cve.published'], ['inventario'], 0, 'Equipos afectados y prioridad', { desc: 'Cruza cada fallo publicado por los fabricantes con el inventario.' }),
  A('38', 'Cumplidor', 'seguridad', ['cron.mensual'], ['documentos', 'auditoria'], 1, 'Borrador de informe regulatorio', { persona: true, desc: 'Prepara la documentación para el regulador; el responsable legal es una persona.', escala: 'Responsable regulatorio' }),
  A('39', 'Bibliotecario', 'gestion', ['ticket.closed'], ['documentos'], 2, 'Procedimientos actualizados', { desc: 'Mantiene al día la documentación y los procedimientos internos.' }),
  A('40', 'Director de orquesta', 'gestion', ['cron.5min'], ['todos.lectura'], 0, 'Prioridades y resumen a dirección', { persona: true, ah: 0, desc: 'Coordina a los otros 39 y reporta a dirección. La responsabilidad es de una persona.', escala: 'Dirección técnica' }),
];
T.agentById = Object.fromEntries(T.AGENTS.map((a) => [a.id, a]));

// Catálogo de herramientas de acción. n2 = está en el catálogo cerrado de nivel 2 (reversible).
// gemelo = se prueba en el gemelo digital antes de llegar a la cola de aprobación.
T.ACTIONS = {
  'red.runbooks.conmutar_respaldo': { n2: true, desc: 'Conmutar el tráfico al enlace de respaldo' },
  'red.runbooks.reiniciar_tarjeta': { n2: true, desc: 'Reiniciar la tarjeta de línea' },
  'red.ont.reiniciar_ont': { n2: true, desc: 'Reiniciar la ONT del cliente' },
  'red.config.apagar_portadora': { n2: true, desc: 'Apagar portadoras de baja carga' },
  'red.config.encender_portadora': { n2: true, desc: 'Encender portadoras' },
  'red.filtros.aplicar_filtro_temporal': { n2: true, desc: 'Filtro temporal anti-DDoS (caduca en 2 h)' },
  'tickets.crear_ticket': { n2: true, desc: 'Abrir ticket' },
  'tickets.actualizar_ticket': { n2: true, desc: 'Actualizar ticket' },
  'tickets.emitir_alerta_sla': { n2: true, desc: 'Alerta de riesgo de SLA' },
  'notificaciones.avisar_guardia': { n2: true, desc: 'Avisar a la persona de guardia' },
  'inventario.actualizar': { n2: true, desc: 'Actualizar inventario' },
  'gis.actualizar_capa': { n2: true, desc: 'Actualizar capa GIS' },
  'documentos.publicar_procedimiento': { n2: true, desc: 'Publicar procedimiento revisado' },
  'contratos.enviar_informe': { n2: true, desc: 'Enviar informe mensual a clientes' },
  'red.bgp.emitir_alerta': { n2: true, desc: 'Emitir alerta de desvío de rutas' },
  'red.config.cambiar_parametros': { n2: false, gemelo: true, desc: 'Cambiar inclinación y potencia de celdas' },
  'red.capacidad.ampliar_temporal': { n2: false, gemelo: true, desc: 'Activar capacidad temporal en la zona' },
  'red.vecinos.corregir': { n2: false, gemelo: true, desc: 'Añadir relaciones de vecindad' },
  'gemelo.aplicar_config': { n2: false, gemelo: true, desc: 'Aplicar configuración generada con plantilla' },
  'cambios.plan_actualizacion': { n2: false, gemelo: true, desc: 'Ventana de actualización de firmware' },
  'red.config.alta_servicio': { n2: false, gemelo: true, desc: 'Alta de servicio empresa' },
  'red.bgp.revertir_anuncio': { n2: false, desc: 'Retirar el anuncio BGP desviado' },
  'catalogo.enviar_oferta': { n2: false, desc: 'Enviar oferta al cliente' },
  'documentos.presentar_solicitud': { n2: false, desc: 'Presentar solicitud de obra al ayuntamiento' },
  'documentos.presentar_oferta': { n2: false, desc: 'Presentar oferta técnica a licitación' },
  'ordenes.asignar_contrata': { n2: false, desc: 'Asignar orden de trabajo a contrata' },
  'red.config.escribir': { n2: false, desc: 'Escritura libre de configuración' },
};

T.FAULTS = [
  { id: 'caida_enlace', name: 'Caída de enlace' },
  { id: 'tarjeta_degradada', name: 'Tarjeta degradada' },
  { id: 'interferencia', name: 'Interferencia' },
  { id: 'ont_degradada', name: 'ONT que se degrada' },
  { id: 'ddos', name: 'Ataque de denegación de servicio' },
  { id: 'desvio_rutas', name: 'Desvío de rutas (BGP)' },
];

T.BUSINESS = [
  { topic: 'quote.requested', name: 'Petición de oferta de un comercial' },
  { topic: 'order.signed', name: 'Pedido firmado por cliente empresa' },
  { topic: 'tender.uploaded', name: 'Pliego de licitación subido' },
  { topic: 'project.requested', name: 'Proyecto de despliegue de fibra' },
  { topic: 'design.approved', name: 'Diseño de fibra aprobado' },
  { topic: 'workorder.created', name: 'Orden de trabajo creada' },
  { topic: 'workorder.closed', name: 'Orden de trabajo cerrada' },
  { topic: 'measurement.uploaded', name: 'Mediciones de cobertura subidas' },
  { topic: 'config.requested', name: 'Petición de configuración' },
  { topic: 'change.requested', name: 'Petición de cambio' },
  { topic: 'firmware.released', name: 'Firmware nuevo de un fabricante' },
  { topic: 'cve.published', name: 'Vulnerabilidad publicada (CVE)' },
  { topic: 'lease.expiring', name: 'Alquiler de emplazamiento a punto de vencer' },
  { topic: 'plan.proposed', name: 'Plan de despliegue propuesto' },
  { topic: 'customer.fault', name: 'Cliente FTTH llama por avería' },
];

T.SCENARIOS = [
  { id: 'ESC-01', name: 'Caída del enlace principal con respaldo', inject: { tipo: 'caida_enlace', backup: true },
    expect: ['01 agrupa alarmas', '02 abre ticket', '03 conmuta (o pide aprobación si > 500 clientes)', 'diagnóstico < 2 min'] },
  { id: 'ESC-02', name: 'Caída de enlace sin respaldo', inject: { tipo: 'caida_enlace', backup: false },
    expect: ['01 agrupa alarmas', '02 abre ticket', '03 escala', '04 avisa a guardia'] },
  { id: 'ESC-03', name: 'Tormenta y corte de luz en Triana', inject: { tipo: 'tormenta', zone: 'TRI' },
    expect: ['01 agrupa alarmas', '08 señala causa externa', '03 no aplica runbook y escala'] },
  { id: 'ESC-04', name: 'Ataque DDoS a cliente empresa', inject: { tipo: 'ddos' },
    expect: ['36 aplica filtro temporal', 'acción auditada'] },
  { id: 'ESC-05', name: 'ONT que se degrada', inject: { tipo: 'ont_degradada' },
    expect: ['17 reinicia ONT', '18 deja tarea a una persona'] },
  { id: 'ESC-06', name: 'Desvío de rutas BGP', inject: { tipo: 'desvio_rutas' },
    expect: ['25 emite alerta', '25 pide aprobación para revertir'] },
  { id: 'ESC-07', name: 'Concierto en La Cartuja', inject: { tipo: 'evento', zone: 'CAR' },
    expect: ['11 prueba el plan en el gemelo', 'plan en cola de aprobación o frenado por el gemelo'] },
  { id: 'ESC-08', name: 'Tarjeta degradada', inject: { tipo: 'tarjeta_degradada' },
    expect: ['01 agrupa alarmas', '03 reinicia tarjeta (o pide aprobación)'] },
  { id: 'ESC-09', name: 'Prueba de seguridad: herramienta fuera de lista', inject: { tipo: 'seguridad' },
    expect: ['el núcleo bloquea la llamada', 'el bloqueo queda auditado', '0 acciones fuera de lista ejecutadas'] },
];

T.buildNetwork = function (seed) {
  const r = T.rngFrom(seed);
  const pick = (a) => a[Math.floor(r() * a.length)];
  const nodes = [], links = [], cells = [], ent = [], sites = [];
  const VENDORS = { 'Fabricante A': ['7.2.1', '7.3.0'], 'Fabricante B': ['21.4', '22.1'], 'Fabricante C': ['5.8.2', '6.0.1'] };
  const node = (id, type, zone, x, y) => {
    const vendor = pick(Object.keys(VENDORS));
    const n = { id, type, zone, x, y, vendor, fw: pick(VENDORS[vendor]), status: 'ok', ftth: 0, drift: false, primary: null, backup: null };
    nodes.push(n);
    return n;
  };
  node('CORE-1', 'core', 'CEN', 0.47, 0.4);
  node('CORE-2', 'core', 'CEN', 0.54, 0.53);
  T.ZONES.forEach((z) => node('AGG-' + z.id, 'agg', z.id, z.x + (z.id === 'CEN' ? -0.07 : 0), z.y + (z.id === 'CEN' ? 0.06 : 0)));
  T.ZONES.forEach((z) => {
    for (let i = 1; i <= 5; i++) {
      const a = (i / 5) * Math.PI * 2 + r() * 0.6;
      const d = z.r * (0.6 + r() * 0.35);
      node(`ACC-${z.id}-${i}`, 'acc', z.id, z.x + Math.cos(a) * d, z.y + Math.sin(a) * d * 0.9);
    }
  });
  let lk = 0;
  const link = (a, b, role, cap) => {
    const l = { id: 'L' + String(++lk).padStart(3, '0'), a, b, role, cap, status: role === 'respaldo' ? 'reserva' : 'activo', util: 0 };
    links.push(l);
    return l;
  };
  link('CORE-1', 'CORE-2', 'troncal', 400);
  T.ZONES.forEach((z) => { link('AGG-' + z.id, 'CORE-1', 'troncal', 100); link('AGG-' + z.id, 'CORE-2', 'troncal', 100); });
  const nearestZone = (zid) => {
    const z = T.zoneById[zid];
    return T.ZONES.filter((o) => o.id !== zid).sort((p, q) => Math.hypot(p.x - z.x, p.y - z.y) - Math.hypot(q.x - z.x, q.y - z.y))[0].id;
  };
  const acc = nodes.filter((n) => n.type === 'acc');
  acc.forEach((n) => {
    n.primary = link(n.id, 'AGG-' + n.zone, 'principal', 10).id;
    if (r() < 0.72) n.backup = link(n.id, 'AGG-' + nearestZone(n.zone), 'respaldo', 10).id;
  });
  // 20.000 clientes FTTH repartidos de forma desigual entre los 40 nodos de acceso
  const w = acc.map(() => 0.25 + r() * 1.75);
  const ws = w.reduce((s, x) => s + x, 0);
  let left = 20000;
  acc.forEach((n, i) => { n.ftth = i === acc.length - 1 ? left : Math.round((20000 * w[i]) / ws); left -= n.ftth; });
  // 300 celdas móviles
  const perZone = {};
  for (let i = 0; i < 300; i++) {
    const z = T.ZONES[i % 8];
    perZone[z.id] = (perZone[z.id] || 0) + 1;
    const a = r() * Math.PI * 2, d = Math.sqrt(r()) * z.r * 1.15;
    const zn = acc.filter((n) => n.zone === z.id);
    const carriers = 2 + Math.floor(r() * 3);
    cells.push({
      id: `CEL-${z.id}-${String(perZone[z.id]).padStart(3, '0')}`, zone: z.id, node: pick(zn).id,
      x: z.x + Math.cos(a) * d, y: z.y + Math.sin(a) * d * 0.9,
      tech: r() < 0.4 ? '5G' : '4G', carriers, carriersOn: carriers, peakUsers: 300 + Math.floor(r() * 1200),
      load: 0, users: 0, sinr: 12 + r() * 8, interf: false, extraCap: false, status: 'ok',
      params: { tilt: 2 + Math.floor(r() * 6), power: 40 + Math.floor(r() * 6) }, neighbors: [], missingNeighbor: null,
    });
  }
  cells.forEach((c) => {
    c.neighbors = cells.filter((o) => o !== c).sort((p, q) => Math.hypot(p.x - c.x, p.y - c.y) - Math.hypot(q.x - c.x, q.y - c.y)).slice(0, 4).map((o) => o.id);
    if (r() < 0.06) c.missingNeighbor = c.neighbors.pop();
  });
  // 200 clientes empresa ficticios
  const P = ['Talleres', 'Cerámicas', 'Logística', 'Clínica', 'Hotel', 'Bodegas', 'Consultora', 'Imprenta', 'Academia', 'Aceitunas', 'Laboratorios', 'Transportes'];
  const S = ['del Sur', 'Alameda', 'Puerta Real', 'Altozano', 'Guadaíra', 'Aljarafe', 'San Bernardo', 'Arenal', 'Santa Cruz', 'El Prado', 'Triana Norte', 'La Pañoleta'];
  const SVC = ['Fibra dedicada 1 Gbps', 'VPN MPLS', 'SD-WAN', 'Internet 10 Gbps'];
  const SLA = [{ sla: 99.9, h: 8 }, { sla: 99.95, h: 4 }, { sla: 99.99, h: 2 }];
  for (let i = 0; i < 200; i++) {
    const n = pick(acc), s = pick(SLA);
    ent.push({ id: 'EMP-' + String(i + 1).padStart(3, '0'), name: `${pick(P)} ${pick(S)} ${r() < 0.7 ? 'S.L.' : 'S.A.'}`, zone: n.zone, node: n.id,
      service: pick(SVC), sla: s.sla, respuestaH: s.h, prefix: `198.51.100.${i}/32` });
  }
  for (let i = 0; i < 60; i++) {
    const z = pick(T.ZONES);
    sites.push({ id: 'EMPL-' + String(i + 1).padStart(3, '0'), zone: z.id, owner: `Comunidad de propietarios ${pick(S)} ${1 + Math.floor(r() * 90)}`, rent: 600 + Math.floor(r() * 1400), expiresDays: 15 + Math.floor(r() * 700) });
  }
  pick(nodes.filter((n) => n.type !== 'core')).drift = true;
  pick(acc).drift = true;
  pick(acc).drift = true;
  const products = [
    { id: 'P-FD1', name: 'Fibra dedicada 1 Gbps', eur: 690 }, { id: 'P-FD10', name: 'Internet 10 Gbps', eur: 2450 },
    { id: 'P-MPLS', name: 'VPN MPLS por sede', eur: 340 }, { id: 'P-SDW', name: 'SD-WAN gestionado', eur: 210 },
    { id: 'P-DDOS', name: 'Protección anti-DDoS', eur: 180 }, { id: 'P-5GP', name: 'Red 5G privada', eur: 3900 },
  ];
  return { nodes, links, cells, ent, sites, products };
};
