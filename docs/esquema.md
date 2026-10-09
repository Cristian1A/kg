# Esquema de entrada de `kg`

Formato JSON con el que la extracción determinista y los agentes externos
describen entidades y relaciones (RF-01, RF-02). El esquema oficial es JSON
Schema draft 2020-12 y se distribuye con el paquete:

```bash
kg schema            # imprime el esquema
kg schema --path     # ruta del archivo instalado
kg schema --json     # {"ok": true, "result": {"path": ..., "schema": {...}}}
```

Fuente: `src/kg/schema/kg.schema.json`. Ejemplos válidos en `examples/`.

## Estructura

```json
{
  "version": "1",
  "nodes": [{ "id": "...", "type": "...", "provenance": { ... } }],
  "edges": [{ "source": "<id>", "target": "<id>", "type": "...", "provenance": { ... } }]
}
```

| Campo | Nodo | Arista | Notas |
|-------|:----:|:------:|-------|
| `id` | obligatorio | — | ID estable (ver abajo) |
| `source`, `target` | — | obligatorios | IDs de los nodos que une |
| `type` | obligatorio | obligatorio | Catálogo estándar o personalizado |
| `label`, `description` | opcionales | — | Texto legible |
| `attrs` | opcional | opcional | Objeto de atributos libres |
| `provenance` | obligatorio | obligatorio | Ver *Procedencia* |

No se admiten otros campos: los atributos propios van dentro de `attrs`.

## IDs estables (PA-02)

`<tipo>:<ruta | nombre cualificado | slug>`, con el prefijo en minúsculas:

| Entidad | ID |
|---------|----|
| Archivo | `file:src/app/main.py` (ruta relativa a la raíz, con `/`) |
| Módulo, clase, función | `module:app.main`, `class:app.main.App`, `function:app.main.run` |
| Dependencia | `dependency:networkx` |
| Sin origen físico | `concept:grafo-de-conocimiento`, `decision:usar-networkx` |

El mismo elemento debe producir siempre el mismo ID: así `kg add` fusiona en
vez de duplicar (RF-30).

## Catálogo estándar

**Entidades (DF 3.2):** `Repo`, `Package`, `Module`, `File`, `Class`,
`Function`, `Dependency`, `Test`, `Document`, `Config`, `Service`, `Endpoint`,
`Person`, `Issue`, `Decision`, `Concept`.

**Relaciones (DF 3.3):** `contains`, `imports`, `depends_on`, `defines`,
`calls`, `documents`, `tests`, `configures`, `authored_by`, `implements`,
`justifies` (Decision → entidad).

## Tipos personalizados

Un tipo fuera del catálogo es **válido**, pero `kg` emite un aviso para que se
revise si existe un tipo estándar equivalente. Formato: entidades en
PascalCase (`Requirement`) y relaciones en snake_case (`satisfies`).

## Procedencia (DF 3.4)

| Campo | Obligatorio | Ejemplo |
|-------|:-----------:|---------|
| `method` | sí | `parser` \| `llm` \| `manual` |
| `extractor` | sí | `python-ast@0.1`, `claude-code` |
| `confidence` | sí | `1.0` (parser), `0.0`–`1.0` (LLM) |
| `source` | no | `src/app/main.py` |
| `lines` | no | `[12, 40]` (1-indexado, inclusivo) |
| `timestamp` | no | `2026-10-09T12:00:00Z` (ISO-8601 con zona) |

`timestamp` es opcional para que la extracción determinista produzca la misma
salida byte a byte (RNF-08).
