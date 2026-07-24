# sphinx-syntax-example

[![PyPI][pypi-badge]][pypi-link]

> A Sphinx extension adding the `syntax-example` directive,
> which shows a block of markup as **both** its raw source and its rendered result.

The directive renders its content twice, stacked inside one framed box:
a syntax-highlighted **source pane** showing what to type,
and a **render pane** showing what it produces.
It is useful for documentation that teaches a markup syntax,
where readers need to see the input alongside the output.

## Installation

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

The output is a pure function of the directive instance —
there is no auto-numbering and no cross-document state —
so the block is reproducible and safe under parallel builds.

### Options and arguments

| Part | Description |
| ---- | ----------- |
| *(argument)* | The title shown as a rubric above the block. Defaults to `Example`; inline markup is parsed. |
| `:highlight:` | Override the source pane's Pygments highlight language (for example `:highlight: python`). |

If `:highlight:` is omitted, the language is inferred from the document's format
via the project's configured source-suffix mapping
(`sphinx.util.get_filetype` over `source_suffix` — the same knowledge Sphinx's
router uses to pick the parser). A Markdown document yields a `myst` lexer when
one is registered (as [myst-parser](https://myst-parser.readthedocs.io) registers)
else `markdown`, and everything else yields `rst`.
An unknown `:highlight:` value falls back to the inferred language
(with a verbose-level note) rather than failing a strict `-W` build.

## Subclassing

Downstream packages that want an aliased directive
(for example `.. need-example::` with auto-numbering, a different class prefix,
or no title at all) subclass `SyntaxExampleDirective`
and register the subclass under the alias name in a `setup(app)` of their own.
Behaviour is customised through small named seams and class attributes,
never by re-implementing `run`:

- the class attributes `default_title`, `wrapper_classes`, `source_classes`
  and `render_classes`;
- `default_language` — how the source language is inferred;
- `format_title` — the title/numbering seam
  (return `None` to drop the title, as a numbering-free `myst-example` would);
- `build_title_node` — how the resolved title becomes a node
  (return `None` to suppress the rubric element entirely);
- `source_text` — what the source pane shows;
- `render_into` — what is nested-parsed into the render pane.

The last two are the seam for a "shown source differs from rendered output"
directive: override `source_text` to return the shown text
and `render_into` to render the alternative output.

```python
from sphinx_syntax_example import SyntaxExampleDirective


class NumberedExample(SyntaxExampleDirective):
    def format_title(self, raw_title):
        meta = self.env.metadata[self.env.docname]
        number = meta.setdefault("_ex_number", 1)
        meta["_ex_number"] = number + 1
        return f"{raw_title or 'Example'} {number}"


def setup(app):
    app.add_directive("numbered-example", NumberedExample)
```

The full override surface is documented in the module docstring.

The bespoke "example" directives shipped by
[sphinx-needs](https://sphinx-needs.readthedocs.io) and myst-parser
(each rendering source next to output) can be replaced by a subclass of this
directive.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

[pypi-badge]: https://img.shields.io/pypi/v/sphinx-syntax-example.svg
[pypi-link]: https://pypi.org/project/sphinx-syntax-example
