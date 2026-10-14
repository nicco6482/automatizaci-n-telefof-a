# teleco-agents

**40 agentes de IA que hacen el trabajo de los ingenieros de una teleco, sobre una red de telecomunicaciones simulada.**

### ▶ [Ver el anuncio (5 min, con voz)](https://nicco6482.github.io/automatizaci-n-telefof-a/anuncio/) · [Abrir la simulación](https://nicco6482.github.io/automatizaci-n-telefof-a/)

El anuncio enseña los 40 agentes uno a uno, como muñecos en una oficina: cada uno va al puesto donde trabaja, y para
tocar la red todos pasan por el núcleo de control. También está en vídeo: `presentacion/teleco-agents-anuncio.mp4`.

> Si el enlace da 404, hay que activar GitHub Pages una vez: **Settings → Pages → Deploy from a branch → `main` / `(root)` → Save**. A los 1-2 minutos la web queda publicada en esa dirección.
>
> Sin internet o sin Pages: descarga el repositorio y abre `demo_web/index.html` con doble clic. No necesita servidor ni instalación.

---

## Qué es

Un prototipo de punta a punta de cómo una teleco podría repartir el trabajo técnico entre 40 agentes de IA, agrupados en 8 áreas (NOC, red móvil, fibra, núcleo y transporte, clientes empresa, planificación, seguridad y gestión), sin conectar nada a una red real.

La idea de fondo: un agente nunca puede hacer algo que no esté en su lista blanca, todo lo que hace queda auditado, y lo que es criterio, firma o trabajo físico acaba siempre en una persona.

## Qué puedes hacer en la simulación

| Zona del panel | Qué ves o haces |
|---|---|
| **Red simulada** | Mapa de una ciudad con 300 celdas móviles, 50 nodos, enlaces principales y de respaldo, 20.000 clientes FTTH y 200 empresas. El tráfico sigue patrones de día, noche y fin de semana. |
| **Inyectar averías** | Caída de enlace, tarjeta degradada, interferencia, ONT que se degrada, ataque DDoS y desvío de rutas BGP. También tormentas, cortes de luz y eventos especiales (concierto en La Cartuja, Feria). |
| **Eventos de negocio** | Ofertas, pedidos firmados, licitaciones, proyectos de fibra, órdenes de trabajo, firmware nuevo, CVE, alquileres que vencen… cada uno activa a su agente. |
| **Aprobaciones** | Las acciones de nivel 1, las que salen del catálogo cerrado y las que afectan a más clientes que el radio de impacto llegan con su evidencia y el resultado en el gemelo digital. Aprobar o rechazar con un clic y un comentario. |
| **Auditoría** | Cada paso de cada agente: entrada, razonamiento, herramienta, resultado, decisión, quién aprobó y coste. Solo se añaden filas. |
| **Tareas humanas** | Lo que los agentes «Persona» dejan a una persona: firmas, negociaciones, trabajo de campo, avisos de guardia. Ningún agente las cierra. |
| **Escenarios** | 9 pruebas reproducibles (caída con y sin respaldo, tormenta, DDoS, ONT, BGP, concierto, tarjeta, seguridad) que comprueban el resultado esperado en la auditoría. |
| **Interruptor general** | Un botón que pone a los 40 agentes en nivel 0 al instante: solo leen y proponen. |
| **Métricas** | Las seis de la especificación con su objetivo: escenarios superados, alarmas falsas filtradas, tiempo de diagnóstico, acciones fuera de lista blanca, acciones sin auditoría y coste por día simulado. |

Haz clic en cualquier agente para ver su configuración YAML, su última salida validada y su auditoría, o para lanzar su disparador a mano.

### Ejemplo: caída de un enlace

1. El simulador corta el enlace principal de un nodo y salen una alarma crítica, varias de celda y algo de ruido.
2. **01 Centinela** descarta las falsas y agrupa las del mismo fallo.
3. **02 Triaje** abre un ticket con prioridad y diagnóstico en unos 46 segundos.
4. **03 Bombero** aplica el runbook: conmuta al respaldo. Si afecta a más de 500 clientes, el núcleo lo manda a aprobación aunque el agente sea de nivel 2.
5. Al aprobarlo, el ejecutor del núcleo actúa sobre la red y el ticket se cierra.
6. **05 Forense** redacta la causa raíz y **39 Bibliotecario** actualiza el procedimiento.

## Guardarraíles del núcleo de control

- **Lista blanca:** se bloquea y se audita cualquier herramienta que no esté declarada en el YAML del agente.
- **Niveles de autonomía:** 0 observa · 1 actúa con aprobación · 2 actúa solo, y solo con acciones reversibles de un catálogo cerrado.
- **Radio de impacto:** por encima del umbral (500 clientes por defecto, ajustable) se exige aprobación.
- **Límite de ritmo:** máximo de acciones por agente y hora; si se supera, el agente se pausa y avisa.
- **Gemelo digital:** los cambios de configuración se prueban antes; si fallan en el gemelo, no llegan a la cola.
- **Agentes «Persona»:** entregan un borrador y la tarea queda asignada a un humano.

## Los 40 agentes

| Área | Agentes |
|---|---|
| Operaciones de red (NOC) | 01 Centinela · 02 Triaje · 03 Bombero · 04 Escalador · 05 Forense · 06 Guardián de SLA · 07 Gestor de cambios · 08 Meteorólogo |
| Red móvil | 09 Afinador de antenas · 10 Cazainterferencias · 11 Planificador de eventos · 12 Ahorrador · 13 Auditor de vecindad · 14 Analista de mediciones |
| Fibra (FTTH) | 15 Diseñador de barrios · 16 Gestor de permisos · 17 Doctor remoto · 18 Coordinador de contratas · 19 Cartógrafo · 20 Adivino |
| Núcleo y transporte | 21 Previsor de capacidad · 22 Configurador · 23 Auditor de configuraciones · 24 Gestor de actualizaciones · 25 Vigilante de rutas |
| Clientes empresa | 26 Preventa · 27 Aprovisionador · 28 Soporte de 2.º nivel · 29 Redactor de informes · 30 Licitador |
| Planificación | 31 Estratega 5G · 32 Analista de inversiones · 33 Negociador de emplazamientos · 34 Proyectista · 35 Espía |
| Seguridad | 36 Escudo · 37 Cazavulnerabilidades · 38 Cumplidor |
| Gestión | 39 Bibliotecario · 40 Director de orquesta |

## Estructura del repositorio

```
├── index.html            # redirige a la simulación (para GitHub Pages)
├── demo_web/
│   ├── index.html        # panel: estilos y estructura
│   ├── data.js           # ciudad simulada, catálogo de 40 agentes, acciones y escenarios
│   ├── engine.js         # reloj, bus de eventos, núcleo de control, gemelo, auditoría, averías
│   ├── agents.js         # comportamiento de cada uno de los 40 agentes
│   └── ui.js             # mapa, pestañas, métricas y controles
├── CLAUDE.md             # reglas del proyecto para Claude Code
└── *.pdf                 # especificación técnica y presentación
```

## Limitaciones de esta demo

- Los agentes siguen reglas deterministas con semilla fija; **no llaman a Claude**. Así la demo es gratis y siempre da el mismo resultado con la misma semilla.
- Tokens y coste son estimaciones simuladas.
- Todo es ficticio: clientes, empresas, fabricantes («Fabricante A/B/C»), direcciones IP de rangos de documentación (198.51.100.0/24, 203.0.113.0/24) y sistemas autónomos AS64496–64511.

## El programa real

Además de la demo, el repositorio contiene el sistema de verdad, que se construye por fases según la especificación ([docs/spec.md](docs/spec.md)):

| Fase | Contenido | Criterio para pasar | Estado |
|---|---|---|---|
| 0 · Base | Simulador, núcleo de control, panel y auditoría | Un evento simulado llega al panel con auditoría completa | ✅ hecha |
| 1 · NOC | Agentes 01–08 | ≥ 90 % de escenarios NOC y 0 acciones fuera de lista | ✅ hecha |
| 2 · Red | Agentes 09–25 | Ningún cambio sin gemelo y aprobación | ✅ hecha |
| 3 · Negocio | Agentes 26–35 | Cada borrador lo cierra una persona | ✅ hecha |
| 4 · Cierre | Agentes 36–40 | Un día simulado completo, todo auditado | ✅ hecha |

Los 40 agentes están terminados, cada uno con al menos 3 escenarios (126 en total, cada uno repetido 5 veces).
La suite completa son 191 pruebas y pasan todas.

Stack: Python 3.12, Claude Agent SDK, servidores MCP propios, Redis Streams, PostgreSQL, FastAPI, React + Vite y Docker Compose.

| Carpeta | Qué hay |
|---|---|
| `simulator/` | Gemelo digital determinista: red, tráfico cada 15 min, averías, gemelo para probar cambios, servicio HTTP |
| `mcp_servers/` | 22 servidores MCP propios (red, tickets, inventario, gemelo, documentos, contratos, mercado…): las únicas herramientas que ven los agentes |
| `agents/<área>/` | Los 40 agentes: un YAML y un prompt cada uno, en 8 carpetas |
| `ops/` | Datos de operación: alarmas, tickets, avisos, tareas humanas, órdenes de trabajo, documentos y eventos de negocio |
| `core/` | Plantilla de agente (Claude Agent SDK o modo guion), política, auditoría de solo inserción, aprobaciones, bus, orquestador |
| `api/` | API del panel (FastAPI) y arranque local en un proceso |
| `dashboard/` | Panel React: **oficina en directo** (un muñeco por agente que va a su puesto según la auditoría real), aprobaciones, avisos, tareas, documentos, auditoría, agentes e interruptor general. También el anuncio (`anuncio.html`) |
| `presentacion/` | El vídeo del anuncio y los scripts que lo generan (`anuncio/voz.py` para voz y música, `anuncio/render.mjs` para el vídeo) |
| `tests/` | Unitarias, de seguridad, criterio de la Fase 0 y escenarios en YAML (cada uno 5 veces) |

### Arrancarlo

Sin Docker, todo en un proceso (SQLite y Redis en memoria):

```bash
uv sync
cd dashboard && npm install && npm run build && cd ..
uv run python -m api.local
```

Abre http://localhost:8000: la vista **Oficina en directo** muestra a los 40 agentes en sus mesas. Inyecta una «Caída de enlace» y míralos levantarse e ir a su puesto. Con «Nodo con respaldo» el Bombero conmuta (o pide aprobación si afecta a más clientes que el radio de impacto). Con «Nodo sin respaldo» escala y el aviso aparece en «Avisos a guardia»: ciérralo como si fueras la persona de guardia y el Forense redactará la causa raíz.

Con Docker (PostgreSQL y Redis reales): copia `.env.example` a `.env`, pon una `POSTGRES_PASSWORD` y:

```bash
docker compose up --build
```

Por defecto los agentes van en **modo guion** (sin coste). Para que piensen con Claude de verdad, pon en `.env` `TELECO_AGENT_MODE=claude` y tu `ANTHROPIC_API_KEY`. El núcleo aplica la misma lista blanca, aprobaciones y auditoría en los dos modos.

### Pruebas

```bash
uv run pytest -q
uv run pytest tests/scenarios -q
```

### Regenerar el anuncio

```bash
uv run --no-project --with edge-tts --with numpy python presentacion/anuncio/voz.py <carpeta_temporal>
cd dashboard && npm run build:pages && cd ..
uv run python -m api.local
node presentacion/anuncio/render.mjs "http://localhost:8000/anuncio.html?render=1" <carpeta_temporal>/mezcla.wav presentacion/teleco-agents-anuncio.mp4
```

`voz.py` genera la narración (edge-tts, voz es-ES-AlvaroNeural) y una música suave, y deja los tiempos de cada frase en
`dashboard/public/anuncio/tiempos.json`; la animación se sincroniza con ellos. `render.mjs` necesita Playwright y ffmpeg.
