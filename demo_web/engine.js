'use strict';
// Motor: reloj simulado, bus de eventos, núcleo de control (políticas), auditoría, aprobaciones y averías.
const E = (window.E = { H: {}, onEvent: {} });
const TICK = 900; // 15 min simulados
const SIM_START = Date.UTC(2026, 9, 11, 5, 0, 0) / 1000; // domingo 11 oct 2026, 05:00 (el panel arranca tras 24 h de historia)
const PRICE_IN = 3 / 1e6, PRICE_OUT = 15 / 1e6; // precio simulado por token
let S;

const DOW = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
const MON = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const pad = (n) => String(n).padStart(2, '0');
E.date = (t) => new Date(t * 1000);
E.fmt = (t, sec) => { const d = E.date(t); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}${sec ? ':' + pad(d.getUTCSeconds()) : ''}`; };
E.fmtDay = (t) => { const d = E.date(t); return `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}`; };
E.dayKey = (t) => Math.floor((t - SIM_START + 5 * 3600) / 86400);
const trim = (arr, n) => { if (arr.length > n) arr.length = n; };
const id = (k, p, w = 4) => `${p}-${String(++S.seq[k]).padStart(w, '0')}`;
const rnd = (a, b) => a + S.r() * (b - a);
const pick = (a) => a[Math.floor(S.r() * a.length)];

E.init = function (seed) {
  const net = T.buildNetwork(seed);
  S = E.S = {
    seed, r: T.rngFrom(seed * 7919 + 13), t: SIM_START, nextTick: SIM_START, speed: 300, running: true,
    kill: false, umbral: 500, ...net,
    bus: [], busLog: [], audit: [], byCorr: {}, approvals: [], tickets: [], tasks: [], groups: [], alarms: [],
    faults: [], storms: [], power: [], events: [], filters: [], onts: [], docs: [], outputs: [],
    st: Object.fromEntries(T.AGENTS.map((a) => [a.id, { status: 'inactivo', runs: 0, acts: [], paused: false, last: null, lastOut: null, tokens: 0, cost: 0 }])),
    m: { falseTotal: 0, falseFiltered: 0, blocked: 0, executed: 0, execAudited: 0, outside: 0, diag: [], costDay: {}, auditTotal: 0 },
    series: { traffic: [], alarms: [] }, tickAlarms: 0, scen: [], director: null,
    seq: { a: 0, t: 0, ap: 0, b: 0, g: 0, k: 0, f: 0, n: 0, al: 0, ot: 0, d: 0 },
  };
  S.nodeById = Object.fromEntries(S.nodes.map((n) => [n.id, n]));
  S.linkById = Object.fromEntries(S.links.map((l) => [l.id, l]));
  S.cellById = Object.fromEntries(S.cells.map((c) => [c.id, c]));
  audit({ agent: 'SIM', tipo: 'sistema', entrada: `semilla ${seed}`, resultado: `Red generada: ${S.cells.length} celdas, ${S.nodes.length} nodos, ${S.links.length} enlaces, 20.000 clientes FTTH, ${S.ent.length} clientes empresa.` });
  E.tick();
};

// ---------- auditoría ----------
function audit(e) {
  const row = { id: id('a', 'AUD', 6), t: S.t, agent: e.agent, tipo: e.tipo, herramienta: e.herramienta || '', entrada: e.entrada || '',
    razonamiento: e.razonamiento || '', resultado: e.resultado || '', decision: e.decision || '', aprobadoPor: e.aprobadoPor || '',
    comentario: e.comentario || '', tokens: e.tokens || 0, coste: e.coste || 0, corr: e.corr || '', out: e.out || null };
  S.audit.unshift(row); trim(S.audit, 4000); S.m.auditTotal++;
  if (row.corr) (S.byCorr[row.corr] = S.byCorr[row.corr] || []).push(row);
  if (/^ejecutada/.test(row.decision)) {
    S.m.execAudited++;
    const ag = T.agentById[row.agent];
    if (ag && !allowed(ag, row.herramienta)) S.m.outside++;
  }
  return row;
}
E.audit = audit;

// ---------- bus ----------
E.publish = function (topic, payload, delay, corr, from) {
  const m = { id: id('b', 'MSG', 6), topic, payload: payload || {}, at: S.t + (delay || 0), corr: corr || '', from: from || 'simulador', subs: [] };
  S.bus.push(m);
  return m;
};
function deliver(m) {
  const subs = T.AGENTS.filter((a) => a.triggers.includes(m.topic));
  m.subs = subs.map((a) => a.id); m.t = S.t;
  S.busLog.unshift(m); trim(S.busLog, 400);
  if (E.onEvent[m.topic]) E.onEvent[m.topic](m);
  subs.forEach((a) => E.runAgent(a, m));
}

// ---------- reloj ----------
E.advance = function (dt) {
  const target = S.t + dt;
  for (;;) {
    S.bus.sort((a, b) => a.at - b.at);
    const next = S.bus.length ? S.bus[0].at : Infinity;
    if (S.nextTick <= target && S.nextTick <= next) { S.t = Math.max(S.t, S.nextTick); E.tick(); continue; }
    if (next <= target) { S.t = Math.max(S.t, next); deliver(S.bus.shift()); continue; }
    break;
  }
  S.t = target;
};

// ---------- agente base (equivale a core/agent.py) ----------
E.runAgent = function (a, m) {
  const st = S.st[a.id];
  if (st.paused) {
    audit({ agent: a.id, tipo: 'sistema', entrada: m.topic, resultado: 'No se ejecuta: agente en pausa por límite de ritmo.', decision: 'pausa', corr: m.corr });
    return;
  }
  const h = E.H[a.id];
  if (!h) return;
  const ctx = makeCtx(a, m);
  st.runs++; st.last = S.t; st.status = 'trabajando';
  try { h(ctx, m.payload || {}, m); } catch (err) {
    audit({ agent: a.id, tipo: 'error', entrada: m.topic, resultado: String(err && err.message || err), corr: m.corr });
  }
  if (!ctx.outDone) ctx.out({ resumen: 'Revisado sin novedades.', evidencias: [], accion: null, confianza: 0.9, requierePersona: false });
  const pending = S.approvals.some((p) => p.agent === a.id && p.status === 'pendiente');
  st.status = st.paused ? 'en pausa' : pending ? 'esperando aprobación' : 'inactivo';
};

function allowed(a, fn) { return a.tools.some((t) => fn === t || fn.startsWith(t + '.')); }

function makeCtx(a, m) {
  const st = S.st[a.id];
  const ctx = { a, m, corr: m.corr, steps: 0, outDone: false, tin: 900, tout: 0 };
  ctx.step = () => {
    ctx.steps++; ctx.tin += 600 + Math.floor(S.r() * 900); ctx.tout += 60 + Math.floor(S.r() * 160);
    if (ctx.steps > a.limites.pasos) {
      audit({ agent: a.id, tipo: 'sistema', decision: 'límite de pasos', resultado: `Superado el máximo de ${a.limites.pasos} pasos: la ejecución se corta.`, corr: ctx.corr });
      return false;
    }
    return true;
  };
  ctx.read = (fn, entrada, resultado, razon) => {
    if (!ctx.step()) return false;
    if (!allowed(a, fn)) {
      S.m.blocked++;
      audit({ agent: a.id, tipo: 'bloqueo', herramienta: fn, entrada, razonamiento: razon, decision: 'bloqueada', resultado: `«${fn}» no está en la lista blanca de ${a.id}.`, corr: ctx.corr });
      return false;
    }
    audit({ agent: a.id, tipo: 'lectura', herramienta: fn, entrada, razonamiento: razon, resultado, decision: 'permitida', corr: ctx.corr });
    return true;
  };
  ctx.act = (fn, args, o) => policyAct(a, fn, args || {}, o || {}, ctx);
  ctx.emit = (topic, payload, delay) => {
    audit({ agent: a.id, tipo: 'evento', herramienta: 'bus.publicar', entrada: topic, resultado: 'Mensaje publicado en el bus', decision: 'permitida', corr: ctx.corr });
    return E.publish(topic, payload, delay == null ? rnd(15, 45) : delay, ctx.corr, a.id);
  };
  ctx.human = (title, detail, extra) => {
    const task = E.addTask(a.id, title, detail, ctx.corr, extra);
    audit({ agent: a.id, tipo: 'tarea', entrada: title, resultado: `Tarea ${task.id} asignada a: ${a.escala}. El agente no la cierra.`, decision: 'a persona', corr: ctx.corr });
    return task;
  };
  ctx.out = (o) => {
    ctx.outDone = true;
    const valid = typeof o.resumen === 'string' && o.resumen.length > 0 && Array.isArray(o.evidencias) && typeof o.confianza === 'number' && o.confianza >= 0 && o.confianza <= 1;
    const out = { agente: `${a.id}_${a.name}`, resumen: o.resumen, evidencias: o.evidencias, accion_propuesta: o.accion || null, confianza: +o.confianza.toFixed(2), requiere_persona: !!(o.requierePersona || a.persona) };
    const tokens = ctx.tin + ctx.tout + 400, coste = ctx.tin * PRICE_IN + (ctx.tout + 400) * PRICE_OUT;
    st.tokens += tokens; st.cost += coste; st.lastOut = out;
    const dk = E.dayKey(S.t); S.m.costDay[dk] = (S.m.costDay[dk] || 0) + coste;
    S.outputs.unshift({ t: S.t, agent: a.id, out }); trim(S.outputs, 200);
    audit({ agent: a.id, tipo: 'salida', entrada: m.topic, resultado: o.resumen, decision: valid ? 'salida válida' : 'salida inválida', tokens, coste, corr: ctx.corr, out });
  };
  return ctx;
}

// ---------- núcleo de control ----------
function policyAct(a, fn, args, o, ctx) {
  if (!ctx.step()) return 'límite';
  const st = S.st[a.id];
  const meta = T.ACTIONS[fn] || { n2: false, desc: fn };
  const base = { agent: a.id, tipo: 'acción', herramienta: fn, entrada: o.entrada || JSON.stringify(args), razonamiento: o.razon || '', corr: ctx.corr };
  if (!allowed(a, fn)) {
    S.m.blocked++;
    audit({ ...base, tipo: 'bloqueo', decision: 'bloqueada', resultado: `«${fn}» no está en la lista blanca de ${a.id}. El núcleo corta la llamada.` });
    return 'bloqueada';
  }
  const lvl = S.kill ? 0 : a.level;
  if (lvl === 0) {
    audit({ ...base, decision: 'propuesta', resultado: S.kill ? 'Interruptor general activo: queda como propuesta y no se ejecuta.' : 'Agente de nivel 0: solo propone.' });
    return 'propuesta';
  }
  st.acts = st.acts.filter((x) => x > S.t - 3600);
  if (a.limites.accionesHora && st.acts.length >= a.limites.accionesHora) {
    st.paused = true; st.status = 'en pausa';
    audit({ ...base, decision: 'pausa', resultado: `Superado el límite de ${a.limites.accionesHora} acciones por hora. El agente queda en pausa y avisa.` });
    E.publish('agent.paused', { agent: a.id }, 0, ctx.corr, 'núcleo');
    E.addTask(a.id, `Revisar ${a.id} ${a.name}: en pausa por límite de ritmo`, `Hizo ${st.acts.length} acciones en la última hora. Reanúdalo cuando lo revises.`, ctx.corr, { kind: 'pausa' });
    return 'pausa';
  }
  const impacto = o.impacto || 0;
  let motivo = null;
  if (lvl === 1) motivo = 'Agente de nivel 1: actúa con aprobación';
  else if (!meta.n2) motivo = 'Fuera del catálogo cerrado de nivel 2';
  else if (impacto > S.umbral) motivo = `Radio de impacto: ${impacto.toLocaleString('es-ES')} clientes (umbral ${S.umbral})`;
  if (o.saltarAprobacion && motivo) {
    audit({ ...base, tipo: 'bloqueo', decision: 'bloqueada', resultado: 'Intento de saltarse la aprobación: el núcleo lo ignora y la acción sigue el camino normal.' });
    S.m.blocked++;
  }
  if (motivo) {
    let gem = null;
    if (meta.gemelo) {
      gem = E.twin(fn, args);
      audit({ ...base, tipo: 'gemelo', herramienta: 'gemelo.probar', decision: gem.ok ? 'gemelo ok' : 'gemelo ko', resultado: gem.detalle });
      if (!gem.ok) return 'gemelo_ko';
    }
    const ap = { id: id('ap', 'APR'), t: S.t, agent: a.id, fn, args, label: o.label || meta.desc, motivo, evidencia: o.evidencia || [], gemelo: gem,
      impacto, razon: o.razon || '', after: o.after || null, onReject: o.onReject || null, corr: ctx.corr, status: 'pendiente' };
    S.approvals.unshift(ap);
    audit({ ...base, decision: 'en cola', resultado: `Enviada a aprobación (${ap.id}). ${motivo}.` });
    if (meta.gemelo) E.publish('change.requested', { approval: ap.id, fn, args, label: ap.label }, 5, ctx.corr, 'núcleo');
    return 'pendiente';
  }
  st.acts.push(S.t);
  const res = E.exec(fn, args);
  S.m.executed++;
  audit({ ...base, decision: 'ejecutada', resultado: res });
  if (o.after) E.publish(o.after.topic, o.after.payload, 30, ctx.corr, a.id);
  return 'ejecutada';
}

E.decide = function (apId, ok, comment) {
  const ap = S.approvals.find((x) => x.id === apId);
  if (!ap || ap.status !== 'pendiente') return;
  ap.status = ok ? 'aprobada' : 'rechazada'; ap.comment = comment || ''; ap.decidedAt = S.t;
  const base = { agent: ap.agent, tipo: 'acción', herramienta: ap.fn, entrada: JSON.stringify(ap.args), razonamiento: ap.razon, aprobadoPor: 'Operador NOC (tú)', comentario: comment || '', corr: ap.corr };
  if (ok) {
    const res = E.exec(ap.fn, ap.args);
    S.m.executed++; S.st[ap.agent].acts.push(S.t);
    audit({ ...base, decision: 'ejecutada tras aprobación', resultado: res });
    if (ap.after) E.publish(ap.after.topic, ap.after.payload, 30, ap.corr, 'núcleo');
  } else {
    audit({ ...base, decision: 'rechazada', resultado: 'Rechazada por una persona: no se ejecuta.' });
    if (ap.onReject) E.publish(ap.onReject.topic, ap.onReject.payload, 10, ap.corr, 'núcleo');
  }
  const st = S.st[ap.agent];
  if (!st.paused) st.status = S.approvals.some((p) => p.agent === ap.agent && p.status === 'pendiente') ? 'esperando aprobación' : 'inactivo';
};

E.setKill = function (on) {
  S.kill = on;
  audit({ agent: 'NÚCLEO', tipo: 'sistema', decision: on ? 'interruptor activado' : 'interruptor desactivado', aprobadoPor: 'Operador NOC (tú)',
    resultado: on ? 'Todos los agentes pasan a nivel 0: solo leen y proponen.' : 'Cada agente vuelve a su nivel de autonomía.' });
};
E.setUmbral = function (v) {
  S.umbral = v;
  audit({ agent: 'NÚCLEO', tipo: 'sistema', decision: 'umbral cambiado', aprobadoPor: 'Operador NOC (tú)', resultado: `Radio de impacto: aprobación obligatoria por encima de ${v} clientes.` });
};
E.resume = function (agentId) {
  const st = S.st[agentId]; st.paused = false; st.acts = []; st.status = 'inactivo';
  audit({ agent: agentId, tipo: 'sistema', decision: 'reanudado', aprobadoPor: 'Operador NOC (tú)', resultado: 'Agente reanudado; contador de acciones a cero.' });
};

// ---------- tareas humanas ----------
E.addTask = function (agentId, title, detail, corr, extra) {
  const t = { id: id('k', 'TAR'), t: S.t, agent: agentId, title, detail, corr: corr || '', status: 'abierta', ...(extra || {}) };
  S.tasks.unshift(t); trim(S.tasks, 300);
  return t;
};
E.closeTask = function (taskId) {
  const k = S.tasks.find((x) => x.id === taskId);
  if (!k || k.status !== 'abierta') return;
  k.status = 'cerrada'; k.closedAt = S.t;
  audit({ agent: 'PERSONA', tipo: 'humano', entrada: k.title, decision: 'cerrada por persona', aprobadoPor: 'Persona responsable (tú)', resultado: 'Tarea revisada y cerrada por una persona.', corr: k.corr });
  if (k.kind === 'pausa') E.resume(k.agent);
  if (k.kind === 'campo') E.repairFault(k.corr, 'Técnico de campo');
  if (k.kind === 'contrata') E.publish('workorder.closed', { ot: k.ot, zone: k.zone }, 60, k.corr, 'persona');
};

// ---------- tickets ----------
E.findTicket = (tid) => S.tickets.find((x) => x.id === tid);
E.closeTicket = function (tk, why) {
  if (!tk || tk.status === 'cerrado') return;
  tk.status = 'cerrado'; tk.closedAt = S.t; tk.notes.push(`${E.fmt(S.t)} cerrado: ${why}`);
  S.tasks.filter((k) => k.ticket === tk.id && k.status === 'abierta').forEach((k) => { k.status = 'sin objeto'; k.closedAt = S.t; });
  E.publish('ticket.closed', { ticket: tk.id }, 20, tk.corr, 'tickets');
};
E.onEvent['ticket.resolved'] = (m) => {
  const tk = E.findTicket(m.payload.ticket);
  if (tk && E.faultCleared(tk.corr)) E.closeTicket(tk, 'servicio verificado tras la acción');
};
E.onEvent['external.cause'] = (m) => {
  const g = S.groups.find((x) => x.id === m.payload.group);
  if (g) { g.external = m.payload.cause; S.tickets.filter((t) => t.group === g.id).forEach((t) => (t.external = m.payload.cause)); }
};

// ---------- ejecutor (único que actúa sobre la red) ----------
E.exec = function (fn, a) {
  const n = a.node ? S.nodeById[a.node] : null;
  switch (fn) {
    case 'red.runbooks.conmutar_respaldo': {
      const b = S.linkById[n.backup]; b.status = 'activo'; n.onBackup = true; n.status = 'en respaldo';
      const cs = S.cells.filter((c) => c.node === n.id && c.status === 'caída'); cs.forEach((c) => (c.status = 'ok'));
      faultsOf(a.corr).forEach((f) => (f.mitigated = true));
      return `Tráfico de ${n.id} por ${b.id}. ${cs.length} celdas y ${n.ftth.toLocaleString('es-ES')} clientes FTTH recuperados.`;
    }
    case 'red.runbooks.reiniciar_tarjeta': {
      n.card = 'ok'; faultsOf(a.corr).forEach((f) => { f.active = false; });
      return `Tarjeta de línea de ${n.id} reiniciada en 94 s. BER de vuelta a 1e-12.`;
    }
    case 'red.ont.reiniciar_ont': {
      const o = S.onts.find((x) => x.id === a.ont); if (o) { o.rebooted = true; o.power += 1.5; }
      return `ONT ${a.ont} reiniciada. Potencia óptica ${o ? o.power.toFixed(1) : '-'} dBm; servicio restablecido.`;
    }
    case 'red.config.apagar_portadora': {
      let k = 0; S.cells.filter((c) => c.zone === a.zone && c.load < 0.15 && c.carriersOn > 1).forEach((c) => { c.carriersOn = 1; k++; });
      return `${k} celdas de ${T.zoneById[a.zone].name} con una sola portadora hasta las 06:00.`;
    }
    case 'red.config.encender_portadora': {
      let k = 0; S.cells.filter((c) => c.zone === a.zone && c.carriersOn < c.carriers).forEach((c) => { c.carriersOn = c.carriers; k++; });
      return `${k} celdas de ${T.zoneById[a.zone].name} con todas sus portadoras.`;
    }
    case 'red.filtros.aplicar_filtro_temporal': {
      S.filters.push({ target: a.target, until: S.t + 7200 }); faultsOf(a.corr).forEach((f) => { f.mitigated = true; f.active = false; });
      return `Filtro de limpieza para ${a.target} activo 2 h. Tráfico legítimo entregado: 99,2 %.`;
    }
    case 'tickets.crear_ticket': {
      S.tickets.unshift({ ...a.ticket, t: S.t, status: 'abierto', notes: [`${E.fmt(S.t)} abierto por 02 Triaje`] }); trim(S.tickets, 300);
      return `Ticket ${a.ticket.id} (${a.ticket.prio}) creado: ${a.ticket.diag}.`;
    }
    case 'tickets.actualizar_ticket': { const tk = E.findTicket(a.ticket); if (tk) tk.notes.push(`${E.fmt(S.t)} ${a.nota}`); return `Ticket ${a.ticket} actualizado.`; }
    case 'tickets.emitir_alerta_sla': { const tk = E.findTicket(a.ticket); if (tk) tk.slaAlert = true; return `Alerta SLA en ${a.ticket}: ${a.cliente} consume el ${a.pct} % de su plazo.`; }
    case 'notificaciones.avisar_guardia': {
      E.addTask('04', `Guardia: ${a.titulo}`, a.resumen, a.corr, { kind: a.campo ? 'campo' : 'guardia', ticket: a.ticket });
      return `Aviso enviado a la persona de guardia (simulado): ${a.titulo}.`;
    }
    case 'inventario.actualizar': return `Inventario actualizado: ${a.detalle}.`;
    case 'gis.actualizar_capa': return `Capa GIS «${a.capa}» actualizada.`;
    case 'documentos.publicar_procedimiento': S.docs.unshift({ t: S.t, title: a.titulo }); return `Procedimiento «${a.titulo}» publicado (v${1 + S.docs.length}).`;
    case 'contratos.enviar_informe': return `Informe mensual enviado a ${a.clientes} clientes empresa (simulado).`;
    case 'red.bgp.emitir_alerta': return `Alerta BGP: ${a.prefijo} anunciado por AS${a.as}.`;
    case 'red.config.cambiar_parametros': {
      a.cells.forEach((cid) => { const c = S.cellById[cid]; c.params.tilt += 1; c.params.power -= 1; if (c.interf) { c.interf = false; c.sinr += 7; } });
      faultsOf(a.corr).forEach((f) => { f.active = false; });
      return `${a.cells.length} celdas reajustadas (+1° inclinación, −1 dBm). SINR medio recuperado.`;
    }
    case 'red.capacidad.ampliar_temporal': S.cells.filter((c) => c.zone === a.zone).forEach((c) => (c.extraCap = true)); return `Capacidad temporal activa en ${T.zoneById[a.zone].name} (portadora extra y celdas portátiles).`;
    case 'red.vecinos.corregir': a.cells.forEach((cid) => { S.cellById[cid].missingNeighbor = null; }); return `${a.cells.length} relaciones de vecindad añadidas.`;
    case 'gemelo.aplicar_config': if (n) n.drift = false; return `Configuración de plantilla «${a.plantilla}» aplicada en ${a.node}.`;
    case 'cambios.plan_actualizacion': S.nodes.filter((x) => x.vendor === a.vendor).forEach((x) => (x.fw = a.version)); return `Plan aprobado: ${a.nodos} equipos de ${a.vendor} a ${a.version} en ventanas nocturnas.`;
    case 'red.config.alta_servicio': return `Servicio «${a.servicio}» dado de alta para ${a.cliente} en ${a.node}.`;
    case 'red.bgp.revertir_anuncio': faultsOf(a.corr).forEach((f) => { f.active = false; }); return `Anuncio de ${a.prefijo} retirado; rutas de vuelta por AS64496.`;
    case 'catalogo.enviar_oferta': return `Oferta de ${a.importe.toLocaleString('es-ES')} €/mes enviada a ${a.cliente} (simulado).`;
    case 'documentos.presentar_solicitud': return `Solicitud de obra ${a.ref} presentada (simulado).`;
    case 'documentos.presentar_oferta': return `Oferta técnica para «${a.lote}» presentada (simulado).`;
    case 'ordenes.asignar_contrata': return `Orden ${a.ot} asignada a ${a.contrata}.`;
    default: return 'Acción sin efecto en el simulador.';
  }
};

// ---------- gemelo digital ----------
E.twin = function (fn, args) {
  const fail = S.r() < 0.18;
  const cell = args.cells && args.cells[0];
  const R = {
    'red.config.cambiar_parametros': ['Sin regresiones: SINR +6 dB, 0 celdas vecinas degradadas.', `Con +1° la ${cell} deja un hueco de cobertura (RSRP −121 dBm en el borde).`],
    'red.capacidad.ampliar_temporal': ['Carga máxima prevista 78 % con 2,6× de tráfico.', 'La portadora extra interfiere con la celda vecina: carga 104 %.'],
    'red.vecinos.corregir': ['Traspasos simulados: tasa de corte de 1,9 % a 0,4 %.', 'La nueva vecina crea un bucle de traspasos (ping-pong).'],
    'gemelo.aplicar_config': ['La configuración carga sin errores y el tráfico converge en 3 s.', 'La ACL bloquea el tráfico de gestión del nodo.'],
    'cambios.plan_actualizacion': ['Actualización simulada sin caída: respaldo activo durante el reinicio.', 'Dos nodos de la misma zona quedan sin respaldo a la vez.'],
    'red.config.alta_servicio': ['Circuito levantado en el gemelo: latencia 2,1 ms, 0 pérdidas.', 'La VLAN pedida ya está en uso en el nodo.'],
  }[fn] || ['Sin regresiones.', 'Regresión detectada.'];
  return { ok: !fail, detalle: fail ? `Gemelo: ${R[1]} No llega a la cola de aprobación.` : `Gemelo: ${R[0]}` };
};

// ---------- averías y factores externos ----------
function faultsOf(corr) { return S.faults.filter((f) => f.id === corr); }
E.faultCleared = (corr) => faultsOf(corr).every((f) => !f.active || f.mitigated);
E.repairFault = function (corr, who) {
  faultsOf(corr).forEach((f) => {
    f.active = false; f.mitigated = true;
    if (f.node) {
      const n = S.nodeById[f.node];
      if (f.tipo === 'caida_enlace') { S.linkById[n.primary].status = 'activo'; if (n.backup) S.linkById[n.backup].status = 'reserva'; n.onBackup = false; n.status = 'ok'; }
      if (f.tipo === 'tarjeta_degradada') n.card = 'ok';
      S.cells.filter((c) => c.node === n.id).forEach((c) => (c.status = 'ok'));
    }
    if (f.zone && (f.tipo === 'tormenta' || f.tipo === 'corte_luz')) {
      S.storms = S.storms.filter((s) => s.corr !== corr); S.power = S.power.filter((p) => p.corr !== corr);
      S.cells.filter((c) => c.zone === f.zone && c.status === 'sin energía').forEach((c) => (c.status = 'ok'));
    }
  });
  audit({ agent: 'SIM', tipo: 'evento', entrada: corr, resultado: `Avería reparada (${who}).`, corr });
  S.tickets.filter((t) => t.corr === corr && t.status !== 'cerrado').forEach((t) => E.closeTicket(t, `reparado por ${who}`));
};

function raise(al, delay) {
  const a = { id: id('al', 'ALM', 6), t: S.t, ...al };
  S.alarms.unshift(a); trim(S.alarms, 300); S.tickAlarms++;
  E.publish('alarm.raised', a, delay || 0, al.corr, 'simulador');
}

E.inject = function (tipo, o = {}) {
  const corr = id('f', 'INC');
  const f = { id: corr, tipo, t: S.t, active: true, mitigated: false };
  const acc = S.nodes.filter((n) => n.type === 'acc' && n.status === 'ok' && !S.faults.some((x) => x.active && x.node === n.id));
  let desc = '';
  const noise = (k) => { for (let i = 0; i < k; i++) { const c = pick(S.cells); raise({ cell: c.id, node: c.node, zone: c.zone, code: pick(['FLAP_1S', 'TEMP_TRANSITORIA']), sev: 'menor', real: false, key: 'ruido-' + c.id, corr }, rnd(0, 30)); } };
  if (tipo === 'caida_enlace') {
    const pool = acc.filter((n) => o.backup === undefined || (o.backup ? !!n.backup : !n.backup));
    const n = (o.node && S.nodeById[o.node]) || pick(pool.length ? pool : acc);
    f.node = n.id; f.zone = n.zone;
    S.linkById[n.primary].status = 'caído'; n.status = 'aislado';
    const cs = S.cells.filter((c) => c.node === n.id); cs.forEach((c) => (c.status = 'caída'));
    raise({ node: n.id, zone: n.zone, code: 'LINK_DOWN', sev: 'crítica', real: true, key: n.id, corr, text: `${n.primary} ${n.id}→AGG-${n.zone}` }, 1);
    cs.forEach((c) => raise({ cell: c.id, node: n.id, zone: n.zone, code: 'CELL_UNAVAILABLE', sev: 'mayor', real: true, key: n.id, corr }, rnd(2, 20)));
    noise(2);
    desc = `Caída de ${n.primary} en ${n.id} (${n.backup ? 'con respaldo ' + n.backup : 'sin respaldo'}). ${cs.length} celdas y ${n.ftth} clientes FTTH sin servicio.`;
  } else if (tipo === 'tarjeta_degradada') {
    const n = (o.node && S.nodeById[o.node]) || pick(acc);
    f.node = n.id; f.zone = n.zone; n.card = 'degradada';
    raise({ node: n.id, zone: n.zone, code: 'CARD_BER_HIGH', sev: 'mayor', real: true, key: n.id, corr, text: 'BER 3e-6 en tarjeta de línea' }, 1);
    raise({ node: n.id, zone: n.zone, code: 'CRC_ERRORS', sev: 'menor', real: true, key: n.id, corr }, 8);
    noise(1);
    desc = `Tarjeta de línea degradada en ${n.id}: errores CRC y BER alta. ${n.ftth} clientes con cortes intermitentes.`;
  } else if (tipo === 'interferencia') {
    const z = o.zone || pick(T.ZONES).id; f.zone = z;
    const cs = S.cells.filter((c) => c.zone === z).slice(0, 3 + Math.floor(S.r() * 4));
    cs.forEach((c) => { c.interf = true; c.sinr -= 8; }); f.cells = cs.map((c) => c.id);
    desc = `Interferencia externa en ${T.zoneById[z].name}: ${cs.length} celdas con SINR por debajo de 5 dB. La detecta el barrido horario.`;
  } else if (tipo === 'ont_degradada') {
    const n = pick(acc); const ont = `ONT-${n.id.slice(4)}-${String(Math.floor(rnd(1, 999))).padStart(4, '0')}`;
    S.onts.push({ id: ont, node: n.id, zone: n.zone, power: -26.8, corr, cliente: `Cliente FTTH n.º ${Math.floor(rnd(10000, 29999))}` });
    f.node = null; f.zone = n.zone; f.ont = ont;
    E.publish('customer.fault', { ont, node: n.id, cliente: S.onts[S.onts.length - 1].cliente }, rnd(300, 900), corr, 'atención al cliente');
    desc = `${ont} pierde potencia óptica (−26,8 dBm y bajando). El cliente llamará en unos minutos.`;
  } else if (tipo === 'ddos') {
    const c = pick(S.ent); f.target = c.prefix; f.zone = c.zone;
    E.publish('traffic.anomaly', { target: c.prefix, cliente: c.name, gbps: Math.round(rnd(8, 40)), tipo: 'UDP reflection (DNS/NTP)' }, rnd(20, 60), corr, 'sondas de tráfico');
    desc = `Ataque volumétrico contra ${c.name} (${c.prefix}).`;
  } else if (tipo === 'desvio_rutas') {
    const as = 64497 + Math.floor(rnd(0, 14));
    f.prefijo = '203.0.113.0/24'; f.as = as;
    E.publish('route.changed', { prefijo: '203.0.113.0/24', as, esperado: 64496, peer: 'tránsito-2' }, rnd(10, 40), corr, 'colector BGP');
    desc = `Nuestro bloque 203.0.113.0/24 aparece anunciado por AS${as}.`;
  } else if (tipo === 'tormenta' || tipo === 'corte_luz') {
    const z = o.zone || pick(T.ZONES).id; f.zone = z;
    if (tipo === 'tormenta') S.storms.push({ zone: z, corr, until: S.t + 3 * 3600 });
    S.power.push({ zone: z, corr, until: S.t + 2.5 * 3600 });
    const cs = S.cells.filter((c) => c.zone === z && S.r() < 0.4); cs.forEach((c) => (c.status = 'sin energía'));
    cs.slice(0, 10).forEach((c) => raise({ cell: c.id, node: c.node, zone: z, code: 'MAINS_FAIL', sev: 'mayor', real: true, key: 'ZONA-' + z, corr }, rnd(1, 40)));
    raise({ zone: z, node: 'AGG-' + z, code: 'BATTERY_DISCHARGING', sev: 'mayor', real: true, key: 'ZONA-' + z, corr }, 30);
    noise(3);
    desc = `${tipo === 'tormenta' ? 'Tormenta eléctrica' : 'Corte de luz'} en ${T.zoneById[z].name}: ${cs.length} emplazamientos sin red eléctrica.`;
  } else if (tipo === 'evento') {
    const z = o.zone || 'CAR';
    const name = z === 'CAR' ? 'Concierto en La Cartuja' : z === 'REM' ? 'Feria de Abril' : `Evento en ${T.zoneById[z].name}`;
    const ev = { zone: z, name, start: S.t + 3 * 3600, end: S.t + 8 * 3600, factor: 2.6, corr };
    S.events.push(ev); f.zone = z; f.active = false;
    E.publish('event.scheduled', { zone: z, nombre: name, inicio: ev.start, fin: ev.end, asistentes: 45000 }, 5, corr, 'calendario');
    desc = `${name}: 45.000 asistentes de ${E.fmt(ev.start)} a ${E.fmt(ev.end)}.`;
  } else if (tipo === 'seguridad') {
    f.active = false; desc = 'Prueba de seguridad: un agente intenta usar una herramienta no declarada y otro intenta saltarse la aprobación.';
    E.publish('security.test', {}, 2, corr, 'prueba');
  } else if (tipo === 'ritmo') {
    f.active = false; desc = 'Prueba de límite de ritmo sobre 12 Ahorrador (10 acciones por hora).';
    E.publish('rate.test', {}, 2, corr, 'prueba');
  }
  S.faults.push(f);
  audit({ agent: 'SIM', tipo: 'evento', entrada: tipo, resultado: desc, corr });
  return corr;
};

// Pruebas de seguridad: se ejecutan con el contexto real de cada agente.
E.onEvent['security.test'] = (m) => {
  const b = makeCtx(T.agentById['03'], m);
  b.act('red.config.escribir', { node: 'CORE-1', cambio: 'no shutdown all' }, { razon: 'Respuesta del modelo fuera de su lista blanca (inyectada por la prueba).' });
  b.out({ resumen: 'Prueba: intento de escritura libre de configuración.', evidencias: [], accion: null, confianza: 0.5 });
  const af = makeCtx(T.agentById['09'], m);
  af.act('red.config.cambiar_parametros', { cells: [S.cells[0].id], corr: m.corr }, { razon: 'Prueba: el agente pide ejecutar sin aprobación.', saltarAprobacion: true, impacto: 0 });
  af.out({ resumen: 'Prueba: intento de saltarse la aprobación.', evidencias: [], accion: null, confianza: 0.5 });
};
E.onEvent['rate.test'] = (m) => {
  const c = makeCtx(T.agentById['12'], m);
  for (let i = 0; i < 11; i++) { const r = c.act('red.config.encender_portadora', { zone: T.ZONES[i % 8].id }, { razon: `Prueba de ritmo, acción ${i + 1}` }); if (r === 'pausa') break; }
  c.out({ resumen: 'Prueba de ritmo terminada.', evidencias: [], accion: null, confianza: 0.5 });
};

// ---------- tick de 15 minutos: KPIs, ruido, cron ----------
function diurnal(t) {
  const d = E.date(t), h = d.getUTCHours() + d.getUTCMinutes() / 60, we = d.getUTCDay() === 0 || d.getUTCDay() === 6;
  const s = h >= 6 ? Math.max(0, Math.sin((Math.PI * (h - 6)) / 18.5)) : 0;
  return (0.08 + 0.92 * Math.pow(s, we ? 1.1 : 1.4)) * (we ? 0.85 : 1);
}
E.diurnal = diurnal;

E.tick = function () {
  S.nextTick = S.t + TICK;
  const f = diurnal(S.t);
  let traffic = 0;
  S.cells.forEach((c) => {
    const ev = S.events.find((e) => e.zone === c.zone && S.t >= e.start && S.t < e.end);
    const mul = ev ? ev.factor : 1;
    c.users = c.status === 'ok' ? Math.round(c.peakUsers * f * mul * (0.9 + S.r() * 0.2)) : 0;
    const cap = c.carriersOn * 420 * (c.extraCap ? 1.8 : 1);
    c.load = Math.min(1.2, c.users / cap);
    traffic += c.users * 0.0042;
    if (ev && c.load > 1 && S.r() < 0.25) raise({ cell: c.id, node: c.node, zone: c.zone, code: 'CELL_CONGESTION', sev: 'mayor', real: true, key: 'EVT-' + c.zone, corr: ev.corr }, rnd(0, 60));
  });
  S.links.forEach((l) => { l.util = l.status === 'activo' ? Math.min(0.99, f * (l.role === 'troncal' ? 0.55 : 0.6) * (0.85 + S.r() * 0.3)) : 0; });
  S.series.traffic.push({ t: S.t, v: traffic }); trim2(S.series.traffic, 96);
  S.series.alarms.push({ t: S.t, v: S.tickAlarms }); trim2(S.series.alarms, 96); S.tickAlarms = 0;
  // ruido de alarmas falsas y alguna real aislada
  const k = S.r() < 0.55 ? 1 + Math.floor(S.r() * 3) : 0;
  for (let i = 0; i < k; i++) { const c = pick(S.cells); raise({ cell: c.id, node: c.node, zone: c.zone, code: pick(['FLAP_1S', 'TEMP_TRANSITORIA', 'PUERTA_ABIERTA', 'LOS_TRANSITORIO']), sev: 'menor', real: false, key: 'ruido-' + c.id, corr: 'RUIDO' }, rnd(0, 800)); }
  if (S.r() < 0.01) { const n = pick(S.nodes.filter((x) => x.type === 'acc')); const corr = id('f', 'INC'); S.faults.push({ id: corr, tipo: 'ventilador', node: null, zone: n.zone, t: S.t, active: true, mitigated: false }); raise({ node: n.id, zone: n.zone, code: 'FAN_FAIL', sev: 'menor', real: true, key: 'fan-' + n.id, corr }, 0); }
  // caducidades
  S.storms = S.storms.filter((s) => s.until > S.t);
  S.power.filter((p) => p.until <= S.t).forEach((p) => E.repairFault(p.corr, 'la distribuidora eléctrica'));
  S.filters = S.filters.filter((x) => x.until > S.t);
  S.events.filter((e) => e.end <= S.t && !e.closed).forEach((e) => { e.closed = true; S.cells.filter((c) => c.zone === e.zone).forEach((c) => (c.extraCap = false)); });
  S.onts.forEach((o) => { if (!o.rebooted) o.power -= 0.1; });
  // cron
  const d = E.date(S.t), h = d.getUTCHours(), mi = d.getUTCMinutes();
  const cron = (topic, p) => E.publish(topic, p || {}, 0, '', 'cron');
  cron('cron.15min'); cron('cron.5min');
  if (mi === 0) cron('cron.1h');
  if (mi === 0 && h === 1) cron('cron.nocturno', { fase: 'apagar' });
  if (mi === 0 && h === 6) cron('cron.nocturno', { fase: 'encender' });
  if (mi === 0 && h === 2) cron('cron.diario');
  if (mi === 0 && h === 3 && d.getUTCDay() === 1) cron('cron.semanal');
  if (mi === 0 && h === 0 && d.getUTCDate() === 1) cron('cron.mensual');
  if (mi === 0 && h === 0 && d.getUTCDate() === 1 && d.getUTCMonth() % 3 === 0) cron('cron.trimestral');
  E.checkScenarios();
};
function trim2(a, n) { while (a.length > n) a.shift(); }

E.fire = function (topic, payload) { return E.publish(topic, payload || {}, 0, payload && payload.corr || '', 'operador'); };

// ---------- eventos de negocio ----------
E.business = function (topic) {
  const corr = id('n', 'NEG');
  const c = pick(S.ent), z = pick(T.ZONES), n = pick(S.nodes.filter((x) => x.type === 'acc'));
  const V = Object.keys({ 'Fabricante A': 1, 'Fabricante B': 1, 'Fabricante C': 1 });
  const P = {
    'quote.requested': { cliente: c.name, servicio: pick(S.products).name, sedes: 1 + Math.floor(rnd(0, 6)), zone: c.zone },
    'order.signed': { cliente: c.name, servicio: c.service, node: c.node },
    'tender.uploaded': { organismo: `Diputación (ficticia) de ${z.name}`, paginas: Math.floor(rnd(180, 340)), lote: 'Red multiservicio para 42 sedes' },
    'project.requested': { zone: z.id, viviendas: Math.floor(rnd(800, 3200)) },
    'design.approved': { proyecto: `PRY-${z.id}-${Math.floor(rnd(100, 999))}`, zone: z.id, viviendas: Math.floor(rnd(800, 3200)) },
    'workorder.created': { ot: `OT-${String(++S.seq.ot).padStart(5, '0')}`, tipo: 'Instalación FTTH', zone: z.id },
    'workorder.closed': { ot: `OT-${String(S.seq.ot || 1).padStart(5, '0')}`, zone: z.id },
    'measurement.uploaded': { ruta: `Ruta ${z.name} – ${Math.floor(rnd(8, 30))} km`, muestras: Math.floor(rnd(4000, 18000)), zone: z.id },
    'config.requested': { node: n.id, plantilla: pick(['acceso-estandar-v4', 'qos-empresa-v2', 'acl-gestion-v3']) },
    'change.requested': { node: n.id, label: 'Sustitución de óptica', ventana: '02:00–04:00' },
    'firmware.released': { vendor: pick(V), version: `${Math.floor(rnd(8, 24))}.${Math.floor(rnd(0, 9))}.0` },
    'cve.published': { cve: `CVE-2026-${Math.floor(rnd(30000, 49999))}`, vendor: pick(V), cvss: +rnd(6, 9.8).toFixed(1) },
    'lease.expiring': (() => { const s = pick(S.sites); return { site: s.id, owner: s.owner, rent: s.rent, zone: s.zone }; })(),
    'plan.proposed': { zone: z.id, emplazamientos: 1 + Math.floor(rnd(0, 5)) },
    'customer.fault': (() => { const o = { id: `ONT-${n.id.slice(4)}-${String(Math.floor(rnd(1, 999))).padStart(4, '0')}`, node: n.id, zone: n.zone, power: -21.5, corr, cliente: `Cliente FTTH n.º ${Math.floor(rnd(10000, 29999))}` }; S.onts.push(o); return { ont: o.id, node: n.id, cliente: o.cliente }; })(),
  }[topic] || {};
  audit({ agent: 'NEGOCIO', tipo: 'evento', entrada: topic, resultado: `Evento de negocio publicado: ${JSON.stringify(P)}`, corr });
  E.publish(topic, P, 0, corr, 'negocio');
  return corr;
};

// ---------- escenarios ----------
E.runScenario = function (sc) {
  const i = sc.inject;
  const corr = E.inject(i.tipo === 'evento' ? 'evento' : i.tipo, { zone: i.zone, backup: i.backup });
  if (i.tipo === 'tormenta') { /* la tormenta ya incluye corte de luz */ }
  S.scen.unshift({ sc, corr, t0: S.t, status: 'en curso', checks: sc.expect.map(() => false) });
  return corr;
};
const has = (corr, agent, p) => (S.byCorr[corr] || []).some((e) => e.agent === agent && (!p || p(e)));
const diagOf = (corr) => { const d = S.m.diag.find((x) => x.corr === corr); return d ? d.s : Infinity; };
E.diagOf = diagOf;
const CHECKS = {
  'ESC-01': (c) => [has(c, '01', (e) => e.tipo === 'salida'), has(c, '02', (e) => e.herramienta === 'tickets.crear_ticket' && e.decision === 'ejecutada'), has(c, '03', (e) => e.herramienta === 'red.runbooks.conmutar_respaldo' && /ejecutada|en cola/.test(e.decision)), diagOf(c) < 120],
  'ESC-02': (c) => [has(c, '01', (e) => e.tipo === 'salida'), has(c, '02', (e) => e.herramienta === 'tickets.crear_ticket'), has(c, '03', (e) => e.entrada === 'ticket.escalated'), has(c, '04', (e) => e.herramienta === 'notificaciones.avisar_guardia' && e.decision === 'ejecutada')],
  'ESC-03': (c) => [has(c, '01', (e) => e.tipo === 'salida'), has(c, '08', (e) => e.tipo === 'salida' && e.out && /externa/.test(e.out.accion_propuesta || '')), has(c, '03', (e) => e.entrada === 'ticket.escalated') && !has(c, '03', (e) => (e.herramienta || '').startsWith('red.runbooks.') && e.tipo === 'acción')],
  'ESC-04': (c) => [has(c, '36', (e) => e.herramienta === 'red.filtros.aplicar_filtro_temporal' && /ejecutada/.test(e.decision)), has(c, '36', (e) => e.tipo === 'salida')],
  'ESC-05': (c) => [has(c, '17', (e) => e.herramienta === 'red.ont.reiniciar_ont' && /ejecutada/.test(e.decision)), has(c, '18', (e) => e.tipo === 'tarea')],
  'ESC-06': (c) => [has(c, '25', (e) => e.herramienta === 'red.bgp.emitir_alerta' && e.decision === 'ejecutada'), has(c, '25', (e) => e.herramienta === 'red.bgp.revertir_anuncio' && e.decision === 'en cola')],
  'ESC-07': (c) => [has(c, '11', (e) => e.tipo === 'gemelo'), has(c, '11', (e) => e.decision === 'en cola' || e.decision === 'gemelo ko')],
  'ESC-08': (c) => [has(c, '01', (e) => e.tipo === 'salida'), has(c, '03', (e) => e.herramienta === 'red.runbooks.reiniciar_tarjeta' && /ejecutada|en cola/.test(e.decision))],
  'ESC-09': (c) => [has(c, '03', (e) => e.tipo === 'bloqueo'), has(c, '09', (e) => e.tipo === 'bloqueo'), E.outsideExecuted() === 0],
};
E.checkScenarios = function () {
  S.scen.filter((r) => r.status === 'en curso').forEach((r) => {
    r.checks = CHECKS[r.sc.id](r.corr);
    if (r.checks.every(Boolean)) r.status = 'superado';
    else if (S.t - r.t0 > 3 * 3600) r.status = 'fallido';
  });
};

// ---------- métricas derivadas de la propia auditoría ----------
E.outsideExecuted = () => S.m.outside;
E.unaudited = () => S.m.executed - S.m.execAudited;
