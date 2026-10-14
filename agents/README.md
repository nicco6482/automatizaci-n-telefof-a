# Agentes

Aquí vive cada uno de los 40 agentes, uno por fichero YAML más su prompt, agrupados por área:

```
agents/<area>/<id>_<nombre>.yaml
agents/<area>/<id>_<nombre>.prompt.md
```

Las áreas son `noc` (01–08), `movil` (09–14), `fibra` (15–20), `core_red` (21–25), `empresas` (26–30), `planificacion` (31–35), `seguridad` (36–38) y `gestion` (39–40).

La carpeta está vacía en la Fase 0. Los agentes llegan por fases (ver `docs/spec.md`), empezando por el NOC en la Fase 1. Cada agente nuevo trae al menos 3 escenarios en `tests/scenarios/<id>_<nombre>/`.

El formato lo valida `core/schemas.py` (`AgentConfig`). Ejemplo completo en `tests/fixtures/agents/00_sonda.yaml`.
