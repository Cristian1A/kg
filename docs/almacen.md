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
| No hay `.kg/graph.json` al cargar | `StoreNotFoundError` (sugiere `kg init`) | — |
| El archivo no cumple el esquema | `StoreCorruptError` con el `Report` de validación | — |
| Dos aristas con la misma identidad | `StoreError` con la ruta JSON | — |

`save_graph` no escribe nada si el grafo no es válido: el almacén anterior se
conserva intacto.
