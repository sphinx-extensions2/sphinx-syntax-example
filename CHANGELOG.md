# Changelog

## Unreleased

### 🐛 Fixes

- The stylesheet no longer relies on load order to win ties against theme
  rules: the render pane's padding now out-specifies theme `.container`
  resets (fixing the missing horizontal padding under Furo, which links its
  `furo-extensions.css` *after* extension stylesheets), and Bootstrap-style
  `.container` layout is neutralized on the outer frame.

## v0.1.0 (2026-07-27)

Initial release.

### ✨ Features

- The `syntax-example` directive, which shows a block of markup as both its
  syntax-highlighted source and its rendered result, stacked inside one framed box.
- An optional title argument (rendered as a rubric, defaulting to `Example`),
  and a `:highlight:` option to override the source pane's highlight language.
- Language inference from the document's format, via the project's configured
  source-suffix mapping, with a graceful fallback for unmapped paths and unknown
  `:highlight:` values (a strict `-W` build is never broken).
- A theme-agnostic stylesheet, registered automatically on HTML builds.
- Documented subclassing seams (`format_title`, `build_title_node`,
  `source_text`, `render_into`, `default_language`) for aliased directives.
