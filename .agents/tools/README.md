# Tools para agentes

Scripts auxiliares que los agentes pueden ejecutar. Cada tool debe ser:

- **Autocontenida**: un archivo, ejecutable con `python .agents/tools/<tool>.py`.
- **No interactiva**: argumentos por CLI, salida por stdout (preferible JSON).
- **Segura**: sin efectos destructivos; si escribe archivos, que sea en una ruta indicada por argumento.

## Tools disponibles

| Tool | Descripción | Uso |
|------|-------------|-----|
| `graph_summary.py` | Resumen de un grafo de ejemplo o de un archivo GraphML | `python .agents/tools/graph_summary.py [archivo.graphml]` |

## Añadir una tool
1. Crear `<nombre>.py` con `argparse` y un `main()`.
2. Documentarla en la tabla de arriba.
3. Las tools externas (APIs, bases de datos, navegador) van en `.mcp.json`, no aquí.
