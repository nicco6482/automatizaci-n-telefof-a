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

- Arrancar: `docker compose up`
- Pruebas: `pytest -q`
- Escenarios: `pytest tests/scenarios -q`
