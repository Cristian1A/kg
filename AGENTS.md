# AGENTS.md

Reglas generales para cualquier agente (Claude Code, Codex, Copilot, etc.) que trabaje en este repositorio.

## Proyecto

Exploración y modelado de grafos con **NetworkX** (Python 3.12). Visualización con matplotlib y HTML interactivo (`graph.html`, `lib/`).

## Estructura

| Ruta | Contenido |
|------|-----------|
| `src/networkx_project/` | Código fuente del paquete |
| `tests/` | Tests con pytest |
| `.agents/skills/` | Skills especializadas (leer el `SKILL.md` relevante antes de actuar) |
| `.agents/tools/` | Scripts auxiliares para agentes |
| `.mcp.json` | Servidores MCP (tools externas) |
| `env/` | Entorno virtual — **no modificar ni leer** |
| `lib/` | Assets JS generados para `graph.html` — no editar a mano |

## Entorno

```bash
source env/bin/activate
pip install -e ".[dev]"
```

## Reglas

1. **Lee la skill adecuada** en `.agents/skills/<nombre>/SKILL.md` antes de tareas de testing, análisis de datos o cambios de arquitectura.
2. El código nuevo va en `src/networkx_project/`; los scripts sueltos de la raíz son de exploración.
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
