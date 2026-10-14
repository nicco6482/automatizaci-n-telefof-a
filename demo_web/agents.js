'use strict';
// Comportamiento de los 40 agentes. Cada uno solo lee, propone o pide acciones a través del núcleo (ctx).
(function () {
  const H = E.H;
  const S = () => E.S;
  const r = () => E.S.r();
  const pick = (a) => a[Math.floor(r() * a.length)];
  const zn = (z) => (T.zoneById[z] ? T.zoneById[z].name : z);
  const N = (n) => Math.round(n).toLocaleString('es-ES');
  const conf = (a, b) => +(a + r() * (b - a)).toFixed(2);
  const newTicketId = () => 'TCK-' + String(++E.S.seq.t).padStart(4, '0');

  // 01 Centinela
  H['01'] = (c, al) => {
    const s = S();
    const same = s.alarms.filter((x) => x.key === al.key).length;
    c.read('red.alarmas.leer', `${al.code} en ${al.cell || al.node}`, `Alarma ${al.id} (${al.sev}); ${same} con la misma clave topológica`, 'Compruebo si se borra sola y si comparte nodo o zona con otras.');
    if (!al.real) s.m.falseTotal++;
    const filtered = al.real ? r() < 0.02 : r() < 0.9;
    if (filtered) {
      if (!al.real) s.m.falseFiltered++;
      al.filtered = true;
      return c.out({ resumen: `${al.code} en ${al.cell || al.node} descartada: transitoria, se borra sola en menos de 60 s.`, evidencias: [al.id], accion: null, confianza: conf(0.8, 0.95) });
    }
    let g = s.groups.find((x) => x.key === al.key && s.t - x.t < 1800 && !x.closed);
    if (g) {
      g.alarms.push(al.id); if (!g.codes.includes(al.code)) g.codes.push(al.code);
      return c.out({ resumen: `${al.code} añadida al grupo ${g.id} (${g.alarms.length} alarmas, mismo fallo).`, evidencias: [al.id, g.id], accion: null, confianza: conf(0.85, 0.97) });
    }
    g = { id: 'GRP-' + String(++s.seq.g).padStart(4, '0'), key: al.key, t: s.t, alarms: [al.id], codes: [al.code], zone: al.zone, node: al.node, corr: al.corr, external: null };
    s.groups.unshift(g); if (s.groups.length > 200) s.groups.length = 200;
    c.emit('alarm.grouped', { group: g.id }, 45);
    c.out({ resumen: `Nuevo grupo ${g.id} por ${al.code} en ${al.node || zn(al.zone)}. Espero 45 s a que lleguen las alarmas hermanas.`, evidencias: [al.id], accion: 'Publicar alarm.grouped', confianza: conf(0.85, 0.96) });
  };

  // 02 Triaje
  H['02'] = (c, p) => {
    const s = S(); const g = s.groups.find((x) => x.id === p.group); if (!g) return;
    const n = s.nodeById[g.node]; const cd = g.codes;
    let diag, tipo, impacto = 0, ents = [];
    if (cd.includes('LINK_DOWN') || cd.includes('CELL_UNAVAILABLE')) { diag = `Caída del enlace principal ${n.primary} de ${n.id}`; tipo = 'caida_enlace'; impacto = n.ftth; ents = s.ent.filter((e) => e.node === n.id); }
    else if (cd.includes('CARD_BER_HIGH') || cd.includes('CRC_ERRORS')) { diag = `Tarjeta de línea degradada en ${n.id}`; tipo = 'tarjeta'; impacto = n.ftth; ents = s.ent.filter((e) => e.node === n.id); }
    else if (cd.includes('MAINS_FAIL') || cd.includes('BATTERY_DISCHARGING')) { diag = `Fallo de alimentación en emplazamientos de ${zn(g.zone)}`; tipo = 'energia'; impacto = s.nodes.filter((x) => x.zone === g.zone).reduce((a, x) => a + x.ftth, 0) * 0.4; ents = s.ent.filter((e) => e.zone === g.zone).slice(0, 6); }
    else if (cd.includes('CELL_CONGESTION')) { diag = `Congestión de celdas por evento en ${zn(g.zone)}`; tipo = 'congestion'; }
    else if (cd.includes('FAN_FAIL')) { diag = `Ventilador averiado en ${g.node}`; tipo = 'ventilador'; }
    else {
      c.read('inventario.consultar', g.node, 'Sin servicios afectados', 'Compruebo si la alarma tiene impacto.');
      return c.out({ resumen: `Alarma aislada ${cd[0]} sin impacto en clientes: en observación, no abro ticket.`, evidencias: [g.id], accion: null, confianza: conf(0.7, 0.88) });
    }
    c.read('inventario.consultar', `${g.node} · ${zn(g.zone)}`, `${N(impacto)} clientes FTTH y ${ents.length} clientes empresa`, 'Calculo el alcance para fijar la prioridad.');
    const dup = s.tickets.find((t) => t.group === g.id || (t.corr === g.corr && g.corr !== 'RUIDO' && t.status !== 'cerrado'));
    c.read('tickets.buscar', g.key, dup ? `Ya existe ${dup.id}` : 'Sin tickets abiertos para este fallo');
    if (dup) {
      c.act('tickets.actualizar_ticket', { ticket: dup.id, nota: `grupo ${g.id} agregado (${g.alarms.length} alarmas)` }, { razon: 'Mismo fallo: no duplico tickets.' });
      return c.out({ resumen: `Grupo ${g.id} añadido a ${dup.id}.`, evidencias: [g.id, dup.id], accion: null, confianza: 0.9 });
    }
    const prio = impacto > 1000 || ents.some((e) => e.sla >= 99.99) ? 'P1' : impacto > 300 || ents.length ? 'P2' : 'P3';
    const tk = { id: newTicketId(), prio, diag, tipo, zone: g.zone, node: g.node, impacto: Math.round(impacto), ents: ents.map((e) => e.id), corr: g.corr, group: g.id, external: g.external };
    const res = c.act('tickets.crear_ticket', { ticket: tk }, { entrada: `${prio} · ${diag}`, razon: `Diagnóstico por patrón de alarmas (${cd.join(', ')}).`, after: { topic: 'ticket.created', payload: { ticket: tk.id } } });
    if (res === 'ejecutada') {
      const f = s.faults.find((x) => x.id === g.corr);
      if (f && f.tipo !== 'evento' && !s.m.diag.some((d) => d.corr === g.corr)) s.m.diag.push({ corr: g.corr, s: s.t - f.t });
      if (ents.length) c.emit('ticket.level2', { ticket: tk.id }, 40);
    }
    c.out({ resumen: `${tk.id} ${prio}: ${diag}. ${N(impacto)} clientes FTTH, ${ents.length} empresas.`, evidencias: [g.id, ...g.alarms.slice(0, 3)], accion: 'tickets.crear_ticket', confianza: conf(0.82, 0.95) });
  };

  // 03 Bombero
  H['03'] = (c, p) => {
    const s = S(); const tk = E.findTicket(p.ticket); if (!tk || tk.status === 'cerrado') return;
    const n = s.nodeById[tk.node];
    c.read('red.runbooks.consultar', tk.diag, tk.tipo === 'caida_enlace' ? 'RB-01 Conmutación a respaldo' : tk.tipo === 'tarjeta' ? 'RB-02 Reinicio de tarjeta' : 'Sin runbook aplicable', 'Busco una solución conocida y reversible.');
    if (r() < 0.04) c.act('red.config.escribir', { node: tk.node }, { razon: 'El modelo propone tocar la configuración a mano.' });
    const esc = (why) => { c.emit('ticket.escalated', { ticket: tk.id, motivo: why }); c.out({ resumen: `Escalo ${tk.id}: ${why}`, evidencias: [tk.id], accion: 'Escalar a guardia', confianza: conf(0.75, 0.9) }); };
    if (tk.external) return esc(`Causa externa (${tk.external}): ningún runbook arregla la energía.`);
    const after = { topic: 'ticket.resolved', payload: { ticket: tk.id } };
    const onReject = { topic: 'ticket.escalated', payload: { ticket: tk.id, motivo: 'Acción rechazada por el operador.' } };
    if (tk.tipo === 'caida_enlace') {
      if (!(n.backup && s.linkById[n.backup].status === 'reserva')) return esc(`${n.id} no tiene enlace de respaldo: hace falta un técnico en campo.`);
      const res = c.act('red.runbooks.conmutar_respaldo', { node: n.id, corr: tk.corr }, {
        entrada: `${n.id}: ${n.primary} → ${n.backup}`, razon: 'RB-01: enlace principal caído y respaldo disponible. Conmutar es reversible.', impacto: n.ftth,
        evidencia: [`${n.primary} caído`, `${n.backup} en reserva, sin carga`, `${N(n.ftth)} clientes FTTH sin servicio`], after, onReject, label: `Conmutar ${n.id} al respaldo ${n.backup}`,
      });
      if (res === 'ejecutada' || res === 'pendiente') return c.out({ resumen: res === 'ejecutada' ? `${n.id} conmutado a ${n.backup}.` : `Conmutación de ${n.id} en cola: afecta a ${N(n.ftth)} clientes (umbral ${s.umbral}).`, evidencias: [tk.id, n.primary, n.backup], accion: 'red.runbooks.conmutar_respaldo', confianza: conf(0.88, 0.97) });
      return esc(`la conmutación quedó como «${res}».`);
    }
    if (tk.tipo === 'tarjeta') {
      const res = c.act('red.runbooks.reiniciar_tarjeta', { node: n.id, corr: tk.corr }, {
        entrada: `${n.id} tarjeta de línea`, razon: 'RB-02: BER alta sin causa física aparente; el reinicio es reversible.', impacto: n.ftth,
        evidencia: ['BER 3e-6', 'errores CRC en aumento', `${N(n.ftth)} clientes en el nodo`], after, onReject, label: `Reiniciar tarjeta de línea de ${n.id}`,
      });
      if (res === 'ejecutada' || res === 'pendiente') return c.out({ resumen: res === 'ejecutada' ? `Tarjeta de ${n.id} reiniciada.` : `Reinicio de ${n.id} en cola: afecta a ${N(n.ftth)} clientes.`, evidencias: [tk.id], accion: 'red.runbooks.reiniciar_tarjeta', confianza: conf(0.8, 0.92) });
      return esc(`el reinicio quedó como «${res}».`);
    }
    esc('sin runbook para este diagnóstico.');
  };

  // 04 Escalador
  H['04'] = (c, p) => {
    const s = S(); const tk = E.findTicket(p.ticket); if (!tk || tk.status === 'cerrado') return;
    const h = E.date(s.t).getUTCHours();
    const quien = h < 8 || h >= 22 ? 'guardia nocturna de transporte' : 'turno de día del NOC';
    c.read('notificaciones.cuadrante', `hora ${h}:00`, `De guardia: ${quien}`, 'Elijo a quién avisar según la hora y el área.');
    c.act('notificaciones.avisar_guardia', { titulo: `${tk.id} ${tk.prio} · ${tk.diag}`, resumen: `${p.motivo} Impacto: ${N(tk.impacto)} clientes FTTH y ${tk.ents.length} empresas en ${zn(tk.zone)}. Al cerrar esta tarea se da la avería por reparada.`, corr: tk.corr, ticket: tk.id, campo: true }, { razon: `Ticket ${tk.prio} sin solución automática.` });
    c.out({ resumen: `Avisada ${quien} por ${tk.id} con resumen de 3 líneas.`, evidencias: [tk.id], accion: 'notificaciones.avisar_guardia', confianza: 0.92 });
  };

  // 05 Forense
  H['05'] = (c, p) => {
    const s = S(); const tk = E.findTicket(p.ticket); if (!tk) return;
    const rows = (s.byCorr[tk.corr] || []).filter((e) => e.tipo === 'acción' && /ejecutada/.test(e.decision));
    const f = s.faults.find((x) => x.id === tk.corr);
    c.read('tickets.historial', tk.id, `${tk.notes.length} notas`, 'Reconstruyo la línea de tiempo.');
    c.read('red.historico.consultar', tk.node || zn(tk.zone), `${(s.byCorr[tk.corr] || []).length} registros del incidente`);
    const dur = f ? Math.round((tk.closedAt - f.t) / 60) : 0;
    const causa = { caida_enlace: 'corte físico en el tramo principal (fibra dañada por obra)', tarjeta: 'degradación del láser de la tarjeta de línea', energia: 'corte de suministro eléctrico de la distribuidora', ventilador: 'fallo mecánico del ventilador', congestion: 'pico de tráfico por evento' }[tk.tipo] || 'sin determinar';
    c.out({ resumen: `Informe ${tk.id}: causa raíz ${causa}. Duración ${dur} min; ${rows.length} acciones ejecutadas.`, evidencias: rows.slice(0, 4).map((e) => e.id), accion: null, confianza: conf(0.7, 0.9) });
  };

  // 06 Guardián de SLA
  H['06'] = (c) => {
    const s = S();
    const open = s.tickets.filter((t) => t.status !== 'cerrado' && t.ents.length);
    c.read('tickets.listar', 'abiertos con empresas', `${open.length} tickets`);
    if (!open.length) return c.out({ resumen: 'Ningún ticket abierto afecta a clientes empresa.', evidencias: [], accion: null, confianza: 0.97 });
    c.read('contratos.sla', open.map((t) => t.id).join(', '), 'Plazos de respuesta de 2 h, 4 h y 8 h');
    let n = 0;
    open.forEach((tk) => {
      const es = tk.ents.map((id) => s.ent.find((e) => e.id === id));
      const worst = es.sort((a, b) => a.respuestaH - b.respuestaH)[0];
      const pct = Math.round(((s.t - tk.t) / (worst.respuestaH * 3600)) * 100);
      if (pct >= 50 && !tk.slaAlert) { c.corr = tk.corr; c.act('tickets.emitir_alerta_sla', { ticket: tk.id, cliente: worst.name, pct }, { razon: `SLA ${worst.sla} %: respuesta en ${worst.respuestaH} h.` }); n++; }
    });
    c.out({ resumen: n ? `${n} alertas de riesgo de SLA emitidas.` : `${open.length} ticket${open.length === 1 ? '' : 's'} con empresas dentro de plazo.`, evidencias: open.map((t) => t.id).slice(0, 4), accion: n ? 'tickets.emitir_alerta_sla' : null, confianza: 0.93 });
  };

  // 07 Gestor de cambios
  H['07'] = (c, p) => {
    const s = S();
    const pend = s.approvals.filter((a) => a.status === 'pendiente' && a.id !== p.approval);
    c.read('cambios.calendario', p.label || p.fn || 'cambio', `${pend.length} cambios pendientes`, 'Busco cambios que toquen lo mismo en la misma ventana.');
    const key = (x) => (x.args && (x.args.zone || x.args.node || (x.args.cells && x.args.cells[0] && x.args.cells[0].slice(4, 7)))) || '';
    const me = p.args ? key({ args: p.args }) : p.node || '';
    const clash = pend.filter((x) => me && key(x) && (key(x) === me || key(x).includes(me) || me.includes(key(x))));
    c.out({ resumen: clash.length ? `Conflicto: ${clash.map((x) => x.id).join(', ')} tocan ${me} en la misma ventana.` : `Sin conflictos para «${p.label || 'el cambio'}».`, evidencias: clash.map((x) => x.id), accion: clash.length ? 'Separar ventanas o aprobar en orden' : null, confianza: conf(0.8, 0.95) });
  };

  // 08 Meteorólogo
  H['08'] = (c, p) => {
    const s = S(); const g = s.groups.find((x) => x.id === p.group); if (!g) return;
    const storm = s.storms.find((x) => x.zone === g.zone), cut = s.power.find((x) => x.zone === g.zone);
    c.read('meteo_sim.consultar', zn(g.zone), storm ? 'Tormenta eléctrica activa, 38 rayos/h' : 'Sin avisos meteorológicos');
    c.read('energia_sim.consultar', zn(g.zone), cut ? 'Corte de suministro declarado por la distribuidora' : 'Suministro normal');
    if (storm || cut) {
      const cause = storm ? 'tormenta y corte de luz' : 'corte de luz';
      c.emit('external.cause', { group: g.id, cause }, 3);
      return c.out({ resumen: `${g.id}: causa externa probable (${cause} en ${zn(g.zone)}).`, evidencias: [g.id], accion: `Causa externa probable: ${cause}`, confianza: conf(0.85, 0.96) });
    }
    c.out({ resumen: `${g.id}: sin factores externos en ${zn(g.zone)}.`, evidencias: [g.id], accion: null, confianza: conf(0.85, 0.95) });
  };

  // 09 Afinador de antenas
  H['09'] = (c, p) => {
    const s = S();
    const cells = (p.cells || []).map((id) => s.cellById[id]).filter((x) => x && x.interf);
    c.read('red.kpis.celdas', cells.length ? cells.map((x) => x.id).join(', ') : 'barrido horario', cells.length ? `SINR medio ${(cells.reduce((a, x) => a + x.sinr, 0) / cells.length).toFixed(1)} dB` : 'KPIs dentro de rango');
    if (!cells.length) return c.out({ resumen: 'Inclinación y potencia correctas en todas las celdas.', evidencias: [], accion: null, confianza: 0.9 });
    c.act('red.config.cambiar_parametros', { cells: cells.map((x) => x.id), corr: c.corr }, { razon: 'Bajar potencia y subir inclinación reduce el solape.', impacto: cells.reduce((a, x) => a + x.users, 0), evidencia: cells.map((x) => `${x.id}: SINR ${x.sinr.toFixed(1)} dB`), label: `Reajustar ${cells.length} celdas de ${zn(cells[0].zone)}` });
    c.out({ resumen: `Propuesto reajuste de ${cells.length} celdas en ${zn(cells[0].zone)}.`, evidencias: cells.map((x) => x.id), accion: 'red.config.cambiar_parametros', confianza: conf(0.72, 0.88) });
  };

  // 10 Cazainterferencias
  H['10'] = (c) => {
    const s = S();
    const bad = s.cells.filter((x) => x.interf && !x.reported);
    c.read('red.kpis.sinr', 'todas las celdas', `${bad.length} celdas con SINR < 5 dB`);
    if (!bad.length) return c.out({ resumen: 'Sin interferencias nuevas.', evidencias: [], accion: null, confianza: 0.94 });
    bad.forEach((x) => (x.reported = true));
    const f = s.faults.find((x) => x.tipo === 'interferencia' && x.cells && x.cells.includes(bad[0].id));
    if (f) c.corr = f.id;
    c.emit('interference.detected', { cells: bad.map((x) => x.id), zone: bad[0].zone }, 30);
    c.out({ resumen: `Interferencia externa en ${bad.length} celdas de ${zn(bad[0].zone)}.`, evidencias: bad.map((x) => x.id), accion: 'Avisar a 09 Afinador', confianza: conf(0.8, 0.93) });
  };

  // 11 Planificador de eventos
  H['11'] = (c, p) => {
    const s = S(); const cells = s.cells.filter((x) => x.zone === p.zone);
    c.read('eventos.consultar', p.nombre, `${N(p.asistentes)} asistentes, ${E.fmt(p.inicio)}–${E.fmt(p.fin)}`);
    c.read('red.capacidad.consultar', zn(p.zone), `${cells.length} celdas; carga prevista ${Math.round(cells.reduce((a, x) => a + x.load, 0) / cells.length * 260)} %`);
    const res = c.act('red.capacidad.ampliar_temporal', { zone: p.zone }, { razon: 'Con 2,6× de tráfico las celdas pasan del 100 % de carga.', evidencia: [`${p.nombre}`, `${cells.length} celdas`, 'Carga prevista sin plan > 100 %'], label: `Capacidad temporal para «${p.nombre}»` });
    c.out({ resumen: res === 'pendiente' ? `Plan de capacidad para «${p.nombre}» en cola de aprobación.` : res === 'gemelo_ko' ? `El gemelo tumba el plan para «${p.nombre}»: rehago la propuesta.` : `Plan «${p.nombre}»: ${res}.`, evidencias: [p.nombre], accion: 'red.capacidad.ampliar_temporal', confianza: conf(0.75, 0.9) });
  };

  // 12 Ahorrador
  H['12'] = (c, p) => {
    const s = S(); const off = p.fase === 'apagar';
    c.read('red.kpis.carga', 'todas las zonas', off ? `${s.cells.filter((x) => x.load < 0.15).length} celdas por debajo del 15 % de carga` : 'Empieza la subida de tráfico de la mañana');
    let k = 0;
    for (const z of T.ZONES) {
      const users = s.cells.filter((x) => x.zone === z.id && x.load < 0.15).reduce((a, x) => a + x.users, 0);
      const res = c.act(off ? 'red.config.apagar_portadora' : 'red.config.encender_portadora', { zone: z.id }, { razon: off ? 'Carga mínima de madrugada.' : 'Hora de restaurar capacidad.', impacto: off ? users : 0 });
      if (res === 'ejecutada') k++;
      if (res === 'pausa') break;
    }
    c.out({ resumen: off ? `Portadoras apagadas en ${k} zonas hasta las 06:00. Ahorro estimado 410 kWh.` : `Portadoras encendidas en ${k} zonas.`, evidencias: [], accion: off ? 'red.config.apagar_portadora' : 'red.config.encender_portadora', confianza: 0.94 });
  };

  // 13 Auditor de vecindad
  H['13'] = (c) => {
    const s = S(); const miss = s.cells.filter((x) => x.missingNeighbor);
    c.read('red.vecinos.listar', '300 celdas', `${miss.length} celdas con vecina ausente`);
    if (!miss.length) return c.out({ resumen: 'Relaciones de vecindad completas.', evidencias: [], accion: null, confianza: 0.95 });
    const sel = miss.slice(0, 10);
    c.act('red.vecinos.corregir', { cells: sel.map((x) => x.id) }, { razon: 'Sin la relación, la llamada se corta al cambiar de celda.', evidencia: sel.slice(0, 3).map((x) => `${x.id} ↛ ${x.missingNeighbor}`), label: `Añadir ${sel.length} relaciones de vecindad` });
    c.out({ resumen: `${miss.length} celdas con vecinas ausentes; propuestas ${sel.length} correcciones.`, evidencias: sel.map((x) => x.id), accion: 'red.vecinos.corregir', confianza: conf(0.8, 0.92) });
  };

  // 14 Analista de mediciones (Persona)
  H['14'] = (c, p) => {
    const ok = 88 + Math.floor(r() * 10);
    c.read('mediciones.cargar', p.ruta, `${N(p.muestras)} muestras; RSRP > −105 dBm en el ${ok} %`);
    c.human('Revisar informe de cobertura y planificar nueva medición en campo', `${p.ruta}: cobertura buena en el ${ok} % de la ruta. Hay 3 tramos por debajo de −110 dBm que hay que volver a medir.`);
    c.out({ resumen: `Informe de cobertura de ${p.ruta}: ${ok} % en buen nivel.`, evidencias: [p.ruta], accion: 'Nueva medición en 3 tramos', confianza: 0.86, requierePersona: true });
  };

  // 15 Diseñador de barrios
  H['15'] = (c, p) => {
    const cajas = Math.ceil(p.viviendas / 16), km = (p.viviendas * 0.014).toFixed(1);
    c.read('catastro_sim.parcelas', zn(p.zone), `${N(p.viviendas)} viviendas en ${Math.ceil(p.viviendas / 40)} edificios`);
    c.read('gis.canalizaciones', zn(p.zone), `${km} km de canalización disponible`);
    c.out({ resumen: `Diseño FTTH para ${zn(p.zone)}: ${cajas} cajas terminales, ${km} km de fibra, 2 divisores 1:64.`, evidencias: [zn(p.zone)], accion: 'Proponer diseño para aprobación (design.approved)', confianza: conf(0.75, 0.88) });
  };

  // 16 Gestor de permisos
  H['16'] = (c, p) => {
    c.read('documentos.plantilla', 'solicitud de licencia de obra', 'Plantilla municipal v3');
    const ref = `LIC-${p.proyecto}`;
    c.act('documentos.presentar_solicitud', { ref }, { razon: 'Borrador completo con planos y memoria.', evidencia: [p.proyecto, 'Memoria técnica (borrador)', 'Planos de canalización'], label: `Presentar solicitud de obra ${ref}` });
    c.out({ resumen: `Borrador de solicitud de obra ${ref} listo.`, evidencias: [p.proyecto], accion: 'documentos.presentar_solicitud', confianza: 0.88 });
  };

  // 17 Doctor remoto
  H['17'] = (c, p) => {
    const s = S(); const o = s.onts.find((x) => x.id === p.ont);
    const pw = o ? o.power : -22;
    c.read('red.ont.diagnostico', p.ont, `Potencia óptica ${pw.toFixed(1)} dBm; ${pw < -25 ? 'por debajo del umbral (−25 dBm)' : 'en rango'}`, 'Diagnóstico remoto antes de mandar un técnico.');
    if (o && o.corr) c.corr = o.corr;
    c.act('red.ont.reiniciar_ont', { ont: p.ont }, { razon: 'Reinicio remoto: reversible y afecta a un solo cliente.', impacto: 1 });
    if (pw < -25) {
      c.emit('workorder.created', { ot: `OT-${String(++s.seq.ot).padStart(5, '0')}`, tipo: 'Sustitución de acometida óptica', zone: o ? o.zone : 'CEN' });
      return c.out({ resumen: `${p.ont} reiniciada; la potencia sigue baja: pido orden de trabajo.`, evidencias: [p.ont], accion: 'workorder.created', confianza: 0.84 });
    }
    c.out({ resumen: `${p.ont} reiniciada; ${p.cliente} vuelve a tener servicio sin desplazar a nadie.`, evidencias: [p.ont], accion: 'red.ont.reiniciar_ont', confianza: 0.9 });
  };

  // 18 Coordinador de contratas (Persona)
  H['18'] = (c, p) => {
    const contrata = pick(['Contrata Norte (ficticia)', 'Instalaciones Guadaíra (ficticia)', 'Redes Aljarafe (ficticia)']);
    c.read('ordenes.consultar', p.ot, `${p.tipo} en ${zn(p.zone)}`);
    c.read('fotos.listar', p.ot, 'Sin fotos todavía');
    c.act('ordenes.asignar_contrata', { ot: p.ot, contrata }, { razon: 'Contrata con menos carga en la zona y mejor nota de calidad.', evidencia: [p.ot, contrata], label: `Asignar ${p.ot} a ${contrata}` });
    c.human(`Validar fotos y cerrar ${p.ot}`, `${p.tipo} en ${zn(p.zone)}. Asignación propuesta: ${contrata}. Cierra cuando las fotos de la fusión sean válidas.`, { kind: 'contrata', ot: p.ot, zone: p.zone });
    c.out({ resumen: `${p.ot}: asignación propuesta a ${contrata}; validación de fotos para una persona.`, evidencias: [p.ot], accion: 'ordenes.asignar_contrata', confianza: 0.87, requierePersona: true });
  };

  // 19 Cartógrafo
  H['19'] = (c, p) => {
    c.act('inventario.actualizar', { detalle: `${p.ot}: acometida y caja terminal registradas` }, { razon: 'Orden cerrada con fotos validadas.' });
    c.act('gis.actualizar_capa', { capa: `FTTH ${zn(p.zone)}` }, { razon: 'Reflejar el tendido en el mapa.' });
    c.out({ resumen: `Inventario y GIS al día tras ${p.ot}.`, evidencias: [p.ot], accion: 'inventario.actualizar', confianza: 0.95 });
  };

  // 20 Adivino
  H['20'] = (c) => {
    const s = S(); const bad = s.onts.filter((o) => o.power < -24.5);
    c.read('red.ont.potencias', `${N(20000)} ONT`, `${bad.length} ONT con tendencia descendente`);
    c.read('red.historico.tendencias', '30 días', 'Pendiente media −0,1 dB/día en las marcadas');
    c.out({ resumen: bad.length ? `Cambiar antes de que el cliente llame: ${bad.map((o) => o.id).join(', ')}.` : 'Ningún equipo en riesgo esta semana.', evidencias: bad.map((o) => o.id), accion: bad.length ? 'Proponer órdenes preventivas' : null, confianza: conf(0.7, 0.86) });
  };

  // 21 Previsor de capacidad
  H['21'] = (c) => {
    const s = S(); const top = s.links.filter((l) => l.role !== 'respaldo').sort((a, b) => b.util - a.util).slice(0, 3);
    c.read('red.trafico.series', '12 semanas', 'Crecimiento medio 1,2 % semanal');
    c.out({ resumen: 'Enlaces que llegarán al 80 %: ' + top.map((l) => `${l.id} (${l.a}→${l.b}) en ${Math.max(2, Math.round(Math.log(0.8 / Math.max(0.2, l.util)) / Math.log(1.012)))} semanas`).join('; ') + '.', evidencias: top.map((l) => l.id), accion: 'Ampliar capacidad antes de la saturación', confianza: conf(0.65, 0.82) });
  };

  // 22 Configurador
  H['22'] = (c, p) => {
    c.read('plantillas.obtener', p.plantilla, '142 líneas de configuración generadas');
    const res = c.act('gemelo.aplicar_config', { node: p.node, plantilla: p.plantilla }, { razon: 'Configuración generada con plantilla; probada antes en el gemelo.', evidencia: [p.node, p.plantilla], label: `Aplicar ${p.plantilla} en ${p.node}` });
    c.out({ resumen: res === 'gemelo_ko' ? `El gemelo rechaza ${p.plantilla} en ${p.node}: no pasa a aprobación.` : `${p.plantilla} para ${p.node}: ${res === 'pendiente' ? 'en cola de aprobación' : res}.`, evidencias: [p.node], accion: 'gemelo.aplicar_config', confianza: 0.86 });
  };

  // 23 Auditor de configuraciones
  H['23'] = (c) => {
    const s = S(); const d = s.nodes.filter((n) => n.drift);
    c.read('red.config.leer', `${s.nodes.length} nodos`, `${d.length} con desviaciones`);
    c.read('plantillas.comparar', 'estándar v4', d.length ? d.map((n) => n.id).join(', ') : 'todo conforme');
    d.slice(0, 2).forEach((n) => c.emit('config.requested', { node: n.id, plantilla: 'acceso-estandar-v4' }, 60));
    c.out({ resumen: d.length ? `${d.length} equipos fuera del estándar: ${d.map((n) => n.id).join(', ')}.` : 'Todos los equipos cumplen el estándar.', evidencias: d.map((n) => n.id), accion: d.length ? 'Pedir al Configurador que los devuelva al estándar' : null, confianza: 0.93 });
  };

  // 24 Gestor de actualizaciones
  H['24'] = (c, p) => {
    const s = S(); const ns = s.nodes.filter((n) => n.vendor === p.vendor && n.fw !== p.version);
    c.read('inventario.por_fabricante', p.vendor, `${ns.length} equipos por actualizar`);
    c.read('cambios.calendario', 'próximas 2 semanas', 'Ventanas libres de 02:00 a 05:00');
    c.act('cambios.plan_actualizacion', { vendor: p.vendor, version: p.version, nodos: ns.length }, { razon: 'Por lotes, de noche, un nodo por zona cada vez para no dejar zonas sin respaldo.', evidencia: [`${ns.length} equipos`, `${p.vendor} → ${p.version}`], label: `Actualizar ${ns.length} equipos de ${p.vendor} a ${p.version}` });
    c.out({ resumen: `Plan de actualización de ${ns.length} equipos de ${p.vendor} a ${p.version} en ${Math.ceil(ns.length / 6)} noches.`, evidencias: [], accion: 'cambios.plan_actualizacion', confianza: 0.85 });
  };

  // 25 Vigilante de rutas
  H['25'] = (c, p) => {
    c.read('red.bgp.rib', p.prefijo, `Origen visto AS${p.as}; esperado AS${p.esperado}`, 'Comparo el origen con el registro de rutas.');
    c.act('red.bgp.emitir_alerta', { prefijo: p.prefijo, as: p.as }, { razon: 'Origen distinto del registrado: posible secuestro o error.' });
    c.act('red.bgp.revertir_anuncio', { prefijo: p.prefijo, corr: c.corr }, { razon: 'Pedir a tránsito que filtre el anuncio y reanunciar más específico.', evidencia: [`${p.prefijo} desde AS${p.as}`, `peer ${p.peer}`], label: `Revertir desvío de ${p.prefijo}` });
    c.out({ resumen: `Desvío de ${p.prefijo} por AS${p.as}: alerta emitida y reversión en cola.`, evidencias: [p.prefijo], accion: 'red.bgp.revertir_anuncio', confianza: conf(0.85, 0.96) });
  };

  // 26 Preventa
  H['26'] = (c, p) => {
    const s = S(); const prod = s.products.find((x) => x.name === p.servicio) || s.products[0];
    const importe = prod.eur * p.sedes;
    c.read('catalogo.precios', p.servicio, `${prod.eur} €/mes por sede`);
    c.read('red.capacidad.consultar', zn(p.zone), 'Puertos libres en el nodo de acceso');
    c.act('catalogo.enviar_oferta', { cliente: p.cliente, importe }, { razon: 'Solución estándar con margen de catálogo.', evidencia: [`${p.sedes} sedes`, prod.name], label: `Oferta a ${p.cliente}: ${importe.toLocaleString('es-ES')} €/mes` });
    c.out({ resumen: `Solución para ${p.cliente}: ${prod.name} en ${p.sedes} sedes, ${importe.toLocaleString('es-ES')} €/mes.`, evidencias: [], accion: 'catalogo.enviar_oferta', confianza: 0.88 });
  };

  // 27 Aprovisionador
  H['27'] = (c, p) => {
    c.read('inventario.puertos', p.node, '3 puertos de 10G libres; VLAN 812 libre');
    const res = c.act('red.config.alta_servicio', { cliente: p.cliente, servicio: p.servicio, node: p.node }, { razon: 'Alta automática con plantilla de servicio.', evidencia: [p.node, p.servicio], label: `Alta de ${p.servicio} para ${p.cliente}` });
    c.out({ resumen: `Alta de ${p.servicio} para ${p.cliente}: ${res === 'pendiente' ? 'probada en el gemelo y en cola' : res}.`, evidencias: [p.node], accion: 'red.config.alta_servicio', confianza: 0.87 });
  };

  // 28 Soporte de 2.º nivel
  H['28'] = (c, p) => {
    const tk = E.findTicket(p.ticket); if (!tk) return;
    c.read('tickets.detalle', tk.id, tk.diag);
    c.read('red.estado', tk.node || zn(tk.zone), tk.status === 'cerrado' ? 'Servicio restablecido' : 'Afectación en curso');
    c.act('tickets.actualizar_ticket', { ticket: tk.id, nota: `informadas ${tk.ents.length} empresas con hora estimada de solución` }, { razon: 'El cliente empresa necesita estado y estimación.' });
    c.out({ resumen: `${tk.ents.length} clientes empresa de ${tk.id} informados.`, evidencias: [tk.id], accion: 'tickets.actualizar_ticket', confianza: 0.9 });
  };

  // 29 Redactor de informes
  H['29'] = (c) => {
    c.read('red.kpis.disponibilidad', 'mes anterior', 'Disponibilidad media 99,97 %');
    c.read('contratos.listar', '200 clientes empresa', '200 contratos con SLA');
    c.act('contratos.enviar_informe', { clientes: 200 }, { razon: 'Informe mensual contractual.', impacto: 200 });
    c.out({ resumen: 'Informes mensuales de disponibilidad y consumo enviados a 200 clientes.', evidencias: [], accion: 'contratos.enviar_informe', confianza: 0.95 });
  };

  // 30 Licitador
  H['30'] = (c, p) => {
    c.read('documentos.pliego', p.organismo, `${p.paginas} páginas; 64 requisitos técnicos extraídos`);
    c.act('documentos.presentar_oferta', { lote: p.lote }, { razon: 'Cumplimos 61 de 64 requisitos; 3 con alternativa.', evidencia: ['Matriz de cumplimiento', 'Memoria técnica (borrador)'], label: `Presentar oferta técnica: ${p.lote}` });
    c.out({ resumen: `Borrador de oferta técnica para «${p.lote}»: cumple 61 de 64 requisitos.`, evidencias: [], accion: 'documentos.presentar_oferta', confianza: 0.82 });
  };

  // 31 Estratega 5G
  H['31'] = (c) => {
    const s = S();
    const z = T.ZONES.map((z) => ({ z, l: s.cells.filter((x) => x.zone === z.id).reduce((a, x) => a + x.load, 0) })).sort((a, b) => b.l - a.l)[0].z;
    c.read('red.trafico.por_zona', 'trimestre', `Mayor carga: ${z.name}`);
    c.read('mercado_sim.cobertura', z.name, 'La competencia tiene 5G en el 74 % de la zona');
    c.emit('plan.proposed', { zone: z.id, emplazamientos: 3 });
    c.out({ resumen: `Proponer 3 emplazamientos 5G nuevos en ${z.name}.`, evidencias: [z.name], accion: 'plan.proposed', confianza: 0.78 });
  };

  // 32 Analista de inversiones
  H['32'] = (c, p) => {
    const capex = p.emplazamientos * 85000, meses = 20 + Math.floor(r() * 18);
    c.read('finanzas_sim.modelo', zn(p.zone), `CAPEX ${capex.toLocaleString('es-ES')} €; ARPU 18,40 €`);
    c.out({ resumen: `${p.emplazamientos} emplazamientos en ${zn(p.zone)}: inversión ${capex.toLocaleString('es-ES')} €, retorno en ${meses} meses.`, evidencias: [], accion: meses < 30 ? 'Rentable: seguir adelante' : 'Revisar: retorno largo', confianza: 0.74 });
  };

  // 33 Negociador de emplazamientos (Persona)
  H['33'] = (c, p) => {
    c.read('contratos.alquiler', p.site, `${p.owner}; ${p.rent} €/mes`);
    const prop = Math.round(p.rent * 0.94);
    c.human(`Negociar renovación de ${p.site}`, `Borrador de renovación con ${p.owner}: propuesta ${prop} €/mes (−6 %) a 5 años. Tratar con la comunidad es trabajo de una persona.`);
    c.out({ resumen: `Borrador de renovación de ${p.site} a ${prop} €/mes.`, evidencias: [p.site], accion: 'Negociación a cargo de una persona', confianza: 0.8, requierePersona: true });
  };

  // 34 Proyectista (Persona)
  H['34'] = (c, p) => {
    c.read('documentos.plantilla', 'proyecto técnico', 'Plantilla de proyecto de telecomunicaciones');
    c.human(`Revisar y firmar el proyecto de ${p.proyecto}`, `Borrador de proyecto técnico (${N(p.viviendas)} viviendas). La firma la pone un ingeniero colegiado, no un agente.`);
    c.out({ resumen: `Borrador de proyecto de ${p.proyecto} listo para firma.`, evidencias: [p.proyecto], accion: 'Firma de una persona', confianza: 0.84, requierePersona: true });
  };

  // 35 Espía
  H['35'] = (c) => {
    c.read('mercado_sim.comparativa', '8 zonas', 'Pruebas de velocidad y cobertura de 3 operadores ficticios');
    c.out({ resumen: 'Ganamos en Nervión y Centro; perdemos en Este (−14 Mbps de mediana) y La Cartuja (cobertura interior).', evidencias: [], accion: 'Priorizar Este en el plan 5G', confianza: 0.76 });
  };

  // 36 Escudo
  H['36'] = (c, p) => {
    c.read('red.trafico.flujos', p.target, `${p.gbps} Gbps de ${p.tipo}; 18.000 orígenes`, 'Separo el tráfico de ataque del legítimo.');
    const res = c.act('red.filtros.aplicar_filtro_temporal', { target: p.target, corr: c.corr }, { razon: 'Filtro reversible que caduca solo en 2 h.', impacto: 1, evidencia: [`${p.gbps} Gbps`, p.tipo] });
    c.out({ resumen: `Ataque de ${p.gbps} Gbps contra ${p.cliente}: ${res === 'ejecutada' ? 'mitigado' : res}.`, evidencias: [p.target], accion: 'red.filtros.aplicar_filtro_temporal', confianza: conf(0.88, 0.97) });
  };

  // 37 Cazavulnerabilidades
  H['37'] = (c, p) => {
    const s = S(); const ns = s.nodes.filter((n) => n.vendor === p.vendor);
    c.read('inventario.por_fabricante', p.vendor, `${ns.length} equipos afectados`);
    const prio = p.cvss >= 9 ? 'crítica' : p.cvss >= 7 ? 'alta' : 'media';
    c.out({ resumen: `${p.cve} (CVSS ${p.cvss}) afecta a ${ns.length} equipos de ${p.vendor}. Prioridad ${prio}; los núcleos primero.`, evidencias: ns.slice(0, 4).map((n) => n.id), accion: 'Pedir parche al fabricante (firmware.released)', confianza: 0.9 });
  };

  // 38 Cumplidor (Persona)
  H['38'] = (c) => {
    const s = S();
    c.read('auditoria.resumen', 'mes', `${N(s.m.auditTotal)} registros; ${E.outsideExecuted()} acciones fuera de lista blanca ejecutadas`);
    c.read('documentos.plantilla', 'informe regulatorio', 'Plantilla del regulador (ficticia)');
    c.human('Revisar y firmar el informe regulatorio mensual', `Borrador con ${s.tickets.length} incidencias, disponibilidad y trazabilidad completa. El responsable ante el regulador es una persona.`);
    c.out({ resumen: 'Borrador de informe regulatorio listo para firma.', evidencias: [], accion: 'Firma del responsable regulatorio', confianza: 0.88, requierePersona: true });
  };

  // 39 Bibliotecario
  H['39'] = (c, p) => {
    const tk = E.findTicket(p.ticket); if (!tk) return;
    if (!['caida_enlace', 'tarjeta', 'energia'].includes(tk.tipo)) return c.out({ resumen: `${tk.id}: nada que añadir a los procedimientos.`, evidencias: [tk.id], accion: null, confianza: 0.9 });
    c.read('documentos.buscar', tk.tipo, 'Procedimiento vigente encontrado');
    const titulo = { caida_enlace: 'RB-01 Conmutación a respaldo', tarjeta: 'RB-02 Reinicio de tarjeta', energia: 'PR-07 Cortes de energía por zona' }[tk.tipo];
    c.act('documentos.publicar_procedimiento', { titulo: `${titulo} (lecciones de ${tk.id})` }, { razon: 'Incorporar lo aprendido en el incidente.' });
    c.out({ resumen: `«${titulo}» actualizado con lo aprendido en ${tk.id}.`, evidencias: [tk.id], accion: 'documentos.publicar_procedimiento', confianza: 0.9 });
  };

  // 40 Director de orquesta (Persona)
  H['40'] = (c) => {
    const s = S();
    const open = s.tickets.filter((t) => t.status !== 'cerrado');
    const pend = s.approvals.filter((a) => a.status === 'pendiente');
    const tasks = s.tasks.filter((k) => k.status === 'abierta');
    const paused = T.AGENTS.filter((a) => s.st[a.id].paused);
    c.read('todos.lectura.resumen', '39 agentes', `${open.length} tickets, ${pend.length} aprobaciones, ${tasks.length} tareas humanas`);
    const prios = [];
    open.filter((t) => t.prio === 'P1').forEach((t) => prios.push(`${t.id} P1 · ${t.diag}`));
    pend.slice(0, 3).forEach((a) => prios.push(`Aprobar o rechazar ${a.id}: ${a.label}`));
    paused.forEach((a) => prios.push(`${a.id} ${a.name} está en pausa`));
    if (!prios.length) prios.push('Sin prioridades abiertas: la red funciona con normalidad.');
    s.director = { t: s.t, prios, open: open.length, pend: pend.length, tasks: tasks.length };
    const d = E.date(s.t);
    if (d.getUTCHours() === 8 && d.getUTCMinutes() === 0) c.human('Revisar el resumen diario a dirección', prios.join(' · '));
    c.out({ resumen: prios[0], evidencias: [], accion: null, confianza: 0.9, requierePersona: true });
  };
})();
