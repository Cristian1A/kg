# Render assets

- `template.html`: the interactive page of `kg render --html`. `{{TOKENS}}`
  are filled in by `kg.render.html.build_html`.
- `vis-network.min.js`: [vis-network](https://github.com/visjs/vis-network)
  9.1.2, standalone build, identical to the copy that pyvis 0.3.2 ships
  except for the removed `sourceMappingURL` line. Dual licensed Apache-2.0 / MIT; the license header
  is kept at the top of the file.

To upgrade vis-network, replace the file, check the page by hand and update
the version here and in `docs/render.md`.
