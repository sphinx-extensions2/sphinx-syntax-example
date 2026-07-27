"""A syntax-example directive that shows markup as source and rendered result.

The directive renders its content **twice**: once as a syntax-highlighted view
of the raw source, and once as the rendered result of parsing that source.
It is useful for documentation that teaches a markup syntax,
where readers need to see both what to type and what it produces.

.. code-block:: rst

   .. syntax-example:: An optional title

      Any **reStructuredText** or MyST markup here.

The output is a pure function of the directive instance —
there is no auto-numbering and no cross-document state —
so the block is reproducible and safe under parallel builds.

The source block's language is the ``:highlight:`` option when it names a
registered Pygments lexer, otherwise it is inferred from the document's format.
The format is taken from the project's configured source-suffix mapping
(:func:`sphinx.util.get_filetype` over ``config.source_suffix`` — the same
knowledge Sphinx's router uses to pick the parser, so a user-remapped suffix is
honoured), falling back to the plain file extension for paths outside that
mapping: a Markdown source yields a ``myst`` lexer when one is registered (as
myst-parser registers) else ``markdown``, and everything else yields ``rst``.
An unknown ``:highlight:`` value falls back to the inferred language (with a
verbose-level note) rather than failing a strict ``-W`` build.

The directive is theme-agnostic: it makes no assumption about the active Sphinx
theme, imports nothing beyond docutils / Sphinx / Pygments, and relies only on
the stable public ``get_filetype`` / ``config.source_suffix`` API. The package
ships one small stylesheet (registered on an HTML build via
:func:`_add_static_assets`) whose colours degrade gracefully across themes.

Subclassing
-----------

Downstream packages that want an aliased directive
(for example ``.. need-example::`` with auto-numbering, a different class
prefix, or no title at all) subclass :class:`SyntaxExampleDirective`.
The intended override surface is:

- the class attributes :attr:`~SyntaxExampleDirective.default_title`,
  :attr:`~SyntaxExampleDirective.wrapper_classes`,
  :attr:`~SyntaxExampleDirective.source_classes` and
  :attr:`~SyntaxExampleDirective.render_classes`;
- :meth:`~SyntaxExampleDirective.default_language` — how the source language is
  inferred;
- :meth:`~SyntaxExampleDirective.format_title` — the title/numbering seam
  (return ``None`` to drop the title, as a numbering-free ``myst-example`` would);
- :meth:`~SyntaxExampleDirective.build_title_node` — how the resolved title
  becomes a node (return ``None`` to suppress the rubric element entirely);
- :meth:`~SyntaxExampleDirective.source_text` — what the source pane shows;
- :meth:`~SyntaxExampleDirective.render_into` — what is nested-parsed into the
  render pane.

The last two are the seam for a "shown source differs from rendered output"
directive (myst-parser's ``:alt-output:``): override ``source_text`` to return
the shown text and ``render_into`` to parse the alternative output.
Register the subclass under the alias name in a ``setup(app)`` of your own.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from docutils import nodes
from docutils.parsers.rst import directives
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound
from sphinx.application import Sphinx
from sphinx.errors import FiletypeNotFoundError
from sphinx.util import get_filetype, logging
from sphinx.util.docutils import SphinxDirective

__version__ = "0.1.0"

logger = logging.getLogger(__name__)

#: Directory holding the packaged stylesheet, shipped inside the package.
_STATIC_DIR = Path(__file__).parent / "static"
#: The stylesheet file name, registered on HTML builds.
_CSS_FILE = "sphinx-syntax-example.css"

#: The CSS class on the outer wrapper, and the two part wrappers.
#: The shipped stylesheet (``static/sphinx-syntax-example.css``) targets these
#: classes; a downstream renderer that emits the same classes reuses the rules.
_WRAPPER_CLASS = "syntax-example"
_SOURCE_CLASS = "syntax-example-source"
_RENDER_CLASS = "syntax-example-render"

#: Source-file suffixes treated as Markdown for language inference.
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})


def _lexer_available(name: str) -> bool:
    """Return whether a Pygments lexer is registered under ``name``.

    :param name: The lexer name to probe.
    :returns: True when :func:`pygments.lexers.get_lexer_by_name` resolves it.
    """
    try:
        get_lexer_by_name(name)
    except ClassNotFound:
        return False
    return True


class SyntaxExampleDirective(SphinxDirective):
    """Show a block of markup as both its source and its rendered result.

    The optional argument is a title, rendered as a rubric above the block
    (defaulting to :attr:`default_title` when absent).
    The ``:highlight:`` option overrides the source block's highlight language,
    which is otherwise inferred from the current document's format.

    Subclasses customise behaviour through the small named seams
    (:meth:`format_title`, :meth:`build_title_node`, :meth:`source_text`,
    :meth:`render_into`, :meth:`default_language`) and the class attributes,
    never by re-implementing :meth:`run` — see the module docstring.
    """

    optional_arguments = 1
    final_argument_whitespace = True
    has_content = True
    option_spec: ClassVar[dict[str, Callable[[str], Any]]] = {
        "highlight": directives.unchanged,
    }

    #: The title used when no argument is given; ``""`` suppresses the title
    #: (subclass override point).
    default_title = "Example"
    #: Classes applied to the outer container (subclass override point).
    wrapper_classes = (_WRAPPER_CLASS,)
    #: Classes applied to the source literal block (subclass override point).
    source_classes = (_SOURCE_CLASS,)
    #: Classes applied to the rendered-result container (subclass override point).
    render_classes = (_RENDER_CLASS,)

    def format_title(self, raw_title: str | None) -> str | None:
        """Resolve the block's title text — the title/numbering seam.

        The canonical behaviour returns the argument, or :attr:`default_title`
        when there is no argument. Override this to add a label or a counter
        (for example ``Example 1``), or return ``None`` for a directive that
        never shows a title.

        :param raw_title: The directive argument (stripped), or ``None`` when
            no argument was given.
        :returns: The final title text, or ``None`` to show no title.
        """
        if raw_title:
            return raw_title
        return self.default_title or None

    def build_title_node(self, title: str | None) -> nodes.Node | None:
        """Build the title node from the resolved title — the title-node seam.

        Returns ``None`` for an empty or absent title so no rubric element is
        emitted at all (rather than an empty ``<p class="rubric">``). Inline
        markup in the title is parsed, so a title may carry emphasis or a role.

        :param title: The resolved title text from :meth:`format_title`.
        :returns: A rubric node, or ``None`` to suppress the title element.
        """
        if not title:
            return None
        title_nodes, _ = self.state.inline_text(title, self.lineno)
        return nodes.rubric(title, "", *title_nodes)

    def source_text(self) -> str:
        """Return the text shown in the source pane — the source-side seam.

        The canonical behaviour is the verbatim directive content. Override
        together with :meth:`render_into` for a directive whose shown source
        differs from its rendered output.

        :returns: The text of the highlighted source block.
        """
        return "\n".join(self.content)

    def render_into(self, container: nodes.Element) -> None:
        """Populate the render pane — the render-side seam.

        The canonical behaviour nested-parses the verbatim content. Override
        together with :meth:`source_text` to render output other than the
        shown source.

        :param container: The render container node to populate in place.
        """
        self.state.nested_parse(self.content, self.content_offset, container)

    def default_language(self) -> str:
        """Infer the source block's highlight language from the document format.

        The format is resolved from the project's configured source-suffix
        mapping via :func:`sphinx.util.get_filetype` — the same knowledge the
        Sphinx router uses to choose the parser, so a user-remapped suffix is
        honoured rather than a hardcoded guess. A path outside that mapping
        (a fragment with a non-source suffix, or no path) raises
        :exc:`~sphinx.errors.FiletypeNotFoundError`, which falls back to the
        plain file extension and then to ``rst`` — never propagating, so a
        strict ``-W`` build is not broken by an include fragment.

        A Markdown format yields ``myst`` when a MyST Pygments lexer is
        registered and ``markdown`` otherwise; any other format yields ``rst``.

        :returns: A Pygments lexer name for the raw source block.
        """
        source, _ = self.get_source_info()
        try:
            filetype = get_filetype(self.config.source_suffix, source or "")
        except FiletypeNotFoundError:
            # No configured suffix matched: fall back to the plain extension.
            suffix = Path(source).suffix.lower() if source else ""
            filetype = "markdown" if suffix in _MARKDOWN_SUFFIXES else "restructuredtext"
        if filetype == "markdown":
            return "myst" if _lexer_available("myst") else "markdown"
        return "rst"

    def resolve_language(self) -> str:
        """Resolve the source block's highlight language.

        The ``:highlight:`` option wins when it names a registered Pygments
        lexer; an unknown value falls back to :meth:`default_language` (with a
        verbose-level note) so a strict ``-W`` build is not broken by a typo.

        :returns: A Pygments lexer name known to be resolvable.
        """
        highlight = str(self.options.get("highlight", "")).strip()
        if highlight and _lexer_available(highlight):
            return highlight
        inferred = self.default_language()
        if highlight:
            logger.verbose(
                "syntax-example: unknown highlight language %r, using %r",
                highlight,
                inferred,
                location=self.get_location(),
            )
        return inferred

    def run(self) -> list[nodes.Node]:
        """Build the example subtree from the override seams.

        A bodyless directive is reported as an error (there is nothing to
        show in either pane) rather than rendering an empty frame.

        :returns: A single container node.
        """
        self.assert_has_content()
        wrapper = nodes.container(classes=list(self.wrapper_classes))
        self.set_source_info(wrapper)

        raw_title = self.arguments[0].strip() if self.arguments else None
        title_node = self.build_title_node(self.format_title(raw_title))
        if title_node is not None:
            wrapper += title_node

        # The raw source, as a highlightable literal block. ``rawsource`` must
        # equal the text so Sphinx highlights it (a mismatch marks it as a
        # parsed-literal and skips highlighting).
        source = self.source_text()
        wrapper += nodes.literal_block(
            source,
            source,
            language=self.resolve_language(),
            classes=list(self.source_classes),
        )

        rendered = nodes.container(classes=list(self.render_classes))
        self.render_into(rendered)
        wrapper += rendered

        return [wrapper]


def _add_static_assets(app: Sphinx) -> None:
    """Register the packaged stylesheet (HTML-format builders only).

    Mirrors the asset-shipping mechanism used by mature extensions: the CSS
    file lives inside the package, its directory is appended to
    ``html_static_path`` so Sphinx copies it into ``_static``, and the file is
    then linked via :meth:`~sphinx.application.Sphinx.add_css_file`.

    :param app: The Sphinx application.
    """
    if app.builder.format != "html":
        return
    app.config.html_static_path.append(str(_STATIC_DIR))
    app.add_css_file(_CSS_FILE)


def setup(app: Sphinx) -> dict[str, object]:
    """Register the ``syntax-example`` directive and its stylesheet.

    :param app: The Sphinx application.
    :returns: Extension metadata declaring the directive parallel-safe
        (it holds no cross-document state).
    """
    app.add_directive("syntax-example", SyntaxExampleDirective)
    app.connect("builder-inited", _add_static_assets)
    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
