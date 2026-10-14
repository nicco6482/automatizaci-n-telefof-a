# Especificación técnica: 40 agentes de IA para una teleco

14 oct 2026 · @Nico

> Transcripción a Markdown del PDF «Especificación técnica 40 agentes de IA para una teleco».

## Objetivo y alcance

Construir un prototipo funcional de 40 agentes de IA que cubren el trabajo de los ingenieros de una teleco, operando sobre una red simulada. El objetivo es demostrar el sistema de punta a punta, no conectarlo a una red real.

### Dentro del alcance

- Un orquestador y 40 agentes con la misma plantilla, agrupados en 8 áreas.
- Una red simulada (gemelo digital) que genera alarmas, tráfico, averías y clientes.
- Un panel web para ver qué hace cada agente y aprobar las acciones que lo requieran.
- Registro de auditoría de cada decisión y acción.

### Fuera del alcance

- Conexión a equipos reales (Nokia, Ericsson, Huawei), OSS/BSS o sistemas de tickets de producción.
- Trabajo físico, firma de proyectos visados y responsabilidad legal: se modelan como tareas que acaban en una persona.
- Despliegue en producción, alta disponibilidad y certificaciones.

### Supuestos

- Lenguaje Python y modelos de Claude vía API; los agentes se construyen con el Claude Agent SDK.
- Todo corre en local con Docker Compose.
- Los datos de red son sintéticos y no contienen información de clientes reales.

## Arquitectura general

Cinco piezas de software y un panel para las personas. El núcleo de control es el único camino entre un agente y la red.

```
Red simulada ──► Bus de eventos ──► 40 agentes ──► Núcleo de control
(alarmas,         (Redis Streams:     (8 áreas, un     (lista blanca,
 tráfico,          activa agentes)     YAML y un        autonomía,
 averías,                              prompt cada uno) límites)
 clientes)                                                │
   ▲                                    nivel 1: espera   │ permitido
   │                                    aprobación        ▼
   │            Persona ◄──► Panel web ◄──────────── Servidores MCP
   │            (aprueba o   (cola de aprobación     (red, tickets,
   │             rechaza      y auditoría)            inventario, docs)
   │             nivel 1)                                 │
   └──────────────────── actúa sobre la red ◄─────────────┘
```

Los eventos de la red simulada activan a los agentes. El núcleo deja pasar a los servidores MCP solo lo permitido y manda a la cola del panel lo de nivel 1, que se ejecuta cuando una persona lo aprueba.

## Stack técnico y estructura del repositorio

Stack mínimo, todo en un solo repositorio y arrancable con un comando.

| Pieza | Elección | Para qué |
|---|---|---|
| Lenguaje | Python 3.12 | Agentes, simulador y API |
| Agentes | Claude Agent SDK | Bucle de razonamiento y uso de herramientas |
| Herramientas | Servidores MCP propios | Exponer la red simulada, tickets e inventario |
| Bus de eventos | Redis Streams | Alarmas, tareas y mensajes entre agentes |
| Base de datos | PostgreSQL | Tickets, inventario, auditoría, aprobaciones |
| API | FastAPI | Backend del panel y de las aprobaciones |
| Panel | React + Vite | Ver agentes, cola de aprobaciones y auditoría |
| Entorno | Docker Compose | Levantar todo en local |
| Pruebas | pytest | Unitarias, de escenarios y de regresión |

```
teleco-agents/
├── CLAUDE.md
├── docker-compose.yml
├── core/              # plantilla de agente, orquestador, autonomía, auditoría
├── agents/
│   ├── noc/           # 01–08
│   ├── movil/         # 09–14
│   ├── fibra/         # 15–20
│   ├── core_red/      # 21–25
│   ├── empresas/      # 26–30
│   ├── planificacion/ # 31–35
│   ├── seguridad/     # 36–38
│   └── gestion/       # 39–40
├── mcp_servers/       # red, tickets, inventario, documentos, notificaciones
├── simulator/         # gemelo digital y generador de escenarios
├── api/               # FastAPI
├── dashboard/         # React
└── tests/
    └── scenarios/     # escenarios reproducibles en YAML
```

## Plantilla común de agente y niveles de autonomía

Los 40 agentes comparten una sola clase base; cada uno solo define su configuración. Así se añade un agente nuevo escribiendo un fichero YAML y su prompt, sin tocar el núcleo.

Cada agente declara en `agents/<area>/<id>_<nombre>.yaml`:

- **id y nombre**: por ejemplo `01_centinela`.
- **disparadores**: eventos del bus que lo activan (`alarm.raised`, `ticket.created`) o un horario cron.
- **herramientas**: lista blanca de herramientas MCP que puede usar; nada fuera de ella.
- **autonomía**: nivel 0, 1 o 2 (tabla de abajo).
- **escalado**: a qué agente o persona pasa lo que no sabe resolver.
- **prompt de sistema**: rol, límites y formato de salida.
- **límites**: máximo de pasos, de tokens y de acciones por hora.

| Nivel | Qué puede hacer | Ejemplos |
|---|---|---|
| 0 · Observa | Solo lee y propone; nunca actúa | Analista de inversiones, Espía |
| 1 · Actúa con aprobación | Prepara la acción y espera a que una persona la apruebe en el panel | Configurador, Gestor de actualizaciones |
| 2 · Actúa solo | Ejecuta acciones reversibles de un catálogo cerrado y lo registra | Bombero, Ahorrador |

Toda salida de agente es un JSON validado con Pydantic: resumen, evidencias, acción propuesta, nivel de confianza y si requiere persona.

## Catálogo de los 40 agentes

Cada fila es un fichero de configuración. Nivel = autonomía (0 observa, 1 con aprobación, 2 solo). «Persona» marca los agentes cuyo resultado acaba siempre en un humano.

| N.º | Agente | Área | Disparador | Herramientas MCP | Salida | Nivel |
|---|---|---|---|---|---|---|
| 01 | Centinela | NOC | alarm.raised | red.alarmas | Alarmas filtradas y agrupadas | 2 |
| 02 | Triaje | NOC | alarm.grouped | tickets, inventario | Ticket con prioridad y diagnóstico | 2 |
| 03 | Bombero | NOC | ticket.created | red.runbooks | Runbook aplicado o escalado | 2 |
| 04 | Escalador | NOC | ticket.escalated | notificaciones | Aviso a guardia con resumen | 2 |
| 05 | Forense | NOC | ticket.closed | tickets, red.historico | Informe de causa raíz | 0 |
| 06 | Guardián de SLA | NOC | cron 15 min | tickets, contratos | Alerta de riesgo de incumplimiento | 2 |
| 07 | Gestor de cambios | NOC | change.requested | cambios | Conflictos detectados | 0 |
| 08 | Meteorólogo | NOC | alarm.grouped | meteo_sim, energia_sim | Causa externa probable | 0 |
| 09 | Afinador de antenas | Móvil | cron 1 h | red.kpis, red.config | Cambio de parámetros | 1 |
| 10 | Cazainterferencias | Móvil | cron 1 h | red.kpis | Celdas afectadas | 0 |
| 11 | Planificador de eventos | Móvil | calendario | red.capacidad, eventos | Plan de capacidad temporal | 1 |
| 12 | Ahorrador | Móvil | cron nocturno | red.kpis, red.config | Portadoras apagadas y encendidas | 2 |
| 13 | Auditor de vecindad | Móvil | cron diario | red.vecinos | Correcciones de vecinos | 1 |
| 14 | Analista de mediciones | Móvil | measurement.uploaded | mediciones | Informe de cobertura · Persona | 0 |
| 15 | Diseñador de barrios | Fibra | project.requested | gis, catastro_sim | Diseño de despliegue | 0 |
| 16 | Gestor de permisos | Fibra | design.approved | documentos | Borrador de solicitud de obra | 1 |
| 17 | Doctor remoto | Fibra | customer.fault | red.ont | Diagnóstico y reinicio remoto | 2 |
| 18 | Coordinador de contratas | Fibra | workorder.created | ordenes, fotos | Asignación y validación · Persona | 1 |
| 19 | Cartógrafo | Fibra | workorder.closed | gis, inventario | Inventario actualizado | 2 |
| 20 | Adivino | Fibra | cron diario | red.ont, red.historico | Lista de equipos a cambiar | 0 |
| 21 | Previsor de capacidad | Núcleo | cron semanal | red.trafico | Previsión de saturación | 0 |
| 22 | Configurador | Núcleo | config.requested | plantillas, gemelo | Configuración probada en gemelo | 1 |
| 23 | Auditor de configuraciones | Núcleo | cron diario | red.config, plantillas | Desviaciones del estándar | 0 |
| 24 | Gestor de actualizaciones | Núcleo | firmware.released | inventario, cambios | Plan de actualización | 1 |
| 25 | Vigilante de rutas | Núcleo | route.changed | red.bgp | Alerta de desvío de rutas | 2 |
| 26 | Preventa | Empresas | quote.requested | catalogo, red.capacidad | Solución y presupuesto | 1 |
| 27 | Aprovisionador | Empresas | order.signed | red.config, inventario | Servicio dado de alta | 1 |
| 28 | Soporte de 2.º nivel | Empresas | ticket.level2 | tickets, red | Resolución o escalado | 2 |
| 29 | Redactor de informes | Empresas | cron mensual | red.kpis, contratos | Informe mensual por cliente | 2 |
| 30 | Licitador | Empresas | tender.uploaded | documentos | Borrador de oferta técnica | 1 |
| 31 | Estratega 5G | Planificación | cron trimestral | red.trafico, mercado_sim | Propuesta de emplazamientos | 0 |
| 32 | Analista de inversiones | Planificación | plan.proposed | finanzas_sim | Rentabilidad estimada | 0 |
| 33 | Negociador de emplazamientos | Planificación | lease.expiring | contratos | Borrador de renovación · Persona | 1 |
| 34 | Proyectista | Planificación | design.approved | documentos | Borrador de proyecto · Persona | 1 |
| 35 | Espía | Planificación | cron semanal | mercado_sim | Comparativa con competencia | 0 |
| 36 | Escudo | Seguridad | traffic.anomaly | red.trafico, red.filtros | Mitigación aplicada | 2 |
| 37 | Cazavulnerabilidades | Seguridad | cve.published | inventario | Equipos afectados y prioridad | 0 |
| 38 | Cumplidor | Seguridad | cron mensual | documentos, auditoria | Borrador de informe regulatorio · Persona | 1 |
| 39 | Bibliotecario | Gestión | ticket.closed | documentos | Procedimientos actualizados | 2 |
| 40 | Director de orquesta | Gestión | cron 5 min | todos (lectura) | Prioridades y resumen a dirección · Persona | 0 |

## Datos simulados y gemelo digital

El simulador es lo primero que se construye: sin él, los agentes no tienen nada sobre lo que trabajar. Debe ser determinista con semilla fija para que las pruebas se puedan repetir.

### Qué modela

- Red de una ciudad mediana: unas 300 celdas móviles, 50 nodos de transporte y núcleo, 20.000 clientes de fibra y 200 clientes empresa.
- Series de tráfico y KPIs cada 15 minutos con patrones de día, noche y fin de semana.
- Eventos especiales (ferias, conciertos) que disparan el tráfico en una zona.
- Averías inyectables: caída de enlace, tarjeta degradada, interferencia, ONT que se degrada, ataque de denegación de servicio, desvío de rutas.
- Factores externos: tormentas y cortes de luz por zona.
- Inventario, contratos con SLA, órdenes de trabajo y catálogo de productos.

### Escenarios

Cada escenario es un YAML en `tests/scenarios/` con la semilla, la avería inyectada y el resultado esperado. Ejemplo: «caída del enlace principal de un nodo con respaldo disponible → el Bombero conmuta en menos de 2 minutos y el Forense explica la causa».

### Gemelo digital

Copia del estado de la red donde el Configurador y el Gestor de actualizaciones prueban un cambio antes de proponerlo. Si el cambio rompe algo en el gemelo, no llega a la cola de aprobación.

## Guardarraíles, seguridad y supervisión humana

La regla de fondo: un agente nunca puede hacer algo que no esté en su lista blanca, y todo lo que hace queda registrado.

- **Lista blanca de herramientas**: el núcleo bloquea cualquier llamada MCP no declarada en el YAML del agente.
- **Catálogo cerrado de acciones de nivel 2**: solo acciones reversibles (conmutar a respaldo, reiniciar, apagar y encender portadoras). Cualquier otra pasa a nivel 1.
- **Interruptor general**: un botón en el panel pone a todos los agentes en nivel 0 al instante.
- **Límites de ritmo**: máximo de acciones por agente y hora; si se supera, el agente se pausa y avisa.
- **Radio de impacto**: una acción que afecte a más de un umbral de clientes (configurable, por defecto 500) requiere aprobación aunque el agente sea de nivel 2.
- **Auditoría**: cada paso guarda entrada, razonamiento resumido, herramienta llamada, resultado y quién aprobó.
- **Aprobaciones**: cola en el panel con la acción, la evidencia y el resultado en el gemelo; aprobar o rechazar con un clic y un comentario.
- **Secretos**: credenciales solo en variables de entorno, nunca en prompts ni en logs.
- **Datos**: sin datos personales reales; el simulador genera clientes ficticios.

Los agentes marcados como «Persona» en el catálogo no cierran nunca su tarea: entregan un borrador y la tarea queda asignada a un humano.

## Plan por fases

Se construye por fases y cada una tiene una puerta: si no se cumple su criterio, no se empieza la siguiente. El piloto del NOC va primero porque es donde más horas se ahorran y más fácil es medir.

| Fase | Contenido | Criterio para pasar |
|---|---|---|
| 0 · Base | Simulador, núcleo, panel, auditoría | Un evento simulado llega al panel con auditoría completa |
| 1 · NOC | Agentes 01–08, piloto completo | ≥ 90 % escenarios NOC y 0 acciones fuera de lista |
| 2 · Red | Agentes 09–25: móvil, fibra, núcleo | Ningún cambio sin gemelo y aprobación |
| 3 · Negocio | Agentes 26–35: empresas y planificación | Cada borrador lo cierra una persona |
| 4 · Cierre | Agentes 36–40: seguridad, orquestador | Un día simulado completo, todo auditado |

No hay fechas: dependen de cuánto tiempo se dedique. Lo que sí está fijado es el orden y los criterios.

## Pruebas y métricas de éxito

Un agente no se da por terminado hasta que pasa sus escenarios. Las respuestas del modelo varían, así que cada escenario se ejecuta 5 veces y se exige un porcentaje de acierto, no un acierto único.

- **Unitarias**: núcleo, validación de salidas, lista blanca, límites de ritmo.
- **De escenario**: avería inyectada en el simulador y comprobación del resultado esperado.
- **De regresión**: todos los escenarios en cada cambio de prompt o de modelo.
- **De seguridad**: intentos de usar herramientas no permitidas o de saltarse la aprobación deben fallar siempre.

| Métrica | Objetivo del prototipo |
|---|---|
| Escenarios superados (5 ejecuciones) | ≥ 90 % por agente |
| Alarmas falsas filtradas por el Centinela | ≥ 80 % |
| Tiempo de diagnóstico de una incidencia | < 2 min |
| Acciones fuera de lista blanca ejecutadas | 0 |
| Acciones sin rastro en auditoría | 0 |
| Coste en API por día simulado | Medido y visible en el panel |

## Instrucciones para Claude Code

Exporta este documento a Markdown, guárdalo como `docs/spec.md` en un repositorio vacío y crea un `CLAUDE.md`. Después lanza el primer prompt:

> Lee docs/spec.md y CLAUDE.md. Propón un plan para la Fase 0 (simulador, núcleo y panel), con la lista de ficheros que vas a crear. Espera mi visto bueno antes de escribir código.

A partir de ahí, una fase por sesión: pide el plan, revísalo, deja que lo construya y comprueba el criterio de aceptación antes de pasar a la siguiente.
