# Convenciones de contribución

## Commits — Conventional Commits (en español)

```
<tipo>(<ámbito>): <resumen en imperativo, ≤ 72 caracteres, sin punto final>

<cuerpo opcional: QUÉ cambia y POR QUÉ, no el cómo. Líneas ≤ 72.>

Refs: #<issue>   |   Closes: #<issue>
RF: RF-10, RF-11
```

**Tipos**

| Tipo | Uso |
|------|-----|
| `feat` | Nueva funcionalidad |
| `fix` | Corrección de bug |
| `docs` | Solo documentación |
| `test` | Añadir o corregir tests |
| `refactor` | Cambio de código sin cambiar el comportamiento |
| `perf` | Mejora de rendimiento |
| `build` | Dependencias, empaquetado, Docker |
| `ci` | Integración continua |
| `chore` | Mantenimiento (config, .gitignore…) |

**Ámbitos** (módulos del proyecto): `schema`, `extract`, `store`, `merge`, `query`, `render`, `export`, `cli`, `mcp`, `agents`, `docs`.

**Ejemplos**
```
feat(schema): añadir JSON Schema con catálogo estándar de entidades

Define nodes/edges, procedencia y tipos personalizados con aviso.

Closes: #3
RF: RF-01, RF-02
```
```
fix(extract): ignorar archivos .py dentro de env/ y .venv/

Refs: #12
```

- Un commit = un cambio lógico. Los tests van en el mismo commit que el código.
- Un cambio incompatible se marca con `!` (`feat(cli)!: …`) y un pie `BREAKING CHANGE: …`.
- Plantilla local: `git config commit.template .gitmessage`.

## Ramas

`<tipo>/<issue>-<slug>` → `feat/3-json-schema`, `fix/12-ignorar-venv`.
`main` siempre estable; se integra por Pull Request.

## Issues

Se abren con las plantillas de `.github/ISSUE_TEMPLATE/`:

- **Título**: `[<ámbito>] <descripción breve>` → `[schema] Validar referencias rotas entre aristas`
- **Feature**: requisito(s) RF/RNF asociados, descripción, criterios de aceptación en forma de checklist, notas técnicas.
- **Bug**: pasos para reproducir, resultado esperado vs. obtenido, versión/entorno, logs.

**Etiquetas**

| Grupo | Etiquetas |
|-------|-----------|
| Tipo | `type:feature`, `type:bug`, `type:docs`, `type:chore` |
| Prioridad (fase del DF) | `prio:mvp`, `prio:v0.2`, `prio:futuro` |
| Ámbito | `area:schema`, `area:extract`, `area:store`, `area:merge`, `area:query`, `area:render`, `area:export`, `area:cli`, `area:mcp`, `area:agents` |
| Estado | `status:blocked`, `good first issue` |

Hitos (milestones): `v0.1 (MVP)`, `v0.2`.
