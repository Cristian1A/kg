# Documento de Requisitos Funcionales — `kg` (nombre provisional)

| Campo | Valor |
|-------|-------|
| Versión del documento | 1.0 |
| Fecha | 2026-10-06 |
| Estado | Aprobado por el cliente (2026-10-07) |
| Fuente | Entrevista de requisitos (`respuestas_usuario.txt`, bloques 1–4) |

---

## 1. Introducción

### 1.1 Propósito
`kg` es una herramienta de línea de comandos que convierte el conocimiento sobre un proyecto de software (código, dependencias, documentación, tests, decisiones…) en un **grafo de conocimiento** que se puede consultar, visualizar y exportar.

La pueden usar tanto **personas** como **agentes de IA**. El objetivo es que developers y stakeholders entiendan de qué va un proyecto y cómo está construido, y que un agente pueda razonar sobre él con datos fiables.

### 1.2 Alcance
- El dominio principal es **repositorios de software**. El modelo es extensible a cualquier dominio.
- La entrada se obtiene por dos vías:
  1. **Extracción determinista**: parseo del código y de los ficheros de configuración. Python primero.
  2. **Extracción asistida por un agente externo**: el agente lee el repo o un texto y genera un JSON conforme al esquema.
- La salida es un grafo almacenado en el propio repo, con visualización (PNG/SVG, HTML interactivo) y exportación a otros formatos.

### 1.3 Contexto
Es un proyecto exploratorio con vocación de *side project* publicable (licencia MIT). Las primeras pruebas se harán sobre repos pequeños de Python.

### 1.4 Glosario
| Término | Definición |
|---------|------------|
| **Entidad / nodo** | Elemento del proyecto: archivo, función, dependencia, documento… |
| **Relación / arista** | Vínculo dirigido y tipado entre dos entidades (`imports`, `tests`…) |
| **Catálogo estándar** | Conjunto mínimo de tipos de entidad y relación que la herramienta define y que los agentes deben considerar |
| **Tipo personalizado** | Tipo de entidad o relación que no está en el catálogo y que define el usuario o el agente |
| **Procedencia** | Metadatos sobre el origen de un dato: fuente, archivo/línea, método (parser/LLM) y confianza |
| **Almacén** | Carpeta `.kg/` dentro del repo analizado que contiene el grafo |
| **Agente externo** | Asistente de IA (Claude Code u otro) que usa `kg` como herramienta |

---

## 2. Usuarios y casos de uso

### 2.1 Perfiles
| Perfil | Necesidad | Cómo interactúa |
|--------|-----------|-----------------|
| **Developer** | Entender la estructura, el impacto de un cambio y la cobertura | CLI, HTML interactivo, preguntas a un agente |
| **Stakeholder no técnico** | Ver de un vistazo de qué va el proyecto | Imagen o HTML generados |
| **Agente de IA** | Construir el grafo y consultarlo para responder preguntas | CLI con `--json`, servidor MCP |

### 2.2 Casos de uso principales
| ID | Caso de uso | Actor | Flujo resumido |
|----|-------------|-------|----------------|
| CU-01 | **Mapear un repo** | Developer / agente | `kg init` → `kg extract .` → el agente añade docs y decisiones con `kg add` → `kg render --html` |
| CU-02 | **¿Qué tests hacen falta?** | Agente | Consulta las entidades de código que no tienen ninguna relación `tests` entrante y propone tests |
| CU-03 | **¿Está la documentación alineada con el código?** | Agente | Compara lo que dicen los nodos `Document` (relaciones `documents`, procedencia LLM) con lo que extrajo el parser. Señala referencias a elementos inexistentes y código público sin documentar |
| CU-04 | **¿Cómo expando el proyecto con estos N requisitos?** | Agente | Lee los módulos, responsabilidades, dependencias y decisiones del grafo, y razona dónde y cómo encajar los requisitos |
| CU-05 | **Impacto de un cambio** | Developer / agente | `kg impact <nodo>` lista lo que depende de forma transitiva del nodo |
| CU-06 | **Compartir el mapa** | Developer | `kg render` o `kg export --format mermaid` para incluirlo en un README o en una presentación |

> Las preguntas abiertas (CU-02, CU-03 y CU-04) las responde un **agente externo** razonando sobre el grafo. `kg` no integra ningún LLM. Lo que garantiza es que el grafo contiene los datos necesarios y que las consultas estructuradas funcionan.

---

## 3. Modelo de datos

### 3.1 Principios
- **Esquema híbrido.** Hay un catálogo estándar obligatorio que sirve de guía, y se permiten tipos personalizados de entidad y relación.
- **Sin redundancia.** Cada entidad real aparece en un único nodo. Para ello cada entidad tiene un **ID estable** derivado de su naturaleza; por ejemplo `file:src/app/main.py` o `function:app.main.run`.
- **Trazabilidad.** Todo nodo y toda relación registran su procedencia.
- **Dirigido y con atributos.** El grafo es un multigrafo dirigido (`nx.MultiDiGraph`) con atributos libres en nodos y aristas.

### 3.2 Catálogo estándar de entidades
| Tipo | Descripción | Origen típico |
|------|-------------|---------------|
| `Repo` | Raíz del proyecto | Parser |
| `Package` / `Module` | Paquete o módulo de código | Parser |
| `File` | Archivo del repo | Parser |
| `Class` | Clase | Parser |
| `Function` | Función o método | Parser |
| `Dependency` | Dependencia externa (pyproject, requirements) | Parser |
| `Test` | Archivo o función de test | Parser |
| `Document` | Documento (README, docs/, docstrings relevantes) | Parser + LLM |
| `Config` | Configuración (pyproject, .env.example, CI) | Parser |
| `Service` / `Endpoint` | Servicio o endpoint expuesto | Parser + LLM |
| `Person` | Contributor o autor | git / LLM |
| `Issue` | Incidencia o tarea | LLM / futuro |
| `Decision` | Decisión de diseño (ADR o lo explicado en la doc) | LLM |
| `Concept` | Concepto de dominio | LLM |

### 3.3 Catálogo estándar de relaciones
`contains`, `imports`, `depends_on`, `defines`, `calls`, `documents`, `tests`, `configures`, `authored_by`, `implements`, `justifies` (Decision → entidad).

### 3.4 Procedencia (por nodo y por relación)
| Campo | Ejemplo |
|-------|---------|
| `source` | `src/app/main.py` |
| `lines` | `[12, 40]` |
| `method` | `parser` \| `llm` \| `manual` |
| `extractor` | `python-ast@0.1`, `claude-code` |
| `confidence` | `1.0` (parser), `0.0–1.0` (LLM) |
| `timestamp` | ISO-8601 |

---

## 4. Requisitos funcionales

Prioridades:
- **MVP**: v0.1.
- **v0.2**: siguiente iteración.
- **Futuro**: mejora sin fecha.

### 4.1 Esquema y validación
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-01 | Existe un **JSON Schema** oficial y publicado del formato de entrada (`nodes`, `edges`, atributos y procedencia) que un agente pueda leer | MVP |
| RF-02 | El esquema incluye el **catálogo estándar** y admite **tipos personalizados**; un tipo no estándar genera un *aviso*, no un error | MVP |
| RF-03 | `kg validate <json>` valida sin modificar el almacén | MVP |
| RF-04 | Los errores de validación son **claros y accionables**: ruta JSON del fallo, valor recibido, valor esperado y sugerencia. Se pueden obtener en texto y en JSON (`--json`) para que un agente se autocorrija | MVP |
| RF-05 | La validación detecta referencias rotas (una arista que apunta a un nodo inexistente) e IDs duplicados en el mismo archivo | MVP |

### 4.2 Extracción
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-10 | `kg extract <ruta>` analiza un repo Python de forma determinista y genera nodos `Repo`, `Package/Module`, `File`, `Class`, `Function` y `Test`, con las relaciones `contains`, `defines` e `imports` | MVP |
| RF-11 | Extrae `Dependency` y `Config` de `pyproject.toml` y `requirements*.txt` | MVP |
| RF-12 | Detecta tests (convención pytest) y crea relaciones `tests` hacia el código que importan o invocan | MVP |
| RF-13 | Extrae relaciones `calls` entre funciones (análisis estático, sin garantía completa) | v0.2 |
| RF-14 | Extrae `Person` y `authored_by` desde el historial de git | Futuro |
| RF-15 | Extractores para JS/TS y otros ecosistemas | Futuro |

### 4.3 Integración con agentes
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-20 | Se proporcionan **guidelines/skill** para agentes: cómo recorrer un repo o un texto, qué entidades y relaciones buscar como mínimo (catálogo estándar), cómo asignar IDs estables, cómo rellenar la procedencia y la confianza, y cómo validar e iterar con `kg validate` | MVP |
| RF-21 | `kg add <json>` incorpora al almacén las entidades y relaciones de un JSON válido | MVP |
| RF-22 | Todos los comandos admiten `--json` para producir una salida legible por máquinas | MVP |
| RF-23 | **Servidor MCP** que expone las operaciones principales (validate, add, query, impact, render, export) como tools | v0.2 |
| RF-24 | `kg` **no** llama a ningún LLM ni requiere API keys | MVP (restricción) |

### 4.4 Fusión y deduplicación
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-30 | **Fusión básica por ID**: al añadir una entidad con un ID existente se combinan sus atributos en vez de duplicarla | MVP (necesario para RF-21) |
| RF-31 | **Procedencia múltiple**: una entidad o relación confirmada por varias fuentes conserva todas sus procedencias | v0.2 |
| RF-32 | **Deduplicación avanzada**: detecta entidades equivalentes con distinto ID (por ejemplo `pandas` en la doc y `Dependency:pandas` en el código) mediante normalización o alias, y las fusiona o propone fusionarlas | v0.2 |
| RF-33 | Política de conflictos configurable cuando dos fuentes discrepan en un atributo (por defecto prevalece el parser sobre el LLM) | v0.2 |

### 4.5 Consultas y análisis
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-40 | `kg query` permite: obtener un nodo y sus atributos, vecinos entrantes y salientes, filtrar por tipo o atributo, y buscar caminos entre dos nodos | v0.2 |
| RF-41 | `kg impact <nodo>` lista las dependencias transitivas (todo lo que depende de forma directa o indirecta del nodo), con su profundidad | v0.2 |
| RF-42 | Consultas predefinidas que apoyan los casos de uso: código sin tests (CU-02) y código sin documentar o documentos que referencian entidades inexistentes (CU-03) | v0.2 |

### 4.6 Visualización
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-50 | `kg render --png` / `--svg` genera una imagen estática del grafo | MVP |
| RF-51 | `kg render --html` genera un HTML interactivo y autocontenido (funciona offline) | MVP |
| RF-52 | El HTML incluye colores por tipo de entidad, estilo o etiqueta por tipo de relación y una **leyenda** | MVP |
| RF-53 | El HTML incluye **filtros** por tipo de entidad y de relación | MVP |
| RF-54 | El HTML muestra los **detalles del nodo al hacer clic**: atributos y procedencia | MVP |
| RF-55 | El HTML incluye un **buscador sencillo** por nombre o ID | MVP |
| RF-56 | Vistas por público (alto nivel para stakeholders y detalle para developers) y agrupar/colapsar módulos | Futuro |

### 4.7 Exportación
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-60 | `kg export --format mermaid` | v0.2 |
| RF-61 | `kg export --format dot` (Graphviz) | v0.2 |
| RF-62 | Exportación a Neo4j/Cypher | Futuro |

### 4.8 Almacenamiento, versionado y actualización
| ID | Requisito | Prioridad |
|----|-----------|-----------|
| RF-70 | `kg init` crea el almacén `.kg/` dentro del repo analizado | MVP |
| RF-71 | El almacén usa **JSON legible y con orden determinista**, para que los diffs de git sean limpios y revisables en PRs. El versionado se delega en el git del repo | MVP |
| RF-72 | **Actualización incremental**: `kg extract` solo reprocesa los archivos modificados según git y elimina las entidades de los archivos borrados | v0.2 |
| RF-73 | **Hook post-commit** opcional que lanza la actualización incremental | v0.2 |
| RF-74 | `kg log`, `kg diff <v1> <v2>` (nodos y relaciones añadidos, eliminados o modificados) y `kg checkout <versión>`, apoyados en el historial de git del almacén | v0.2 |

---

## 5. Interfaz de línea de comandos

```
kg init                         Crea el almacén .kg/ en el repo
kg extract <ruta>               Extracción determinista (Python)
kg add <archivo.json>           Añade y fusiona entidades y relaciones
kg validate <archivo.json>      Valida contra el esquema sin aplicar cambios
kg query ...                    Nodos, vecinos, caminos y filtros         (v0.2)
kg impact <nodo>                Dependencias transitivas                  (v0.2)
kg render --png|--svg|--html    Visualización
kg export --format mermaid|dot  Exportación                               (v0.2)
kg log | diff | checkout        Historial y comparación de versiones      (v0.2)

Opciones globales: --json (salida legible por máquinas), --kg-dir <ruta>
```

Códigos de salida: `0` OK, `1` error de validación, `2` error de uso, `>2` error interno.

---

## 6. Requisitos no funcionales

| ID | Requisito |
|----|-----------|
| RNF-01 | **Lenguaje**: Python ≥ 3.12, basado en NetworkX |
| RNF-02 | **Plataforma**: Linux. macOS y Windows no están soportados oficialmente |
| RNF-03 | **Distribución**: instalación local (`pip install -e .`). Debe poder dockerizarse (Dockerfile en v0.2). PyPI queda para el futuro |
| RNF-04 | **Privacidad**: funciona 100 % offline; la herramienta no envía código ni datos a ningún servicio |
| RNF-05 | **Licencia**: MIT |
| RNF-06 | **Rendimiento**: sin objetivo cerrado en el MVP. Se medirá el tiempo de `extract` y `render` en los repos de prueba y se fijará un objetivo para la v0.2 (referencia orientativa: repo de menos de 100 archivos en menos de 10 s) |
| RNF-07 | **Calidad**: tests con pytest, incluidos tests específicos de los mensajes de validación (RF-04). Lint con ruff |
| RNF-08 | **Determinismo**: la misma entrada produce el mismo almacén, byte a byte, y el mismo layout de visualización (semilla fija) |
| RNF-09 | **Escalabilidad**: diseñado para repos pequeños en el MVP. No se deben tomar decisiones que impidan escalar a repos medianos o grandes |

---

## 7. Plan de entregas

| Versión | Contenido |
|---------|-----------|
| **v0.1 (MVP)** | Esquema y validación (RF-01–05), extractor Python (RF-10–12), guidelines para agentes y `add` (RF-20–22, 24), fusión básica por ID (RF-30), render PNG/SVG/HTML (RF-50–55), almacén `.kg/` (RF-70–71) |
| **v0.2** | Procedencia múltiple y deduplicación avanzada (RF-31–33), consultas e impacto (RF-40–42), export Mermaid/DOT (RF-60–61), incremental, hook y versionado (RF-72–74), servidor MCP (RF-23), `calls` (RF-13), Dockerfile |
| **Futuro** | Vistas por público, Neo4j, git blame/authors, otros lenguajes, PyPI |

---

## 8. Criterios de aceptación del MVP

El MVP se considera un **éxito** si:

1. Se ejecuta el flujo CU-01 completo (`init → extract → add → render`) sin errores sobre **al menos 3 repos pequeños de Python** distintos, por ejemplo este mismo y dos repos públicos de menos de 100 archivos.
2. En cada repo, un agente externo que solo dispone del grafo responde de forma correcta y verificable a las tres preguntas de referencia:
   - "¿Qué tests hacen falta?"
   - "¿Está la documentación alineada con el código?"
   - "¿Cómo se puede expandir este proyecto si le doy estos 2 nuevos requisitos?"
3. Un JSON inválido generado a propósito produce errores que permiten a un agente corregirlo en **una iteración**.
4. El HTML permite localizar un nodo con el buscador, filtrarlo por tipo y ver su procedencia.
5. Ejecutar `kg extract` dos veces seguidas no crea nodos duplicados (RF-30).

---

## 9. Fuera de alcance

Confirmado por el cliente el 2026-10-07:
- Un LLM integrado en la herramienta (comando `ask`, llamadas a APIs o gestión de API keys).
- Servidor web o hosting del grafo; colaboración multiusuario en tiempo real.
- Soporte oficial de macOS y Windows.
- Modo *watch* en tiempo real (la actualización se dispara a mano o por hook).
- Análisis semántico profundo del código: tipos, flujo de datos y análisis dinámico en ejecución.
- Base de datos de grafos como almacenamiento primario. Neo4j solo como formato de exportación futuro.

---

## 10. Supuestos y decisiones

### Supuestos (aceptados)
- S-01: El repo analizado usa git. Sin git, `kg` funciona, pero sin incremental ni versionado.
- S-02: La extracción con LLM la hace siempre un agente externo, que es responsable de su propio coste y privacidad.
- S-03: La fusión básica del MVP (RF-30) se incluye aunque la fusión completa (C) se marcó para después, porque sin ella `add` y `extract` generarían duplicados.

### Decisiones (preguntas abiertas resueltas)
| ID | Decisión |
|----|----------|
| PA-01 | El nombre del proyecto y de la CLI es **`kg`** por ahora; se revisará antes de publicar en PyPI |
| PA-02 | Las entidades sin origen físico usan IDs `<tipo>:<slug>` (p. ej. `concept:grafo-de-conocimiento`, `decision:usar-networkx`) |
| PA-03 | El HTML interactivo se genera con **pyvis (vis.js)**, empaquetado para funcionar offline |
| PA-04 | Lista de fuera de alcance confirmada (sección 9) |
