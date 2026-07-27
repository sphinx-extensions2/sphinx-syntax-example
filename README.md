# sphinx-syntax-example

[![PyPI][pypi-badge]][pypi-link]
[![Docs][rtd-badge]][rtd-link]
[![CI][ci-badge]][ci-link]

> A Sphinx extension adding the `syntax-example` directive,
> which shows a block of markup as **both** its raw source and its rendered result.

The directive renders its content twice, stacked inside one framed box:
a syntax-highlighted **source pane** showing what to type,
and a **render pane** showing what it produces.
It is useful for documentation that teaches a markup syntax,
where readers need to see the input alongside the output.

## Installation

Requires Python 3.11+ and Sphinx 7.2+.

```bash
pip install sphinx-syntax-example
```

Then add it to the `extensions` list in your `conf.py`:

```python
extensions = [
    # ...
    "sphinx_syntax_example",
]
```

The extension ships a small, theme-agnostic stylesheet
that is registered automatically on HTML builds
(it defines its own colours with fallbacks that pick up the active theme's
variables when present, and looks right on [Furo](https://github.com/pradyunsg/furo)
in both light and dark modes).

## Usage

Write a `syntax-example` directive with the markup you want to demonstrate
as its content. An optional argument sets the title shown above the block
(defaulting to `Example`):

```rst
.. syntax-example:: An optional title

   Any **reStructuredText** or MyST markup here.
```

The block above produces a framed box titled *An optional title*, containing
the highlighted source `Any **reStructuredText** or MyST markup here.`
and, below it, that markup rendered (with `reStructuredText` in bold).

### Options and arguments

| Part | Description |
| ---- | ----------- |
| *(argument)* | The title shown as a rubric above the block. Defaults to `Example`; inline markup is parsed. |
| `:highlight:` | Override the source pane's highlight language (for example `:highlight: python`). |

If `:highlight:` is omitted, the language is inferred from the document's format
via the project's configured source-suffix mapping
(`sphinx.util.get_filetype` over `source_suffix` — the same knowledge Sphinx's
router uses to pick the parser). A Markdown document yields a `myst` lexer when
one is registered (as [myst-parser](https://myst-parser.readthedocs.io) registers)
else `markdown`, and everything else yields `rst`.
A `:highlight:` value naming a lexer added with `app.add_lexer` — one that
exists only for your project, and so is invisible to Pygments' global registry —
is honoured too. An unknown value falls back to the inferred language
(with a verbose-level note) rather than failing a strict `-W` build.

### Numbering

| Config value | Default | Description |
| ------------ | ------- | ----------- |
| `syntax_example_numbering` | `False` | Number the examples in each document. |

Titles are unnumbered by default. Set `syntax_example_numbering = True` in
`conf.py` to have the default title become a numbered label, with any argument
carried as a subtitle:

```text
.. syntax-example::          →  Example 1
.. syntax-example:: Custom   →  Example 2: Custom
```

The counter restarts at 1 in each document, and each registered directive name
counts independently, so a downstream alias never shares the run.
Numbering only decorates a non-empty default title: a subclass whose
`default_title` is `""` is unaffected by the config value.

Either way the extension keeps **no cross-document state**. The counter lives in
`env.temp_data`, which Sphinx replaces for each source file it reads — and a
document is exactly the unit of both parallel reading and incremental
rebuilding, so re-reading one changed file reproduces the numbers of a full
build and nothing crosses between parallel workers.

## Subclassing

Downstream packages that want an aliased directive
(for example `.. need-example::` with its own label, a different class prefix,
or no title at all) subclass `SyntaxExampleDirective`
and register the subclass under the alias name in a `setup(app)` of their own.
Behaviour is customised through small named seams and class attributes,
never by re-implementing `run`:

- the class attributes `default_title`, `wrapper_classes`, `source_classes`
  and `render_classes` — the single source of the CSS classes on the three
  parts, applied by `run` itself;
- `default_language` — how the source language is inferred;
- `format_title` — the title/numbering seam
  (return `None` to drop the title, as a numbering-free `myst-example` would,
  or ignore `syntax_example_numbering` to number on your own terms);
- `build_title_node` — how the resolved title becomes a node
  (return `None` to suppress the rubric element entirely);
- `build_wrapper_node` and `build_render_node` — the node *type* and any extra
  attributes on the two containers, for a subclass needing something other than
  a plain `container`;
- `source_text` — what the source pane shows;
- `render_into` — what is nested-parsed into the render pane.

Two helpers exist for those overrides to call:
`per_document_number()` returns the next number in the current document
(keyed by the registered directive name, so aliases count independently),
and `nested_parse_text(text, container)` parses a *string* of markup into a
node using the host document's own parser.

`source_text` and `render_into` together are the seam for a "shown source
differs from rendered output" directive: override `source_text` to return the
shown text, and `render_into` to render the alternative output.

```python
from docutils.parsers.rst import directives

from sphinx_syntax_example import SyntaxExampleDirective


class NumberedExample(SyntaxExampleDirective):
    """Numbered unconditionally, regardless of syntax_example_numbering."""

    def format_title(self, raw_title):
        return f"{raw_title or 'Example'} {self.per_document_number()}"


class AltOutputExample(SyntaxExampleDirective):
    """Shows verbatim source, renders something else.

    Takes the alternative markup from an ``:alt-output:`` option.
    """

    option_spec = {
        **SyntaxExampleDirective.option_spec,
        "alt-output": directives.unchanged,
    }

    def render_into(self, container):
        alternative = self.options.get("alt-output")
        if alternative is None:
            super().render_into(container)
        else:
            self.nested_parse_text(alternative, container)


def setup(app):
    app.add_directive("numbered-example", NumberedExample)
    app.add_directive("alt-example", AltOutputExample)
```

`build_wrapper_node` and `build_render_node` exist for renderers that must not
emit a docutils `container`. A myst-parser-style example returns a
sphinx-design div (`is_div=True`, `design_component="div"`) instead, so that
extension's container visitor writes `<div class="myst-example docutils">`
*without* the `container` class — keeping Bootstrap- and pydata-theme
`.container` layout rules off the frame:

```python
from docutils import nodes

from sphinx_syntax_example import SyntaxExampleDirective


class DivExample(SyntaxExampleDirective):
    wrapper_classes = ("myst-example",)
    render_classes = ("myst-example-render",)

    def build_wrapper_node(self):
        return nodes.container(is_div=True, design_component="div")

    def build_render_node(self):
        return nodes.container(is_div=True, design_component="div")
```

Return the bare node: these seams choose the node type and its extra
attributes, and `run` applies the class attributes to whatever comes back
(merging with any class the factory set). So an override neither has to repeat
the classes nor can accidentally drop them and render unstyled.

The full override surface is documented in the module docstring.

The bespoke "example" directives shipped by
[sphinx-needs](https://sphinx-needs.readthedocs.io) and myst-parser
(each rendering source next to output) can be replaced by a subclass of this
directive.

## Contributing

See [CONTRIBUTING.md](https://github.com/sphinx-extensions2/sphinx-syntax-example/blob/main/CONTRIBUTING.md).

[pypi-badge]: https://img.shields.io/pypi/v/sphinx-syntax-example.svg
[pypi-link]: https://pypi.org/project/sphinx-syntax-example
[rtd-badge]: https://readthedocs.org/projects/sphinx-syntax-example/badge/?version=latest
[rtd-link]: https://sphinx-syntax-example.readthedocs.io
[ci-badge]: https://github.com/sphinx-extensions2/sphinx-syntax-example/actions/workflows/tests.yml/badge.svg
[ci-link]: https://github.com/sphinx-extensions2/sphinx-syntax-example/actions/workflows/tests.yml
