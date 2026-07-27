# Changelog

## Unreleased

### ✨ Features

- New `syntax_example_numbering` config value (default `False`, `env` rebuild):
  when enabled, the default title becomes a per-document numbered label and any
  argument is carried as a subtitle — `Example 1`, `Example 5: the filter
  option` — reproducing the shape of sphinx-needs' bespoke `need-example`
  directive so its documentation can move to the canonical directive. The
  counter restarts per document and is keyed by the registered directive name
  (lowercased), so aliases number independently; an empty `default_title` is
  left alone. A matching option is being added to ubCode's Rust engine under
  the same config name, to produce the same output.
- New `build_wrapper_node` and `build_render_node` seams, deciding the node
  *type* and any extra attributes on the two containers. A subclass can now
  emit sphinx-design divs (`is_div`, `design_component`) — whose visitor omits
  the `container` class, keeping Bootstrap- and pydata-theme `.container`
  layout rules off the frame — without re-implementing `run`. The class
  attributes remain the single source of the CSS classes: `run` applies them to
  whatever the seams return, so an override neither repeats them nor can drop
  them.
- New `per_document_number()` helper: the per-document counter behind
  `syntax_example_numbering`, callable from a `format_title` override that
  numbers on its own terms.
- New `nested_parse_text(text, container)` helper, parsing a *string* of markup
  into a node with the host document's own parser (reStructuredText in an
  `.rst` file, MyST in a Markdown one) and the directive's source attribution.
  This is what a "shown source differs from rendered output" override needs,
  where the content-list-based `render_into` default cannot help.

### 🐛 Fixes

- `:highlight:` now accepts a lexer registered with `app.add_lexer`, and
  `myst` is detected as one. Only Pygments' global registry was consulted
  before, so a project-local lexer (as myst-parser's own documentation
  registers) was invisible and silently fell back to the inferred language.
  Sphinx's own built-in aliases are consulted too, so `:highlight: none` — a
  valid Sphinx highlight language that Pygments does not resolve — is now
  honoured instead of falling back.

## v0.1.1 (2026-07-27)

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
