# samples/

Directorio de pruebas manuales de `kg` sobre repos de terceros. Los repos
clonados aquí **no se suben** (`samples/*` está en `.gitignore`); solo se
versiona este README.

Sirve para el criterio de aceptación 1 del MVP (sección 8 del DF: flujo
CU-01 sobre al menos 3 repos pequeños de Python) y para medir `extract` y
`render` (RNF-06). Seguimiento en la issue #12.

## Repos de prueba

| Repo | Motivo |
|------|--------|
| [alfredodeza/basic-python-cli](https://github.com/alfredodeza/basic-python-cli) | CLI mínima, muy pocos archivos |

Añade aquí cada repo nuevo que uses para probar.

## Uso

```bash
git clone --depth 1 https://github.com/alfredodeza/basic-python-cli samples/basic-python-cli
kg init --kg-dir samples/basic-python-cli/.kg
kg extract samples/basic-python-cli --kg-dir samples/basic-python-cli/.kg
kg render --html --kg-dir samples/basic-python-cli/.kg -o samples/basic-python-cli.html
```

Los subcomandos se irán habilitando según avancen sus issues (#4, #6, #9…).
