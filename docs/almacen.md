# Almacén `.kg/`

Donde `kg` guarda el grafo del proyecto (RF-70, RF-71). Vive dentro del repo
analizado y se versiona con su git: el formato está pensado para que los diffs
de un PR sean legibles.

```bash
kg init                    # crea .kg/ en el directorio actual
kg init --kg-dir ruta/.kg  # en otra ruta (el directorio padre debe existir)
kg init --json             # {"ok": true, "result": {"kg_dir", "graph", "version"}}
```

`kg init` falla con código `2` si la ruta ya existe (no la modifica) o si no
existe su directorio padre.

## Añadir entidades y relaciones: `kg add`

```bash
kg add grafo.json          # valida y fusiona en .kg/graph.json
cat grafo.json | kg add -  # desde stdin
kg add grafo.json --json   # resumen para agentes
```

1. Carga el almacén (si no existe: código `2`, sugiere `kg init`).
2. Valida el documento como `kg validate`, con una diferencia: las aristas
   pueden apuntar a nodos que **ya están en el almacén**, no solo a los del
   archivo. Así un agente puede añadir `documents` hacia funciones que creó
   `kg extract`.
3. Si hay errores, no modifica nada (código `1`).
4. Fusiona por ID (RF-30) y guarda. Si nada cambia, no reescribe el archivo:
   repetir el mismo `add` deja el almacén idéntico.

### Reglas de fusión (MVP)

| Caso | Resultado |
|------|-----------|
| Nodo con ID nuevo | Se añade |
| Nodo con ID existente | Se combinan los campos; los que el documento no trae se conservan |
| `attrs` | Se combinan por clave de primer nivel; los valores anidados se sustituyen enteros |
| Arista con (`source`, `target`, `type`) nuevo | Se añade |
| Arista existente | Se combinan `attrs` y `provenance` igual que en nodos; no se duplica |
| Mismo campo con valor distinto | **Gana el valor nuevo** y se informa como conflicto |

`provenance` se trata como un único valor: la última fuente sustituye a la
anterior. Conservar varias procedencias es RF-31 y la política de conflictos
configurable (p. ej. parser antes que LLM) es RF-33, ambos de la v0.2.

### Resumen

```text
grafo.json fusionado en .kg/graph.json
  nodos:   2 añadidos, 1 fusionado, 9 sin cambios
  aristas: 4 añadidas, 0 fusionadas, 9 sin cambios
  1 conflicto (se conserva el valor nuevo):
    function:size.main · label: "main" → "main()"
```

Con `--json`, `result` trae `changed`, `nodes` y `edges` (listas `added`,
`merged` y `unchanged`; las aristas como `source -[type]-> target`),
`conflicts` (`kind`, `element`, `field`, `old`, `new`) y los `warnings` de la
validación. Si el documento no es válido, el error lleva los mismos `details`
que `kg validate`.

## Estructura

```
.kg/
└── graph.json   # nodos y aristas del grafo
```

Un único archivo: la escritura es atómica (archivo temporal + `rename`) y el
grafo nunca queda a medias entre dos archivos. Con un objeto por nodo/arista
y el orden fijo, un cambio en una entidad solo toca sus líneas.

## Formato

`graph.json` es un **documento válido del esquema de entrada** (ver
[esquema.md](esquema.md)), por lo que se puede revisar con
`kg validate .kg/graph.json`. La versión del formato es el campo `version`
(hoy `"1"`, la misma que el esquema).

```json
{
  "version": "1",
  "nodes": [
    {
      "id": "dependency:networkx",
      "type": "Dependency",
      "attrs": {
        "spec": ">=3.7"
      },
      "provenance": {
        "confidence": 1.0,
        "extractor": "pyproject@0.1",
        "method": "parser",
        "source": "pyproject.toml"
      }
    }
  ],
  "edges": []
}
```

## Determinismo (RNF-08)

El mismo grafo produce el mismo archivo byte a byte, sea cual sea el orden en
que se añadieron sus elementos:

| Qué | Orden |
|-----|-------|
| Raíz | `version`, `nodes`, `edges` |
| Nodos | por `id` |
| Aristas | por (`source`, `target`, `type`) |
| Campos de un nodo | `id`, `type`, `label`, `description`, `attrs`, `provenance` (los ausentes se omiten) |
| Campos de una arista | `source`, `target`, `type`, `attrs`, `provenance` |
| Claves dentro de `attrs` y `provenance` | alfabético, también en objetos anidados |
| Listas (`lines`, valores de `attrs`) | se conservan tal cual |

Texto UTF-8 sin escapar (`ensure_ascii=False`), sangría de 2 espacios, saltos
de línea `\n` y salto final. Campos que no son del esquema, como `$schema`,
no se guardan.

## Modelo en memoria

`kg.store.load_graph()` devuelve un `nx.MultiDiGraph`:

- Nodo: clave = `id`; atributos `type`, `label`, `description`, `attrs`,
  `provenance` (solo los presentes).
- Arista: clave = `type`, así que su identidad es (`source`, `target`, `type`)
  y no puede haber dos iguales. Atributos `type`, `attrs`, `provenance`.

```python
from pathlib import Path
from kg import store

graph = store.load_graph(Path(".kg"))  # valida contra el esquema
graph.edges["file:a.py", "function:a.f", "defines"]
store.save_graph(graph, Path(".kg"))  # valida antes de escribir
```

## Errores

| Situación | Excepción | En la CLI |
|-----------|-----------|-----------|
| `kg init` sobre una ruta existente | `StoreExistsError` | código `2` |
| `kg init` sin el directorio padre | `StoreNotFoundError` | código `2` |
| No hay `.kg/graph.json` al cargar | `StoreNotFoundError` (sugiere `kg init`) | código `2` |
| El archivo no cumple el esquema | `StoreCorruptError` con el `Report` de validación | código `1` |
| Dos aristas con la misma identidad | `StoreError` con la ruta JSON | código `2` |

`save_graph` no escribe nada si el grafo no es válido: el almacén anterior se
conserva intacto.
