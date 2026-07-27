"""A syntax-example directive that shows markup as source and rendered result.

The directive renders its content **twice**: once as a syntax-highlighted view
of the raw source, and once as the rendered result of parsing that source.
It is useful for documentation that teaches a markup syntax,
where readers need to see both what to type and what it produces.

.. code-block:: rst

   .. syntax-example:: An optional title

      Any **reStructuredText** or MyST markup here.

Titles are unnumbered by default. Setting ``syntax_example_numbering = True``
turns on per-document numbering, so the block above is titled
*Example 1: An optional title* and an untitled one after it *Example 2* — the
shape sphinx-needs' bespoke ``need-example`` directive produced.

Either way the extension keeps **no cross-document state**: the counter lives
in ``env.temp_data``, which Sphinx replaces for each source file it reads, so
numbers restart at 1 per document. Documents are the unit of parallelism and of
incremental rebuilds, which is exactly the scope of that state — re-reading one
changed file reproduces the numbers of a full build, and nothing crosses
between parallel read workers.

The source block's language is the ``:highlight:`` option when it names a
registered lexer — either a Pygments one or a project-local one added with
:meth:`~sphinx.application.Sphinx.add_lexer` — otherwise it is inferred from
the document's format.
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
(for example ``.. need-example::`` with its own label, a different class
prefix, or no title at all) subclass :class:`SyntaxExampleDirective`.
The intended override surface is:

- the class attributes :attr:`~SyntaxExampleDirective.default_title`,
  :attr:`~SyntaxExampleDirective.wrapper_classes`,
  :attr:`~SyntaxExampleDirective.source_classes` and
  :attr:`~SyntaxExampleDirective.render_classes` — the single source of the
  CSS classes on the three parts, applied by
  :meth:`~SyntaxExampleDirective.run` itself;
- :meth:`~SyntaxExampleDirective.default_language` — how the source language is
  inferred;
- :meth:`~SyntaxExampleDirective.format_title` — the title/numbering seam
  (return ``None`` to drop the title, as a numbering-free ``myst-example``
  would, or ignore ``syntax_example_numbering`` to number unconditionally);
- :meth:`~SyntaxExampleDirective.build_title_node` — how the resolved title
  becomes a node (return ``None`` to suppress the rubric element entirely);
- :meth:`~SyntaxExampleDirective.build_wrapper_node` and
  :meth:`~SyntaxExampleDirective.build_render_node` — the node *type* and any
  extra attributes on the two containers, for a subclass needing something
  other than a plain container. These return a bare node: the classes above
  are applied afterwards either way, so an override neither has to copy them
  nor can drop them;
- :meth:`~SyntaxExampleDirective.source_text` — what the source pane shows;
- :meth:`~SyntaxExampleDirective.render_into` — what is nested-parsed into the
  render pane.

``source_text`` and ``render_into`` together are the seam for a "shown source
differs from rendered output" directive (myst-parser's ``:alt-output:``):
override ``source_text`` to return the shown text and ``render_into`` to parse
the alternative output — via
:meth:`~SyntaxExampleDirective.nested_parse_text`, which parses a *string* of
markup into the render pane (the content-list-based default cannot).
:meth:`~SyntaxExampleDirective.per_document_number` supplies the counter for a
``format_title`` that numbers its examples on its own terms; it is the same
helper the built-in ``syntax_example_numbering`` behaviour uses, and it keys
the counter by the registered directive name, so an alias numbers independently
of ``syntax-example``.
Register the subclass under the alias name in a ``setup(app)`` of your own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from docutils import nodes
from docutils.parsers.rst import directives
from docutils.statemachine import StringList
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound
from sphinx import highlighting as sphinx_highlighting
from sphinx.application import Sphinx
from sphinx.errors import FiletypeNotFoundError
from sphinx.util import get_filetype, logging
from sphinx.util.docutils import SphinxDirective

__version__ = "0.1.1"

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

#: The module-level mappings in :mod:`sphinx.highlighting` that a Sphinx build
#: resolves a highlight language against before falling back to Pygments:
#: ``lexer_classes`` (where :meth:`~sphinx.application.Sphinx.add_lexer` puts a
#: lexer class) and ``lexers`` (the legacy instance registry). Both are read by
#: name rather than imported, so a rename in a future Sphinx degrades to the
#: Pygments-only probe instead of raising at import time.
_SPHINX_LEXER_REGISTRIES = ("lexer_classes", "lexers")


def _lexer_available(name: str) -> bool:
    """Return whether any lexer this project can highlight with answers to ``name``.

    Both registries a Sphinx build consults are probed: first the app-level
    ones in :mod:`sphinx.highlighting`, which is where
    :meth:`~sphinx.application.Sphinx.add_lexer` registers a lexer that exists
    only for one project (myst-parser's own documentation adds a local ``myst``
    lexer that way), then Pygments' global registry. Consulting only the latter
    would silently reject a perfectly valid ``:highlight:`` value.

    The Sphinx registries are looked up by name and checked for mapping-ness
    before use, so neither a rename nor a reshape can turn this into a crash.
    Both probes are read-only — a dict membership test and a Pygments alias
    lookup — leaving no registration behind and costing nothing measurable.

    :param name: The lexer name to probe.
    :returns: True when a Sphinx-registered or Pygments lexer resolves it.
    """
    for registry_name in _SPHINX_LEXER_REGISTRIES:
        registry = getattr(sphinx_highlighting, registry_name, None)
        if isinstance(registry, Mapping) and name in registry:
            return True
    try:
        get_lexer_by_name(name)
    except ClassNotFound:
        return False
    return True


class SyntaxExampleDirective(SphinxDirective):
    """Show a block of markup as both its source and its rendered result.

    The optional argument is a title, rendered as a rubric above the block
    (defaulting to :attr:`default_title` when absent, and numbered per document
    when ``syntax_example_numbering`` is enabled).
    The ``:highlight:`` option overrides the source block's highlight language,
    which is otherwise inferred from the current document's format.

    Subclasses customise behaviour through the small named seams
    (:meth:`format_title`, :meth:`build_title_node`, :meth:`build_wrapper_node`,
    :meth:`build_render_node`, :meth:`source_text`, :meth:`render_into`,
    :meth:`default_language`) and the class attributes, never by
    re-implementing :meth:`run` — see the module docstring. Two helpers exist
    for those overrides to call: :meth:`per_document_number` (a numbering
    counter) and :meth:`nested_parse_text` (parse a string of markup).
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

        By default this returns the argument, or :attr:`default_title` when
        there is no argument. With ``syntax_example_numbering = True`` in the
        project's configuration, :attr:`default_title` instead becomes a
        numbered label carrying the argument as a subtitle — ``Example 1``, or
        ``Example 5: the filter option`` — reproducing the shape of
        sphinx-needs' bespoke ``need-example`` directive. The number comes from
        :meth:`per_document_number`, so it is per document and per registered
        directive name: an alias counts separately from ``syntax-example``.

        Numbering only ever decorates a non-empty :attr:`default_title`, since
        the number belongs to the *label*, not to the author's own words. A
        subclass whose :attr:`default_title` is ``""`` is therefore unaffected
        by the config value: with no argument its title stays suppressed, and
        with one its title stays exactly the argument.

        Overriding this method opts out of the config value entirely (call
        :meth:`per_document_number` directly for numbering on other terms).

        :param raw_title: The directive argument (stripped), or ``None`` when
            no argument was given.
        :returns: The final title text, or ``None`` to show no title.
        """
        label = self.default_title or None
        if label and self.config.syntax_example_numbering:
            label = f"{label} {self.per_document_number()}"
            return f"{label}: {raw_title}" if raw_title else label
        if raw_title:
            return raw_title
        return label

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

    def build_wrapper_node(self) -> nodes.Element:
        """Build the outer frame node — the wrapper-node seam.

        This seam decides the node *type* and any extra attributes on it —
        nothing else. :meth:`run` then applies :attr:`wrapper_classes` to
        whatever comes back, sets the source info on it, and fills it with the
        title, source and render parts. An override therefore never copies the
        class attributes, and cannot accidentally drop them: they stay the
        single source of the CSS classes, and the packaged stylesheet keeps
        working. Returning a bare node here is correct.

        The motivating case is a myst-parser-style example, whose wrapper is a
        sphinx-design div (``is_div=True``, ``design_component="div"``): given
        those attributes, sphinx-design's overridden container visitor writes
        ``<div class="myst-example docutils">`` *without* the ``container``
        class, keeping Bootstrap- and pydata-theme ``.container`` layout rules
        off the frame.

        :returns: An empty, class-free node for the example's parts.
        """
        return nodes.container()

    def build_render_node(self) -> nodes.Element:
        """Build the render-pane node — the render-node seam.

        The counterpart of :meth:`build_wrapper_node`, under the same contract:
        return the bare node, and :meth:`run` applies :attr:`render_classes` to
        it before handing it to :meth:`render_into`. Override this to emit a
        sphinx-design div (or any other node) rather than a ``container``.

        :returns: An empty, class-free node to be passed to :meth:`render_into`.
        """
        return nodes.container()

    def _apply_classes(self, node: nodes.Element, classes: Sequence[str]) -> None:
        """Add ``classes`` to ``node``, preserving any it already carries.

        :param node: The node returned by one of the node-building seams.
        :param classes: The class attribute to apply.
        """
        existing = node["classes"]
        existing += [cls for cls in classes if cls not in existing]

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

    def per_document_number(self, key: str | None = None) -> int:
        """Increment and return a per-document counter — the numbering helper.

        This is what the built-in ``syntax_example_numbering`` behaviour counts
        with; call it directly from a :meth:`format_title` override that labels
        its examples on other terms. The first call in a document returns ``1``.

        The counter lives in ``env.temp_data``, which Sphinx replaces wholesale
        for each source file it reads. That scoping is what makes the numbering
        safe where a cross-document counter would not be: numbers restart at
        ``1`` per document, so re-reading a single changed file on an
        incremental build reproduces exactly the numbers of a full build, and
        no state crosses between the worker processes of a parallel read.

        :param key: The counter's key in ``temp_data``. Defaults to one
            namespaced by the name the directive was registered under —
            case-folded, since reStructuredText directive names are
            case-insensitive and two spellings of one directive must share a
            run — so sibling directives count independently; pass an explicit
            key to share one counter across several directives.
        :returns: The next number in the current document, counting from 1.
        """
        counter_key = key or f"syntax-example-count:{self.name.lower()}"
        # ``temp_data`` is a namespace shared with every other extension, so a
        # value of another type under this key restarts rather than raising.
        previous = self.env.temp_data.get(counter_key, 0)
        number = previous + 1 if isinstance(previous, int) else 1
        self.env.temp_data[counter_key] = number
        return number

    def nested_parse_text(self, text: str, container: nodes.Element) -> None:
        """Parse a string of markup into ``container`` — the markup helper.

        :meth:`render_into` receives the directive's content as a pre-built
        line list; an override that renders *something else* (myst-parser's
        ``:alt-output:``, which shows verbatim source in one pane and the
        result of different markup in the other) has only a string, and needs
        it wrapped in a :class:`~docutils.statemachine.StringList` first.

        The lines are attributed to the directive's own source file, and offset
        as its content is, so a warning raised while parsing them points into
        the directive rather than at line 1 of an anonymous block. Passing
        ``content_offset`` — exactly what the default :meth:`render_into` does
        — is also what keeps that true across parsers, each of which reads the
        offset in its own frame of reference. The attribution is approximate by
        construction: line *i* of ``text`` is reported at the directive's
        content offset plus *i*, so markup longer than the content it replaces
        reports past the end of the directive. It names the right file and the
        right neighbourhood, which is what a reader needs.

        Parsing goes through ``state.nested_parse``, i.e. the parser of the
        *host* document: the same call renders reStructuredText in an ``.rst``
        file and MyST in a Markdown one, with no format sniffing here.

        :param text: The markup to parse.
        :param container: The node to populate in place.
        """
        source, _ = self.get_source_info()
        # A fragment outside the source tree reports no path; docutils wants a
        # string either way, and an empty one is what it uses for "unknown".
        path = source or ""
        lines = text.splitlines()
        block = StringList(
            lines,
            source=path,
            items=[(path, self.content_offset + offset) for offset in range(len(lines))],
        )
        self.state.nested_parse(block, self.content_offset, container)

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

        The ``:highlight:`` option wins when it names a lexer registered with
        Pygments *or* with the Sphinx app (via
        :meth:`~sphinx.application.Sphinx.add_lexer`); an unknown value falls
        back to :meth:`default_language` (with a verbose-level note) so a
        strict ``-W`` build is not broken by a typo.

        :returns: A lexer name known to be resolvable at highlight time.
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

        The three class attributes are applied here, uniformly, to whatever the
        node-building seams returned — so a subclass that swaps a node type
        cannot silently lose the classes the stylesheet targets.

        :returns: A single wrapper node.
        """
        self.assert_has_content()
        wrapper = self.build_wrapper_node()
        self._apply_classes(wrapper, self.wrapper_classes)
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

        rendered = self.build_render_node()
        self._apply_classes(rendered, self.render_classes)
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
    """Register the ``syntax-example`` directive, its config value and stylesheet.

    ``syntax_example_numbering`` is an ``env`` rebuild category: it changes the
    text of every title written into a doctree, so toggling it must re-read the
    sources rather than only re-render them.

    :param app: The Sphinx application.
    :returns: Extension metadata declaring the directive parallel-safe
        (its only state is per document, and documents are the unit of
        parallelism).
    """
    app.add_directive("syntax-example", SyntaxExampleDirective)
    app.add_config_value(
        "syntax_example_numbering",
        False,
        "env",
        types=frozenset({bool}),
    )
    app.connect("builder-inited", _add_static_assets)
    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
