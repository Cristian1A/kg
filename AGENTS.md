# AGENTS.md

Reglas generales para cualquier agente (Claude Code, Codex, Copilot, etc.) que trabaje en este repositorio.

## Proyecto

**kg**: CLI (para humanos y agentes de IA) que convierte el conocimiento de un proyecto —código, dependencias, docs, tests, decisiones— en un grafo de conocimiento consultable, visualizable y exportable. Python 3.12 + NetworkX. Requisitos en `docs/requisitos-funcionales.md`.

## Estructura

| Ruta | Contenido |
|------|-----------|
| `src/kg/` | Código fuente del paquete y la CLI `kg` |
| `tests/` | Tests con pytest |
| `.agents/skills/` | Skills especializadas (leer el `SKILL.md` relevante antes de actuar) |
| `.agents/tools/` | Scripts auxiliares para agentes |
| `.mcp.json` | Servidores MCP (tools externas) |
| `env/` | Entorno virtual — **no modificar ni leer** |
| `lib/`, `graph.html` | Assets JS del prototipo pyvis — no editar a mano |
| `graph.py`, `di_graph.py`, `tuto.py`, `*.ipynb` | Prototipos de exploración (excluidos de ruff) |

## Entorno

```bash
source env/bin/activate
pip install -e ".[dev]"
kg --help          # o: python -m kg --help
pytest && ruff check . && ruff format --check .
```

## Reglas

1. **Lee la skill adecuada** en `.agents/skills/<nombre>/SKILL.md` antes de tareas de testing, análisis de datos o cambios de arquitectura.
2. El código nuevo va en `src/kg/`; los scripts sueltos de la raíz son de exploración.
3. Todo cambio de lógica lleva su test en `tests/`. Ejecuta `pytest` antes de dar algo por terminado.
4. Usa type hints y docstrings breves. Formato y lint con `ruff`.
5. No añadas dependencias sin justificarlo; decláralas en `pyproject.toml`.
6. No hagas commits, pushes ni borrados de archivos sin confirmación del usuario.
7. No llames a `plt.show()` en código de librería ni en tests (bloquea la ejecución); devuelve la figura o guárdala.
8. Responde y documenta en español salvo que se pida lo contrario.
9. Commits, ramas e issues siguen `CONTRIBUTING.md` (Conventional Commits en español, referencia a issue y a RF-xx).
10. Los secretos viven en `.env` (en `.gitignore`). **Nunca** imprimas, copies ni hagas commit de su contenido; cárgalo con `set -a; source .env; set +a` y usa la variable.

## Documentación de referencia

- `docs/requisitos-funcionales.md` — requisitos funcionales aprobados (RF-xx / RNF-xx).
