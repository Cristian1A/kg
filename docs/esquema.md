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

## Validación

```bash
kg validate grafo.json          # texto legible
kg validate grafo.json --json   # para agentes
cat grafo.json | kg validate -  # desde stdin
```

No modifica el almacén (RF-03). Cada problema indica **ruta JSON**, **valor
recibido**, **valor esperado** y **sugerencia** (RF-04):

```text
error: $.edges[0].target: la arista apunta a un nodo que no existe en el archivo
  recibido:   "function:a.g"
  esperado:   el ID de un nodo declarado en `nodes`
  sugerencia: ¿Querías decir "function:a.f"? Corrige el ID o añade el nodo a `nodes`.
```

Con `--json`, los errores van en `error.details.errors` y los avisos en
`warnings` (en `result` si el documento es válido). Cada elemento tiene `code`,
`path`, `message`, `received` (`null` si falta el campo), `expected`,
`suggestion` y `severity`.

| Código | Severidad | Causa |
|--------|-----------|-------|
| `invalid_json`, `invalid_encoding` | error | El archivo no es JSON UTF-8 |
| `required`, `unknown_field` | error | Falta un campo o sobra uno (con sugerencia si es una errata) |
| `wrong_type`, `not_allowed`, `out_of_range`, `wrong_length`, `empty` | error | Valor incorrecto |
| `invalid_id`, `invalid_timestamp`, `invalid_type_name` | error | Formato incorrecto |
| `duplicate_id` | error | Dos nodos con el mismo ID (RF-05) |
| `broken_reference` | error | Arista hacia un nodo que no está en el archivo (RF-05); en `kg add`, tampoco en el almacén |
| `custom_type` | aviso | Tipo fuera del catálogo estándar (RF-02) |
| `id_prefix_mismatch` | aviso | El prefijo del ID no coincide con el `type` del nodo |

Códigos de salida: `0` válido (aunque haya avisos), `1` hay errores, `2` el
archivo no existe o no se puede leer.
