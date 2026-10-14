'use strict';
// Panel: dibuja el estado del motor y envía las decisiones de la persona (aprobar, rechazar, interruptor, inyectar).
(function () {
  const $ = (s) => document.querySelector(s);
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  const N = (n) => Math.round(n).toLocaleString('es-ES');
  const slug = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
  const store = { get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } } };
  let office = null;
  let S, tab = store.get('tab', 'apr'), sig = {}, hideCron = true, audF = { agent: '', tipo: '', q: '' }, lastRuns = {};

  // ---------- arranque ----------
  function boot(seed) {
    E.init(seed); S = E.S; sig = {}; lastRuns = {};
    E.onAudit = null;
    E.advance(24 * 3600);
    buildAreas(); fillTargets(); renderAll(true);
    // Oficina de muñecos (oficina.js): se engancha después del día de arranque para no animar el histórico.
    if (window.TelecoOficina && !office) office = window.TelecoOficina.mount($('#oficina'), T.AGENTS);
    if (office) E.onAudit = (row) => office.feed(row);
  }

  function opts(sel, list) { sel.innerHTML = list.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(''); }
  function initControls() {
    opts($('#fType'), T.FAULTS.map((f) => [f.id, f.name]));
    opts($('#xZone'), T.ZONES.map((z) => [z.id, z.name]));
    opts($('#bTopic'), T.BUSINESS.map((b) => [b.topic, b.name]));
    $('#xZone').value = 'TRI';
    $('#fType').addEventListener('change', fillTargets);
    $('#btnFault').addEventListener('click', () => {
      const tipo = $('#fType').value, tg = $('#fTarget').value, o = {};
      if (tg === '_con') o.backup = true; else if (tg === '_sin') o.backup = false; else if (tg.startsWith('ACC') || tg.startsWith('AGG')) o.node = tg; else if (tg && tg !== '_any') o.zone = tg;
      const corr = E.inject(tipo, o); toast(`${corr} inyectada`); renderAll(true);
    });
    $('#btnExt').addEventListener('click', () => { const corr = E.inject($('#xType').value, { zone: $('#xZone').value }); toast(`${corr} lanzado`); renderAll(true); });
    $('#btnBiz').addEventListener('click', () => { const corr = E.business($('#bTopic').value); toast(`${corr} publicado`); renderAll(true); });
    $('#btnSec').addEventListener('click', () => { E.inject('seguridad'); setTab('aud'); });
    $('#btnRate').addEventListener('click', () => { E.inject('ritmo'); toast('Prueba de ritmo lanzada sobre 12 Ahorrador'); });
    $('#umbral').addEventListener('change', (e) => { const v = Math.max(0, parseInt(e.target.value, 10) || 0); E.setUmbral(v); });
    $('#btnPlay').addEventListener('click', () => { S.running = !S.running; $('#btnPlay').textContent = S.running ? 'Pausar' : 'Reanudar'; });
    $('#speed').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      S.speed = +b.dataset.v; [...$('#speed').children].forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    });
    $('#btnReset').addEventListener('click', () => { const sp = S.speed; boot(parseInt($('#seed').value, 10) || 42); S.speed = sp; $('#btnPlay').textContent = 'Pausar'; $('#kill').setAttribute('aria-pressed', 'false'); $('#kill').textContent = 'Interruptor general'; });
    $('#kill').addEventListener('click', () => {
      const on = !S.kill; E.setKill(on);
      $('#kill').setAttribute('aria-pressed', String(on)); $('#kill').textContent = on ? 'Interruptor activo: todos en nivel 0' : 'Interruptor general';
      renderAll(true);
    });
    $('#tabs').addEventListener('click', (e) => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
    $('#tabBody').addEventListener('click', onTabClick);
    $('#tabBody').addEventListener('change', onTabChange);
    $('#tabBody').addEventListener('input', (e) => { if (e.target.id === 'audQ') { audF.q = e.target.value.trim(); sig.tab = null; } });
    $('#areas').addEventListener('click', (e) => { const b = e.target.closest('[data-agent]'); if (b) openAgent(b.dataset.agent); });
    $('#drawer').addEventListener('click', onDrawerClick);
    const cv = $('#map');
    cv.addEventListener('mousemove', (e) => hover(e));
    cv.addEventListener('mouseleave', () => { $('#mapTip').textContent = 'Pasa el ratón por el mapa para ver un nodo o una celda.'; });
  }

  function fillTargets() {
    const t = $('#fType').value, acc = S.nodes.filter((n) => n.type === 'acc');
    let list = [['_any', 'Aleatorio']];
    if (t === 'caida_enlace') list = [['_con', 'Nodo con respaldo (aleatorio)'], ['_sin', 'Nodo sin respaldo (aleatorio)'], ...acc.map((n) => [n.id, `${n.id} · ${n.backup ? 'con' : 'sin'} respaldo · ${N(n.ftth)} clientes`])];
    else if (t === 'tarjeta_degradada') list = [['_any', 'Aleatorio'], ...acc.map((n) => [n.id, `${n.id} · ${N(n.ftth)} clientes`])];
    else if (t === 'interferencia') list = [['_any', 'Zona aleatoria'], ...T.ZONES.map((z) => [z.id, z.name])];
    opts($('#fTarget'), list);
  }

  let toastT;
  function toast(msg) { const el = $('#mapTip'); el.textContent = msg; clearTimeout(toastT); toastT = setTimeout(() => { el.textContent = ''; }, 2500); }

  function setTab(t) {
    tab = t; store.set('tab', t); sig.tab = null;
    [...$('#tabs').children].forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === t)));
    renderTab(true);
  }

  // ---------- bucle ----------
  let acc = 0;
  setInterval(() => {
    if (!S) return;
    if (S.running) E.advance(S.speed * 0.2);
    acc++;
    renderClock(); drawMap();
    if (office) { const h = E.date(S.t).getUTCHours(); office.setFx({ alarm: S.faults.some((f) => f.active), kill: S.kill, night: h >= 22 || h < 7 ? 0.6 : 0 }); }
    if (acc % 2 === 0) { renderMetrics(); renderAgents(); renderTab(false); renderBadges(); }
    if (acc % 5 === 0) renderSparks();
  }, 200);

  function renderAll() {
    renderClock(); renderMetrics(); renderAgents(); renderBadges(); renderSparks(); drawMap(); sig.tab = null; renderTab(true); }
  function renderClock() { $('#clkDay').textContent = E.fmtDay(S.t); $('#clkTime').textContent = E.fmt(S.t); }

  // ---------- métricas ----------
  function renderMetrics() {
    const done = S.scen.filter((r) => r.status !== 'en curso'), pass = done.filter((r) => r.status === 'superado').length;
    const fp = S.m.falseTotal ? (S.m.falseFiltered / S.m.falseTotal) * 100 : null;
    const d = S.m.diag.length ? S.m.diag.reduce((a, x) => a + x.s, 0) / S.m.diag.length : null;
    const cost = S.m.costDay[E.dayKey(S.t)] || 0;
    const tokens = T.AGENTS.reduce((a, x) => a + S.st[x.id].tokens, 0);
    const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
    const M = [
      ['Escenarios superados', done.length ? `${Math.round((pass / done.length) * 100)} %` : '—', `${pass} de ${done.length} terminados · objetivo ≥ 90 %`, !done.length ? '' : pass / done.length >= 0.9 ? 'ok' : 'crit'],
      ['Alarmas falsas filtradas', fp == null ? '—' : `${fp.toFixed(0)} %`, `${S.m.falseFiltered} de ${S.m.falseTotal} · objetivo ≥ 80 %`, fp == null ? '' : fp >= 80 ? 'ok' : 'crit'],
      ['Tiempo de diagnóstico', d == null ? '—' : mmss(d), `media de ${S.m.diag.length} incidencias · objetivo < 2 min`, d == null ? '' : d < 120 ? 'ok' : 'warn'],
      ['Fuera de lista blanca ejecutadas', String(E.outsideExecuted()), `${S.m.blocked} intentos bloqueados · objetivo 0`, E.outsideExecuted() === 0 ? 'ok' : 'crit'],
      ['Acciones sin auditoría', String(E.unaudited()), `${N(S.m.executed)} ejecutadas · ${N(S.m.auditTotal)} registros · objetivo 0`, E.unaudited() === 0 ? 'ok' : 'crit'],
      ['Coste API hoy (simulado)', `${cost.toFixed(2)} $`, `${N(tokens)} tokens en total · medido y visible`, 'ok'],
    ];
    const html = M.map(([l, v, g, s]) => `<div class="metric" data-s="${s}"><span class="lbl">${l}</span><span class="v">${v}</span><span class="goal">${g}</span></div>`).join('');
    if (html !== sig.metrics) { $('#metrics').innerHTML = html; sig.metrics = html; }
  }
  function renderBadges() {
    const p = S.approvals.filter((a) => a.status === 'pendiente').length;
    $('#bApr').textContent = p; $('#bApr').classList.toggle('hot', p > 0);
    $('#bAud').textContent = S.m.auditTotal > 9999 ? Math.round(S.m.auditTotal / 1000) + 'k' : S.m.auditTotal;
    $('#bTck').textContent = S.tickets.filter((t) => t.status !== 'cerrado').length;
    const k = S.tasks.filter((t) => t.status === 'abierta').length;
    $('#bTar').textContent = k; $('#bTar').classList.toggle('hot', k > 0);
  }

  // ---------- agentes ----------
  function buildAreas() {
    $('#areas').innerHTML = T.AREAS.map((ar) => `<div class="area"><h3>${esc(ar.name)}<span>${ar.range}</span></h3>${T.AGENTS.filter((a) => a.area === ar.id).map((a) => `
      <button type="button" class="ag" data-agent="${a.id}" id="ag${a.id}">
        <span class="n">${a.id}</span><span class="nm">${esc(a.name)}${a.persona ? ' <span class="chip warn">persona</span>' : ''}</span>
        <span class="side"><span class="dot" id="dot${a.id}"></span><b class="lv lv${a.level}">N${a.level}</b></span>
        <span class="last" id="last${a.id}">${esc(a.output)}</span>
      </button>`).join('')}</div>`).join('');
  }
  function renderAgents() {
    T.AGENTS.forEach((a) => {
      const st = S.st[a.id];
      const dot = $('#dot' + a.id);
      const cls = st.paused ? 'pausa' : st.status === 'esperando aprobación' ? 'esperando' : S.t - (st.last || -1e9) < 120 ? 'trabajando' : '';
      dot.className = 'dot ' + cls; dot.title = st.paused ? 'en pausa' : cls === 'esperando' ? 'esperando aprobación' : cls ? 'trabajando' : 'inactivo';
      const txt = st.lastOut ? `${E.fmt(st.last)} · ${st.lastOut.resumen}` : `Sin ejecuciones · ${a.output}`;
      const el = $('#last' + a.id); if (el.textContent !== txt) el.textContent = txt;
      if (lastRuns[a.id] !== undefined && st.runs > lastRuns[a.id] && a.id !== '40' && a.id !== '06') { const b = $('#ag' + a.id); b.classList.remove('flash'); void b.offsetWidth; b.classList.add('flash'); }
      lastRuns[a.id] = st.runs;
      const lv = $('#ag' + a.id + ' .lv');
      const eff = S.kill ? 0 : a.level; lv.className = `lv lv${eff}`; lv.textContent = `N${eff}`;
    });
  }

  function yaml(a) {
    return [`id: ${a.id}_${slug(a.name)}`, `nombre: ${a.name}`, `area: ${a.area}`, `disparadores: [${a.triggers.map((t) => T.TRIGGER_LABEL[t] ? `${t}  # ${T.TRIGGER_LABEL[t]}` : t).join(', ')}]`,
      'herramientas:  # lista blanca: el núcleo bloquea cualquier otra', ...a.tools.map((t) => `  - ${t}`),
      `autonomia: ${a.level}  # ${['observa', 'actúa con aprobación', 'actúa solo (catálogo cerrado)'][a.level]}`, `escalado: ${a.escala}`,
      `limites: {pasos: ${a.limites.pasos}, tokens: ${a.limites.tokens}, acciones_hora: ${a.limites.accionesHora}}`,
      `persona: ${a.persona}`, `prompt: agents/${a.area}/${a.id}_${slug(a.name)}.prompt.md`, 'salida: AgentOutput  # resumen, evidencias, accion_propuesta, confianza, requiere_persona'].join('\n');
  }
  let openId = null;
  function openAgent(aid) { openId = aid; renderDrawer(); const d = $('#drawer'); if (!d.open) d.showModal(); }
  function renderDrawer() {
    const a = T.agentById[openId], st = S.st[a.id];
    const rows = S.audit.filter((e) => e.agent === a.id).slice(0, 12);
    const trig = a.triggers[0];
    const canFire = trig.startsWith('cron') || T.BUSINESS.some((b) => b.topic === trig) || trig === 'event.scheduled';
    const actsH = st.acts.filter((x) => x > S.t - 3600).length;
    $('#drawer').innerHTML = `<div class="dlg-h"><div><span class="lbl">${esc(T.AREAS.find((x) => x.id === a.area).name)}</span><h2 id="dlgTitle">${a.id} ${esc(a.name)}</h2><p class="muted" style="margin:4px 0 0">${esc(a.desc)}</p></div><button type="button" data-close>Cerrar</button></div>
      <div class="dlg-b">
        <div class="toolbar"><b class="lv lv${a.level}">Nivel ${a.level}</b>${a.persona ? '<span class="chip warn">Persona: entrega borrador, no cierra</span>' : ''}<span class="chip">${st.runs} ejecuciones</span><span class="chip">${N(st.tokens)} tokens · ${st.cost.toFixed(3)} $</span><span class="chip ${actsH && a.limites.accionesHora && actsH >= a.limites.accionesHora * 0.8 ? 'warn' : ''}">${actsH}/${a.limites.accionesHora || '—'} acciones esta hora</span>${st.paused ? '<span class="chip crit">En pausa</span>' : ''}</div>
        <div class="toolbar">${canFire ? `<button type="button" class="primary" data-fire="${trig}">Lanzar disparador ${esc(trig)}</button>` : `<span class="muted">Se activa con ${esc(trig)}: inyecta una avería para verlo trabajar.</span>`}${st.paused ? '<button type="button" data-resume>Reanudar</button>' : ''}</div>
        <div><span class="lbl">agents/${a.area}/${a.id}_${slug(a.name)}.yaml</span><pre class="yaml">${esc(yaml(a))}</pre></div>
        <div><span class="lbl">Última salida validada</span><pre class="json">${esc(st.lastOut ? JSON.stringify(st.lastOut, null, 2) : 'Todavía no ha ejecutado.')}</pre></div>
        <div><span class="lbl">Auditoría reciente</span>${rows.length ? rows.map((e) => `<div class="row"><div class="hd"><span class="t">${E.fmt(e.t, 1)}</span>${chipDec(e)}<code>${esc(e.herramienta || e.tipo)}</code></div><div class="wrap">${esc(e.resultado)}</div></div>`).join('') : '<p class="empty">Sin registros.</p>'}</div>
      </div>`;
  }
  function onDrawerClick(e) {
    const t = e.target;
    if (t.closest('[data-close]') || t === $('#drawer')) { $('#drawer').close(); openId = null; return; }
    const f = t.closest('[data-fire]');
    if (f) {
      const topic = f.dataset.fire;
      if (topic === 'event.scheduled') E.inject('evento', { zone: 'REM' });
      else if (T.BUSINESS.some((b) => b.topic === topic)) E.business(topic);
      else E.fire(topic, topic === 'cron.nocturno' ? { fase: E.date(S.t).getUTCHours() < 6 || E.date(S.t).getUTCHours() >= 20 ? 'apagar' : 'encender' } : {});
      E.advance(1); renderDrawer(); return;
    }
    if (t.closest('[data-resume]')) { E.resume(openId); renderDrawer(); }
  }

  // ---------- pestañas ----------
  function chipDec(e) {
    const d = e.decision || e.tipo;
    const c = /bloquead|ko|rechaz|pausa|inválida|límite/.test(d) ? 'crit' : /cola|propuesta|persona/.test(d) ? 'warn' : /ejecutada|ok|válida/.test(d) ? 'ok' : '';
    return `<span class="chip ${c}">${esc(d)}</span>`;
  }
  const agName = (aid) => (T.agentById[aid] ? `${aid} ${T.agentById[aid].name}` : aid);

  function renderTab(force) {
    let key;
    if (tab === 'apr') key = S.approvals.map((a) => a.id + a.status).join();
    else if (tab === 'bus') key = (S.busLog[0] && S.busLog[0].id) + hideCron;
    else if (tab === 'aud') key = S.m.auditTotal + JSON.stringify(audF);
    else if (tab === 'tck') key = S.tickets.map((t) => t.id + t.status + t.notes.length + t.external + t.slaAlert).join();
    else if (tab === 'tar') key = S.tasks.map((t) => t.id + t.status).join();
    else if (tab === 'esc') key = S.scen.map((r) => r.status + r.checks.join()).join();
    else key = S.director && S.director.t + '' + S.outputs.length + S.docs.length;
    if (!force && key === sig.tab) return;
    sig.tab = key;
    const body = $('#tabBody');
    const keepFocus = document.activeElement && body.contains(document.activeElement) ? document.activeElement.id : null;
    const html = { apr: tabApr, bus: tabBus, aud: tabAud, tck: tabTck, tar: tabTar, esc: tabEsc, dir: tabDir }[tab]();
    body.innerHTML = html;
    if (keepFocus && $('#' + keepFocus)) { const el = $('#' + keepFocus); el.focus(); if (el.setSelectionRange && el.value) el.setSelectionRange(el.value.length, el.value.length); }
  }

  const comments = {};
  function tabApr() {
    const pend = S.approvals.filter((a) => a.status === 'pendiente'), done = S.approvals.filter((a) => a.status !== 'pendiente').slice(0, 30);
    let h = pend.length ? '' : '<p class="empty">No hay acciones esperando. Las de nivel 1, las que salen del catálogo cerrado y las que superan el radio de impacto aparecerán aquí con su evidencia y el resultado en el gemelo.</p>';
    h += pend.map((a) => `<div class="appr">
      <div class="hd" style="display:flex;flex-wrap:wrap;gap:6px;align-items:baseline"><b class="mono">${a.id}</b><span>${esc(agName(a.agent))}</span><span class="chip warn">${esc(a.motivo)}</span><span class="t mono muted">${E.fmt(a.t, 1)}</span></div>
      <div><b>${esc(a.label)}</b> <code class="muted">${esc(a.fn)}</code></div>
      ${a.razon ? `<div class="muted">${esc(a.razon)}</div>` : ''}
      ${a.evidencia.length ? `<ul>${a.evidencia.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      ${a.gemelo ? `<div class="twin">${esc(a.gemelo.detalle)}</div>` : '<div class="muted" style="font-size:13px">Acción sin prueba en gemelo (no cambia configuración).</div>'}
      ${a.impacto ? `<div class="muted" style="font-size:13px">Clientes afectados: <b class="num">${N(a.impacto)}</b></div>` : ''}
      <div class="act"><input id="c_${a.id}" placeholder="Comentario (opcional)" value="${esc(comments[a.id] || '')}" aria-label="Comentario para ${a.id}"><button type="button" class="primary" data-ok="${a.id}">Aprobar y ejecutar</button><button type="button" class="no" data-no="${a.id}">Rechazar</button></div>
    </div>`).join('');
    if (done.length) h += `<h3 style="margin:14px 0 4px">Decididas</h3>` + done.map((a) => `<div class="row"><div class="hd"><span class="t">${E.fmt(a.decidedAt)}</span><span class="chip ${a.status === 'aprobada' ? 'ok' : 'crit'}">${a.status}</span><b class="mono">${a.id}</b><span>${esc(a.label)}</span></div>${a.comment ? `<div class="muted">«${esc(a.comment)}»</div>` : ''}</div>`).join('');
    return h;
  }
  function tabBus() {
    const list = S.busLog.filter((m) => !hideCron || !m.topic.startsWith('cron')).slice(0, 150);
    return `<div class="toolbar"><label><input type="checkbox" id="hideCron" ${hideCron ? 'checked' : ''}> Ocultar los ticks de cron</label><span class="muted">Redis Streams simulado: cada mensaje activa a los agentes suscritos.</span></div>` +
      (list.length ? list.map((m) => `<div class="row"><div class="hd"><span class="t">${E.fmt(m.t, 1)}</span><span class="chip acc">${esc(m.topic)}</span><span class="muted">de ${esc(agName(m.from))}</span>${m.corr ? `<code>${esc(m.corr)}</code>` : ''}</div><div class="muted">${m.subs.length ? '→ ' + m.subs.map(agName).map(esc).join(', ') : 'sin suscriptores (lo consume el motor)'}${m.payload && (m.payload.code || m.payload.ticket || m.payload.group) ? ' · ' + esc(m.payload.code || m.payload.ticket || m.payload.group) : ''}</div></div>`).join('') : '<p class="empty">Aún no hay mensajes.</p>');
  }
  function tabAud() {
    let list = S.audit;
    if (audF.agent) list = list.filter((e) => e.agent === audF.agent);
    if (audF.tipo === 'acc') list = list.filter((e) => e.tipo === 'acción' || e.tipo === 'gemelo');
    if (audF.tipo === 'blq') list = list.filter((e) => e.tipo === 'bloqueo' || /pausa|rechaz|ko/.test(e.decision));
    if (audF.tipo === 'sal') list = list.filter((e) => e.tipo === 'salida');
    if (audF.tipo === 'per') list = list.filter((e) => e.aprobadoPor);
    if (audF.q) { const q = audF.q.toLowerCase(); list = list.filter((e) => (e.corr + ' ' + e.herramienta + ' ' + e.resultado + ' ' + e.entrada).toLowerCase().includes(q)); }
    const shown = list.slice(0, 250);
    const agOpts = [['', 'Todos los agentes'], ...T.AGENTS.map((a) => [a.id, `${a.id} ${a.name}`]), ['SIM', 'Simulador'], ['NÚCLEO', 'Núcleo'], ['PERSONA', 'Personas'], ['NEGOCIO', 'Negocio']];
    return `<div class="toolbar">
      <select id="audAgent" aria-label="Filtrar por agente">${agOpts.map(([v, l]) => `<option value="${esc(v)}" ${v === audF.agent ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
      <select id="audTipo" aria-label="Filtrar por tipo">${[['', 'Todos los pasos'], ['acc', 'Acciones y gemelo'], ['blq', 'Bloqueos, pausas y rechazos'], ['sal', 'Salidas de agente'], ['per', 'Decisiones de personas']].map(([v, l]) => `<option value="${v}" ${v === audF.tipo ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <input id="audQ" placeholder="Buscar incidente, herramienta…" value="${esc(audF.q)}" aria-label="Buscar en la auditoría">
      <span class="muted">${N(list.length)} de ${N(S.m.auditTotal)} · solo se añaden filas</span></div>
      <div class="tablewrap"><table class="audit"><thead><tr><th>Hora</th><th>Quién</th><th>Paso</th><th>Entrada → resultado</th><th>Decisión</th><th>Aprobó</th><th>Coste</th></tr></thead><tbody>
      ${shown.map((e) => `<tr class="${e.tipo === 'bloqueo' ? 'bloq' : ''}"><td class="mono num">${E.fmt(e.t, 1)}</td><td>${esc(agName(e.agent))}${e.corr ? `<br><code class="muted">${esc(e.corr)}</code>` : ''}</td><td>${esc(e.tipo)}${e.herramienta ? `<br><code>${esc(e.herramienta)}</code>` : ''}</td>
      <td class="res wrap">${e.entrada ? `<span class="muted">${esc(e.entrada.slice(0, 140))}</span><br>` : ''}${esc(e.resultado)}${e.razonamiento ? `<br><i class="muted">${esc(e.razonamiento)}</i>` : ''}${e.comentario ? `<br>«${esc(e.comentario)}»` : ''}</td>
      <td>${e.decision ? chipDec(e) : ''}</td><td>${esc(e.aprobadoPor)}</td><td class="mono num">${e.tokens ? `${N(e.tokens)}<br>${e.coste.toFixed(4)} $` : ''}</td></tr>`).join('')}
      </tbody></table></div>`;
  }
  function tabTck() {
    if (!S.tickets.length) return '<p class="empty">Sin tickets. Inyecta una avería: el Triaje abrirá uno con prioridad y diagnóstico.</p>';
    return S.tickets.slice(0, 80).map((t) => `<div class="row"><div class="hd"><b class="mono">${t.id}</b><span class="chip ${t.prio === 'P1' ? 'crit' : t.prio === 'P2' ? 'warn' : ''}">${t.prio}</span><span class="chip ${t.status === 'cerrado' ? 'ok' : 'acc'}">${t.status}</span>${t.external ? `<span class="chip warn">causa externa: ${esc(t.external)}</span>` : ''}${t.slaAlert ? '<span class="chip crit">riesgo SLA</span>' : ''}<span class="t">${E.fmt(t.t)}</span><code class="muted">${esc(t.corr)}</code></div>
      <div><b>${esc(t.diag)}</b></div><div class="muted">${esc(T.zoneById[t.zone] ? T.zoneById[t.zone].name : t.zone)} · ${esc(t.node || '')} · ${N(t.impacto)} clientes FTTH · ${t.ents.length} empresas</div>
      <div class="muted mono" style="font-size:12px">${t.notes.slice(-3).map(esc).join('<br>')}</div></div>`).join('');
  }
  function tabTar() {
    const open = S.tasks.filter((k) => k.status === 'abierta'), closed = S.tasks.filter((k) => k.status !== 'abierta').slice(0, 30);
    const hint = { campo: 'Al cerrarla, el técnico ha reparado la avería.', contrata: 'Al cerrarla, la orden de trabajo se da por terminada.', pausa: 'Al cerrarla, el agente se reanuda.' };
    let h = open.length ? '' : '<p class="empty">Nada pendiente para personas. Aquí llegan los borradores de los agentes «Persona», los avisos de guardia y los agentes en pausa.</p>';
    h += open.map((k) => `<div class="appr"><div class="hd" style="display:flex;flex-wrap:wrap;gap:6px;align-items:baseline"><b class="mono">${k.id}</b><span>${esc(agName(k.agent))}</span><span class="t mono muted">${E.fmt(k.t)}</span>${k.corr ? `<code class="muted">${esc(k.corr)}</code>` : ''}</div>
      <b>${esc(k.title)}</b><div class="muted wrap">${esc(k.detail)}</div>${hint[k.kind] ? `<div style="font-size:13px">${hint[k.kind]}</div>` : ''}
      <div class="act"><button type="button" class="primary" data-task="${k.id}">Revisado, lo cierro yo</button></div></div>`).join('');
    if (closed.length) h += '<h3 style="margin:14px 0 4px">Cerradas</h3>' + closed.map((k) => `<div class="row"><div class="hd"><span class="t">${E.fmt(k.closedAt)}</span><span class="chip ${k.status === 'cerrada' ? 'ok' : ''}">${k.status === 'cerrada' ? 'cerrada por persona' : 'sin objeto: el ticket se resolvió'}</span><span>${esc(k.title)}</span></div></div>`).join('');
    return h;
  }
  function tabEsc() {
    const runs = S.scen;
    return `<div class="toolbar"><button type="button" class="primary" data-escall>Ejecutar los ${T.SCENARIOS.length} escenarios</button><span class="muted">Cada escenario inyecta su avería en la red viva y comprueba el resultado esperado en la auditoría (máx. 3 h simuladas).</span></div>` +
      T.SCENARIOS.map((sc) => { const last = runs.find((r) => r.sc.id === sc.id); const n = runs.filter((r) => r.sc.id === sc.id).length, ok = runs.filter((r) => r.sc.id === sc.id && r.status === 'superado').length;
        return `<div class="row"><div class="hd"><b class="mono">${sc.id}</b><b>${esc(sc.name)}</b>${last ? `<span class="chip ${last.status === 'superado' ? 'ok' : last.status === 'fallido' ? 'crit' : 'acc'}">${last.status}</span><code class="muted">${esc(last.corr)}</code>` : ''}${n ? `<span class="muted">${ok}/${n} superados</span>` : ''}<button type="button" data-esc="${sc.id}" style="margin-left:auto">Ejecutar</button></div>
        <div class="muted" style="font-size:13px">${sc.expect.map((x, i) => `${last ? (last.checks[i] ? '✓' : last.status === 'en curso' ? '…' : '✗') : '·'} ${esc(x)}`).join('<br>')}</div></div>`; }).join('');
  }
  function tabDir() {
    const d = S.director;
    return `<h3>Resumen a dirección${d ? ` <span class="muted mono" style="font-size:12px">${E.fmt(d.t)}</span>` : ''}</h3>
      ${d ? `<p class="muted">${d.open} tickets abiertos · ${d.pend} aprobaciones pendientes · ${d.tasks} tareas humanas</p><ol>${d.prios.map((p) => `<li>${esc(p)}</li>`).join('')}</ol>` : '<p class="empty">El Director de orquesta resume cada tick.</p>'}
      <h3 style="margin-top:14px">Procedimientos publicados</h3>${S.docs.length ? S.docs.slice(0, 10).map((x) => `<div class="row"><div class="hd"><span class="t">${E.fmt(x.t)}</span>${esc(x.title)}</div></div>`).join('') : '<p class="muted">Ninguno todavía.</p>'}
      <h3 style="margin-top:14px">Últimas salidas de agentes</h3>${S.outputs.filter((o) => o.agent !== '40' && o.agent !== '06').slice(0, 25).map((o) => `<div class="row"><div class="hd"><span class="t">${E.fmt(o.t, 1)}</span><b>${esc(agName(o.agent))}</b><span class="chip">confianza ${o.out.confianza}</span>${o.out.requiere_persona ? '<span class="chip warn">requiere persona</span>' : ''}</div><div class="wrap">${esc(o.out.resumen)}</div></div>`).join('')}`;
  }
  function onTabClick(e) {
    const t = e.target;
    const ok = t.closest('[data-ok]'), no = t.closest('[data-no]');
    if (ok || no) { const idv = (ok || no).dataset[ok ? 'ok' : 'no']; const c = ($('#c_' + idv) || {}).value || ''; E.decide(idv, !!ok, c); delete comments[idv]; renderAll(true); return; }
    const tk = t.closest('[data-task]'); if (tk) { E.closeTask(tk.dataset.task); renderAll(true); return; }
    const sc = t.closest('[data-esc]'); if (sc) { E.runScenario(T.SCENARIOS.find((x) => x.id === sc.dataset.esc)); sig.tab = null; renderTab(true); return; }
    if (t.closest('[data-escall]')) { T.SCENARIOS.forEach((x, i) => { E.runScenario(x); E.advance(60); }); renderAll(true); }
  }
  function onTabChange(e) {
    const t = e.target;
    if (t.id === 'hideCron') { hideCron = t.checked; sig.tab = null; renderTab(true); }
    if (t.id === 'audAgent') { audF.agent = t.value; renderTab(true); }
    if (t.id === 'audTipo') { audF.tipo = t.value; renderTab(true); }
  }
  document.addEventListener('input', (e) => { if (e.target.id && e.target.id.startsWith('c_')) comments[e.target.id.slice(2)] = e.target.value; });

  // ---------- mapa ----------
  let colors = {}, colorsAt = 0;
  function readColors() {
    if (Date.now() - colorsAt < 2000) return colors;
    const cs = getComputedStyle(document.documentElement);
    ['--ink', '--muted', '--accent', '--ok', '--warn', '--crit', '--map-bg', '--map-zone', '--map-link', '--panel', '--line', '--f-display', '--f-mono'].forEach((k) => (colors[k] = cs.getPropertyValue(k).trim()));
    colorsAt = Date.now(); return colors;
  }
  function drawMap() {
    const cv = $('#map'), dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight; if (!W) return;
    if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext('2d'), C = readColors();
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const X = (x) => 14 + x * (W - 28), Y = (y) => 14 + y * (H - 28), R = Math.min(W, H);
    T.ZONES.forEach((z) => {
      g.beginPath(); g.ellipse(X(z.x), Y(z.y), z.r * (W - 28) * 1.25, z.r * (H - 28) * 1.6, 0, 0, Math.PI * 2); g.fillStyle = C['--map-zone']; g.fill();
      g.fillStyle = C['--muted']; g.font = `600 ${Math.max(11, R * 0.026)}px ${C['--f-display']}`; g.textAlign = 'center';
      g.fillText(z.name.toUpperCase(), X(z.x), Y(z.y) - z.r * (H - 28) * 1.6 + 14);
    });
    S.storms.forEach((s) => { const z = T.zoneById[s.zone]; g.save(); g.beginPath(); g.ellipse(X(z.x), Y(z.y), z.r * (W - 28) * 1.4, z.r * (H - 28) * 1.8, 0, 0, Math.PI * 2); g.setLineDash([5, 4]); g.strokeStyle = C['--crit']; g.lineWidth = 1.5; g.stroke(); g.restore(); });
    S.power.forEach((p) => { const z = T.zoneById[p.zone]; g.save(); g.beginPath(); g.ellipse(X(z.x), Y(z.y), z.r * (W - 28) * 1.25, z.r * (H - 28) * 1.6, 0, 0, Math.PI * 2); g.clip(); g.strokeStyle = C['--crit']; g.globalAlpha = 0.18; g.lineWidth = 1; for (let i = -H; i < W; i += 7) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i + H, H); g.stroke(); } g.restore(); });
    S.events.filter((e) => S.t < e.end).forEach((e) => { const z = T.zoneById[e.zone]; const live = S.t >= e.start; g.beginPath(); g.ellipse(X(z.x), Y(z.y), z.r * (W - 28) * 1.35, z.r * (H - 28) * 1.7, 0, 0, Math.PI * 2); g.strokeStyle = C['--warn']; g.lineWidth = live ? 3 : 1.5; g.stroke(); g.fillStyle = C['--warn']; g.font = `600 12px ${C['--f-display']}`; g.textAlign = 'center'; g.fillText(`${e.name}${live ? ' · en curso' : ' · ' + E.fmt(e.start)}`, X(z.x), Y(z.y) + z.r * (H - 28) * 1.7 + 14); });
    S.links.forEach((l) => {
      const a = S.nodeById[l.a], b = S.nodeById[l.b];
      g.beginPath(); g.moveTo(X(a.x), Y(a.y)); g.lineTo(X(b.x), Y(b.y));
      g.setLineDash(l.role === 'respaldo' && l.status === 'reserva' ? [3, 4] : l.status === 'caído' ? [6, 3] : []);
      g.strokeStyle = l.status === 'caído' ? C['--crit'] : l.role === 'respaldo' && l.status === 'activo' ? C['--warn'] : C['--map-link'];
      g.lineWidth = l.role === 'troncal' ? 1.8 : l.status === 'caído' || (l.role === 'respaldo' && l.status === 'activo') ? 2.2 : 1;
      g.globalAlpha = l.role === 'respaldo' && l.status === 'reserva' ? 0.6 : 1; g.stroke(); g.globalAlpha = 1;
    });
    g.setLineDash([]);
    const cr = Math.max(2, R * 0.0055);
    S.cells.forEach((c) => {
      const col = c.status !== 'ok' ? C['--crit'] : c.interf ? C['--warn'] : c.load > 0.85 ? C['--warn'] : C['--ok'];
      g.beginPath(); g.arc(X(c.x), Y(c.y), cr, 0, Math.PI * 2);
      if (c.carriersOn < c.carriers && c.status === 'ok') { g.strokeStyle = col; g.lineWidth = 1; g.stroke(); }
      else { g.fillStyle = col; g.globalAlpha = c.status !== 'ok' || c.interf ? 1 : 0.35 + Math.min(0.65, c.load * 0.8); g.fill(); g.globalAlpha = 1; }
      if (c.interf) { g.beginPath(); g.arc(X(c.x), Y(c.y), cr + 3, 0, Math.PI * 2); g.strokeStyle = C['--warn']; g.lineWidth = 1; g.stroke(); }
    });
    S.nodes.forEach((n) => {
      const s = n.type === 'core' ? 9 : n.type === 'agg' ? 7 : 5;
      const col = n.status === 'aislado' ? C['--crit'] : n.status === 'en respaldo' || n.card === 'degradada' ? C['--warn'] : C['--accent'];
      g.fillStyle = col; g.fillRect(X(n.x) - s / 2, Y(n.y) - s / 2, s, s);
      if (n.type !== 'acc') { g.strokeStyle = C['--panel']; g.lineWidth = 1.5; g.strokeRect(X(n.x) - s / 2, Y(n.y) - s / 2, s, s); }
      if (n.type === 'core') { g.fillStyle = C['--ink']; g.font = `500 10.5px ${C['--f-mono']}`; g.textAlign = 'left'; g.fillText(n.id, X(n.x) + 8, Y(n.y) + 4); }
    });
    cv._X = X; cv._Y = Y;
  }
  function hover(e) {
    const cv = $('#map'); if (!cv._X) return;
    const rc = cv.getBoundingClientRect(), mx = e.clientX - rc.left, my = e.clientY - rc.top;
    let best = null, bd = 12;
    S.nodes.forEach((n) => { const d = Math.hypot(cv._X(n.x) - mx, cv._Y(n.y) - my); if (d < bd) { bd = d; best = { n }; } });
    if (!best) S.cells.forEach((c) => { const d = Math.hypot(cv._X(c.x) - mx, cv._Y(c.y) - my); if (d < bd * 0.7) { bd = d / 0.7; best = { c }; } });
    const tip = $('#mapTip');
    if (!best) { tip.textContent = ''; return; }
    if (best.n) { const n = best.n; tip.textContent = `${n.id} · ${n.type === 'acc' ? 'acceso' : n.type === 'agg' ? 'agregación' : 'núcleo'} · ${n.status}${n.card === 'degradada' ? ' · tarjeta degradada' : ''} · ${n.vendor} ${n.fw}${n.ftth ? ` · ${N(n.ftth)} clientes FTTH` : ''}${n.type === 'acc' ? ` · ${n.backup ? 'respaldo ' + n.backup : 'sin respaldo'}` : ''}${n.drift ? ' · fuera de estándar' : ''}`; }
    else { const c = best.c; tip.textContent = `${c.id} · ${c.tech} · ${c.status} · carga ${Math.round(c.load * 100)} % · ${N(c.users)} usuarios · portadoras ${c.carriersOn}/${c.carriers} · SINR ${c.sinr.toFixed(1)} dB · inclinación ${c.params.tilt}°`; }
  }

  // ---------- minigráficos ----------
  function spark(svg, data, color) {
    if (data.length < 2) { svg.innerHTML = ''; return; }
    const max = Math.max(1, ...data.map((d) => d.v)), w = 300, h = 46, step = w / 95;
    const pts = data.map((d, i) => [i * step, h - 3 - (d.v / max) * (h - 8)]);
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
    const last = pts[pts.length - 1];
    svg.innerHTML = `<path d="M0,${h - 3}H${w}" stroke="var(--line)" stroke-width="1" fill="none"/><path d="${line}L${last[0]},${h - 3}L0,${h - 3}Z" fill="${color}" fill-opacity=".12"/><path d="${line}" stroke="${color}" stroke-width="1.6" fill="none" vector-effect="non-scaling-stroke"/><circle cx="${last[0]}" cy="${last[1]}" r="2.6" fill="${color}"/>`;
  }
  function renderSparks() {
    spark($('#spTraffic'), S.series.traffic, 'var(--accent)'); spark($('#spAlarms'), S.series.alarms, 'var(--warn)');
    const t = S.series.traffic[S.series.traffic.length - 1], a = S.series.alarms[S.series.alarms.length - 1];
    $('#trafNow').textContent = t ? `${t.v.toFixed(1)} Gbps` : ''; $('#almNow').textContent = a ? `${a.v}` : '';
  }

  // ---------- inicio con un incidente ya en marcha ----------
  E.init(42); S = E.S;
  initControls();
  buildAreas(); fillTargets();
  E.advance(24 * 3600 + 1800);
  E.runScenario(T.SCENARIOS[0]);
  E.advance(240);
  setTab(['apr', 'bus', 'aud', 'tck', 'tar', 'esc', 'dir'].includes(tab) ? tab : 'apr');
  renderAll(true);
  if (window.TelecoOficina) { office = window.TelecoOficina.mount($('#oficina'), T.AGENTS); E.onAudit = (row) => office.feed(row); }
  window.addEventListener('resize', () => drawMap());
})();
