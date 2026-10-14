# Proyecto: teleco-agents

Prototipo de 40 agentes de IA que hacen el trabajo de los ingenieros de una teleco,
sobre una red de telecomunicaciones SIMULADA (gemelo digital). Nada es real.
La especificación completa está en `docs/spec.md`: léela antes de cada fase.

## Reglas (no se negocian)

- Python 3.12, tipado estricto (`mypy --strict`) y Pydantic para toda salida de agente.
- Agentes con el Claude Agent SDK. Herramientas solo a través de servidores MCP
  propios en `mcp_servers/`.
- Nunca conectar con sistemas reales (equipos, OSS/BSS, tickets de producción) ni
  meter credenciales en el código. Secretos solo en variables de entorno, nunca en
  prompts ni en logs.
- Todo agente hereda de `core/agent.py`. Cada uno se define con un YAML
  (`agents/<area>/<id>_<nombre>.yaml`) y un prompt; añadir un agente no toca el núcleo.
- Ninguna acción sin su entrada en la tabla de auditoría.
- Cada agente llega con al menos 3 escenarios de prueba en `tests/scenarios/`.
- Trabaja por fases (`docs/spec.md`, "Plan por fases"). No empieces una fase hasta
  que la anterior cumpla su criterio.

## Guardarraíles que impone el núcleo (`core/`)

- Lista blanca: cualquier llamada MCP no declarada en el YAML del agente se bloquea.
- Autonomía: 0 observa · 1 actúa con aprobación · 2 actúa solo (solo acciones
  reversibles del catálogo cerrado; lo demás pasa a nivel 1).
- Radio de impacto: acción que afecte a más de N clientes (por defecto 500) requiere
  aprobación aunque el agente sea de nivel 2.
- Límites de ritmo por agente y hora: si se superan, el agente se pausa y avisa.
- Interruptor general: pone a todos los agentes en nivel 0 al instante.
- Agentes "Persona" nunca cierran su tarea: entregan un borrador asignado a un humano.
- Simulador determinista con semilla fija; datos sintéticos, sin datos personales reales.

## Comandos

- Arrancar: `docker compose up` (necesita `.env`, copia de `.env.example`)
- Arrancar sin Docker, todo en un proceso: `uv run python -m api.local` → http://localhost:8000
- Pruebas: `pytest -q` (con uv: `uv run pytest -q`)
- Escenarios: `pytest tests/scenarios -q`
- Tipos y estilo: `uv run mypy` y `uv run ruff check core simulator mcp_servers api tests`
- Panel: `cd dashboard && npm install && npm run build` (la API sirve `dashboard/dist`)

## Cómo está montado

- Herramientas: nombre canónico `red.runbooks.conmutar_respaldo` = herramienta MCP `runbooks__conmutar_respaldo`
  del servidor `red` = `mcp__red__runbooks__conmutar_respaldo` en el Agent SDK (`core/tools.py`).
- Catálogo de acciones en `core/actions_catalog.yaml`. Lo que no está ahí cuenta como acción fuera de catálogo.
- `core/control.py` es el único camino a la red: autoriza, audita antes de ejecutar, prueba en el gemelo,
  encola aprobaciones y ejecuta lo aprobado.
- Modo `guion` (sin clave, por defecto) y modo `claude` (`TELECO_AGENT_MODE=claude` + `ANTHROPIC_API_KEY`).
  Los guiones viven en `core/guiones/` y pasan por la misma política que Claude.
- El simulador se usa a través de `simulator/port.py`: es la pieza que se cambiaría por el adaptador de una red real.

## Estado

- Fase 0 terminada: `tests/test_phase0_gate.py` comprueba el criterio (evento simulado → panel con auditoría
  completa → aprobación humana → red recuperada). Agente de prueba: `tests/fixtures/agents/00_sonda.yaml`.
- Siguiente: Fase 1, agentes 01–08 del NOC, cada uno con al menos 3 escenarios.
