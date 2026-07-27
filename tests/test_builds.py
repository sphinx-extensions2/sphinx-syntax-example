"""End-to-end build tests for the ``syntax-example`` directive.

Each test builds a tiny Sphinx project in a temporary directory, in-process
(rather than shelling out), so the extension's coverage is recorded and no
external ``sphinx`` on ``PATH`` is required. Behaviour is asserted against the
resulting doctree and, where relevant, the emitted HTML and build warnings —
mirroring the harness used by sibling ``sphinx-extensions2`` projects, but with
targeted structural assertions instead of committed doctree snapshots (chosen
for robustness across the Sphinx 7.2-9.x matrix).
"""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from pathlib import Path
import pickle
import re
import shutil
import sys
from textwrap import dedent
from types import SimpleNamespace

from docutils import nodes
import pytest
from sphinx import highlighting
from sphinx.application import Sphinx
from sphinx.util.docutils import docutils_namespace, patch_docutils

from sphinx_syntax_example import SyntaxExampleDirective


@pytest.fixture(autouse=True)
def _isolate_lexer_registries() -> Iterator[None]:
    """Restore ``sphinx.highlighting``'s lexer registries around each test.

    ``app.add_lexer`` writes into module-level dicts, which — unlike the
    docutils registrations that ``docutils_namespace`` takes care of — would
    otherwise leak from one in-process build into every later one.
    """
    names = ("lexers", "lexer_classes")
    saved = {name: dict(getattr(highlighting, name)) for name in names}
    yield
    for name, entries in saved.items():
        registry = getattr(highlighting, name)
        registry.clear()
        registry.update(entries)


class BuildResult:
    """The outcome of an in-process Sphinx build."""

    def __init__(self, build: Path, stdout: str, stderr: str) -> None:
        self._build = build
        self._stdout = stdout
        self._stderr = stderr

    @property
    def build(self) -> Path:
        return self._build

    @property
    def stdout(self) -> str:
        return self._stdout

    @property
    def stderr(self) -> str:
        return self._stderr

    def doctree(self, docname: str = "index") -> nodes.document:
        path = self._build / "doctrees" / f"{docname}.doctree"
        doc = pickle.loads(path.read_bytes())
        assert isinstance(doc, nodes.document)
        return doc


def run_sphinxbuild(
    path: Path,
    *,
    buildername: str = "html",
    warningiserror: bool = False,
    clear_build: bool = True,
) -> BuildResult:
    """Build the Sphinx project at ``path`` in-process and return the result.

    :param path: the source directory (also used as the config directory).
    :param buildername: the Sphinx builder to run (``html`` by default).
    :param warningiserror: turn warnings into errors, exercising ``-W`` safety.
    :param clear_build: remove any previous build output first (full build).
    """
    build_path = path / "_build"
    if clear_build and build_path.is_dir():
        shutil.rmtree(build_path)

    status, warning = StringIO(), StringIO()

    # Isolate any module a conf.py imports from the source directory, so an
    # in-process build cannot leak state into a later build.
    src = path.resolve()
    saved_sys_path = sys.path.copy()
    try:
        # patch_docutils + docutils_namespace stop docutils registrations
        # (directives/roles/nodes) leaking between builds.
        with patch_docutils(str(path)), docutils_namespace():
            app = Sphinx(
                srcdir=str(path),
                confdir=str(path),
                outdir=str(build_path / buildername),
                doctreedir=str(build_path / "doctrees"),
                buildername=buildername,
                status=status,
                warning=warning,
                warningiserror=warningiserror,
            )
            app.build()
    finally:
        sys.path[:] = saved_sys_path
        for name, module in list(sys.modules.items()):
            module_file = getattr(module, "__file__", None)
            if module_file and Path(module_file).resolve().is_relative_to(src):
                del sys.modules[name]

    return BuildResult(build_path, status.getvalue(), warning.getvalue())


CONF_CONTENT = """
version = "0.1"
extensions = ["sphinx_syntax_example"]
"""


def _wrapper(doc: nodes.document) -> nodes.container:
    """Return the single ``syntax-example`` wrapper container in ``doc``."""
    for container in doc.findall(nodes.container):
        if "syntax-example" in container["classes"]:
            return container
    raise AssertionError("no .syntax-example wrapper found in doctree")


def _source_block(wrapper: nodes.Element) -> nodes.literal_block:
    """Return the source-pane literal block of a wrapper."""
    for block in wrapper.findall(nodes.literal_block):
        if "syntax-example-source" in block["classes"]:
            return block
    raise AssertionError("no .syntax-example-source block found")


def _render_pane(wrapper: nodes.Element) -> nodes.container:
    """Return the render-pane container of a wrapper."""
    for container in wrapper.findall(nodes.container):
        if "syntax-example-render" in container["classes"]:
            return container
    raise AssertionError("no .syntax-example-render container found")


def test_basic_render(tmp_path: Path) -> None:
    """The directive emits a framed wrapper with a default rubric, a source
    literal block, and a render pane that nested-parses the content."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::

               Some **bold** content.
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr

    wrapper = _wrapper(result.doctree())

    # default title -> a rubric reading "Example"
    rubrics = list(wrapper.findall(nodes.rubric))
    assert len(rubrics) == 1
    assert rubrics[0].astext() == "Example"

    # source pane: verbatim text, rst language
    source = _source_block(wrapper)
    assert source.astext() == "Some **bold** content."
    assert source["language"] == "rst"

    # render pane: the content parsed (so **bold** became a strong node)
    render = _render_pane(wrapper)
    assert list(render.findall(nodes.strong))


def test_explicit_title(tmp_path: Path) -> None:
    """A directive argument becomes the rubric title."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example:: My Custom Title

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    rubrics = list(_wrapper(result.doctree()).findall(nodes.rubric))
    assert [r.astext() for r in rubrics] == ["My Custom Title"]


def test_title_inline_markup(tmp_path: Path) -> None:
    """Inline markup in the title argument is parsed."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example:: A **bold** title

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    rubric = next(_wrapper(result.doctree()).findall(nodes.rubric))
    assert list(rubric.findall(nodes.strong))


def test_highlight_override(tmp_path: Path) -> None:
    """A valid ``:highlight:`` value overrides the inferred language."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::
               :highlight: python

               print("hello")
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    assert _source_block(_wrapper(result.doctree()))["language"] == "python"


def test_unknown_highlight_falls_back_under_warning_is_error(tmp_path: Path) -> None:
    """An unknown ``:highlight:`` value falls back to the inferred language and
    emits no warning, so a strict ``-W`` build is not broken."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::
               :highlight: not-a-real-lexer

               content
            """
        )
    )
    # warningiserror=True: if the unknown lexer emitted a warning, build() would
    # raise. A clean build proves the verbose-level fallback is -W safe.
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert _source_block(_wrapper(result.doctree()))["language"] == "rst"


def test_css_asset_registered(tmp_path: Path) -> None:
    """The packaged stylesheet is copied into the HTML output and linked."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    css = result.build / "html" / "_static" / "sphinx-syntax-example.css"
    assert css.is_file()
    html = (result.build / "html" / "index.html").read_text(encoding="utf8")
    assert "sphinx-syntax-example.css" in html


def test_non_html_builder_skips_css(tmp_path: Path) -> None:
    """On a non-HTML builder the stylesheet registration is skipped cleanly."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path, buildername="text")
    assert not result.stderr
    assert (result.build / "text" / "index.txt").is_file()
    # no _static/ tree (and hence no stylesheet) is emitted for a text build
    assert not (result.build / "text" / "_static").exists()


def test_markdown_source_detection(tmp_path: Path) -> None:
    """In a MyST Markdown document the source pane uses a Markdown-family
    lexer, inferred from the ``.md`` source suffix."""
    pytest.importorskip("myst_parser")
    (tmp_path / "conf.py").write_text(CONF_CONTENT + "\nextensions.append('myst_parser')\n")
    (tmp_path / "index.md").write_text(
        dedent(
            """\
            # Test

            ```{syntax-example}
            Some **markdown** content
            ```
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    source = _source_block(_wrapper(result.doctree()))
    assert source["language"] in {"myst", "markdown"}
    # the render pane still parses the content as MyST (bold -> strong)
    assert list(_render_pane(_wrapper(result.doctree())).findall(nodes.strong))


def test_empty_content_is_an_error(tmp_path: Path) -> None:
    """A bodyless directive is reported as an error instead of silently
    rendering an empty frame."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::

            A following paragraph.
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert "Content block expected" in result.stderr
    assert not [
        c for c in result.doctree().findall(nodes.container) if "syntax-example" in c["classes"]
    ]


def test_malformed_title_markup_is_reported(tmp_path: Path) -> None:
    """Broken inline markup in the title is reported as a build warning (so a
    strict ``-W`` build catches it) and marked ``problematic`` in the rubric —
    the docutils reporter logs it at parse time, independent of the returned
    system-message nodes."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example:: A *unclosed emphasis title

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert "Inline emphasis start-string" in result.stderr
    rubric = next(_wrapper(result.doctree()).findall(nodes.rubric))
    assert list(rubric.findall(nodes.problematic))


# --- language inference (unit level) --------------------------------------
#
# The FiletypeNotFoundError fallback fires for a source path whose suffix is not
# a configured source suffix. That cannot be provoked through a build (Sphinx's
# ``include`` directive resolves a parser by the fragment's suffix, and the only
# documents read are those whose suffix *is* configured), so it is exercised
# directly on the directive's method. A subclass overrides the two attributes
# ``default_language`` reads — ``get_source_info`` and ``config`` — so the method
# can be called without a full docutils directive construction.


class _LanguageProbe(SyntaxExampleDirective):
    """A ``default_language`` harness with a fixed source path and suffix map."""

    def __init__(self, source: str | None, source_suffix: dict[str, str]) -> None:
        self._source = source
        self._source_suffix = source_suffix

    def get_source_info(self, *args: object, **kwargs: object) -> tuple[str | None, int]:  # type: ignore[override]
        return self._source, 1

    @property
    def config(self):  # type: ignore[override]
        return SimpleNamespace(source_suffix=self._source_suffix)


_RST_ONLY = {".rst": "restructuredtext"}


def test_default_language_configured_suffix() -> None:
    """A path matching a configured source suffix resolves via get_filetype."""
    assert _LanguageProbe("/docs/index.rst", _RST_ONLY).default_language() == "rst"


def test_default_language_markdown_extension_fallback() -> None:
    """An unmapped ``.md`` suffix falls back to a Markdown-family lexer."""
    lang = _LanguageProbe("/docs/fragment.md", _RST_ONLY).default_language()
    assert lang in {"myst", "markdown"}
    lang = _LanguageProbe("/docs/fragment.markdown", _RST_ONLY).default_language()
    assert lang in {"myst", "markdown"}


def test_default_language_unmapped_suffix_fallback() -> None:
    """An unmapped non-Markdown suffix falls back to ``rst``."""
    assert _LanguageProbe("/docs/fragment.txt", _RST_ONLY).default_language() == "rst"


def test_default_language_empty_source() -> None:
    """An empty source path falls back to ``rst`` without raising."""
    assert _LanguageProbe("", _RST_ONLY).default_language() == "rst"


# --- subclass seams -------------------------------------------------------

_SUBCLASS_CONF = CONF_CONTENT + dedent(
    '''
        from docutils import nodes
        from sphinx_syntax_example import SyntaxExampleDirective


        class NoTitleExample(SyntaxExampleDirective):
            """A directive that never shows a title."""

            default_title = ""


        class NumberedExample(SyntaxExampleDirective):
            """A directive that numbers its examples per document."""

            def format_title(self, raw_title):
                return f"{raw_title or 'Example'} {self.per_document_number()}"


        class AltOutputExample(SyntaxExampleDirective):
            """A directive whose shown source differs from its rendered output."""

            def source_text(self):
                return "SHOWN SOURCE"

            def render_into(self, container):
                container += nodes.paragraph(text="RENDERED OUTPUT")


        def setup(app):
            app.add_directive("no-title-example", NoTitleExample)
            app.add_directive("numbered-example", NumberedExample)
            app.add_directive("alt-example", AltOutputExample)
        '''
)


def test_subclass_empty_title_suppresses_rubric(tmp_path: Path) -> None:
    """An empty ``default_title`` with no argument suppresses the rubric
    entirely (no empty rubric element is emitted)."""
    (tmp_path / "conf.py").write_text(_SUBCLASS_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. no-title-example::

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    wrapper = _wrapper(result.doctree())
    assert not list(wrapper.findall(nodes.rubric))
    # the source and render panes are still present and populated
    assert _source_block(wrapper).astext() == "content"
    assert _render_pane(wrapper).astext() == "content"


def test_subclass_numbering_seam(tmp_path: Path) -> None:
    """A ``format_title`` override can number examples per document."""
    (tmp_path / "conf.py").write_text(_SUBCLASS_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. numbered-example::

               first

            .. numbered-example:: Custom

               second
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    titles = [r.astext() for r in result.doctree().findall(nodes.rubric)]
    assert titles == ["Example 1", "Custom 2"]


def test_subclass_alt_output_seam(tmp_path: Path) -> None:
    """Overriding ``source_text`` and ``render_into`` decouples the shown
    source from the rendered output."""
    (tmp_path / "conf.py").write_text(_SUBCLASS_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. alt-example::

               ignored content
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert not result.stderr
    wrapper = _wrapper(result.doctree())
    assert _source_block(wrapper).astext() == "SHOWN SOURCE"
    assert _render_pane(wrapper).astext() == "RENDERED OUTPUT"


# --- node-factory seams ---------------------------------------------------

_FACTORY_CONF = CONF_CONTENT + dedent(
    '''
        from docutils import nodes
        from sphinx_syntax_example import SyntaxExampleDirective


        class DivExample(SyntaxExampleDirective):
            """A directive whose two containers are sphinx-design style divs.

            The factories set only the node type and its extra attributes; the
            classes are left to ``run``, as the documented contract says.
            """

            wrapper_classes = ("myst-example",)
            render_classes = ("myst-example-render",)

            def build_wrapper_node(self):
                return nodes.container(is_div=True, design_component="div")

            def build_render_node(self):
                return nodes.container(is_div=True, design_component="div")


        class PrestyledExample(SyntaxExampleDirective):
            """A directive whose factory seeds a class of its own."""

            def build_wrapper_node(self):
                return nodes.container(classes=["extra", "syntax-example"])


        def setup(app):
            app.add_directive("div-example", DivExample)
            app.add_directive("prestyled-example", PrestyledExample)
        '''
)


def _container_with_class(root: nodes.Element, class_: str) -> nodes.container:
    """Return the single container in ``root`` carrying ``class_``."""
    found = [c for c in root.findall(nodes.container) if class_ in c["classes"]]
    assert len(found) == 1, f"expected one .{class_} container, found {len(found)}"
    return found[0]


def test_node_factory_seams(tmp_path: Path) -> None:
    """``build_wrapper_node`` / ``build_render_node`` decide the node type and
    its extra attributes, so a subclass can emit sphinx-design ``is_div`` nodes
    (whose visitor omits the ``container`` class) without re-implementing
    ``run`` — and without restating the class attributes, which ``run`` applies
    to whatever the factories returned."""
    (tmp_path / "conf.py").write_text(_FACTORY_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. div-example::

               Some **bold** content.
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr

    doc = result.doctree()
    # the class attributes still reached both nodes, though neither factory
    # mentioned them — without this the block would render silently unstyled
    wrapper = _container_with_class(doc, "myst-example")
    render = _container_with_class(wrapper, "myst-example-render")

    # the attributes the sphinx-design container visitor keys off survive into
    # the doctree, on both nodes
    for node in (wrapper, render):
        assert node["is_div"] is True
        assert node["design_component"] == "div"

    # ``run`` still sets the source info on whatever the wrapper seam returned
    assert wrapper.source is not None
    assert wrapper.source.endswith("index.rst")
    assert wrapper.line is not None

    # and the parts are assembled into it exactly as before
    assert [r.astext() for r in wrapper.findall(nodes.rubric)] == ["Example"]
    assert _source_block(wrapper).astext() == "Some **bold** content."
    assert list(render.findall(nodes.strong))


def test_node_factory_classes_are_merged_not_replaced(tmp_path: Path) -> None:
    """A class the factory set is kept alongside the class attribute's, and a
    class named by both is not duplicated."""
    (tmp_path / "conf.py").write_text(_FACTORY_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. prestyled-example::

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert _wrapper(result.doctree())["classes"] == ["extra", "syntax-example"]


# --- lexer resolution -----------------------------------------------------

_LEXER_CONF = CONF_CONTENT + dedent(
    '''
        from pygments.lexers.markup import RstLexer


        class ProjectLexer(RstLexer):
            """A lexer that exists only for this project, as myst-parser's own
            documentation registers a local ``MystLexer``."""

            name = "ProjectLexer"
            aliases = []
            filenames = []
            mimetypes = []


        def setup(app):
            app.add_lexer("project-markup", ProjectLexer)
        '''
)


def test_app_registered_lexer_is_honoured(tmp_path: Path) -> None:
    """A lexer registered through ``app.add_lexer`` — invisible to Pygments'
    global registry — is accepted as a ``:highlight:`` value rather than
    silently falling back, and highlights cleanly under ``-W``."""
    from sphinx_syntax_example import _lexer_available

    # precondition: Pygments alone does not know this name
    assert not _lexer_available("project-markup")

    (tmp_path / "conf.py").write_text(_LEXER_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::
               :highlight: project-markup

               Some *project* markup.
            """
        )
    )
    # warningiserror=True: neither the directive's fallback note nor Sphinx's
    # own "Pygments lexer name is not known" warning may fire.
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert _source_block(_wrapper(result.doctree()))["language"] == "project-markup"


def test_pygments_only_lexer_is_honoured(tmp_path: Path) -> None:
    """A lexer only Pygments provides is honoured — the fallback arm of the
    probe, after the Sphinx registries have been consulted and missed.

    The precondition is asserted rather than assumed: were ``ruby`` ever to gain
    a Sphinx registration, this test would keep passing while silently no longer
    reaching the Pygments lookup at all, which is precisely how that arm went
    uncovered before.
    """
    assert "ruby" not in highlighting.lexer_classes
    assert "ruby" not in highlighting.lexers

    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::
               :highlight: ruby

               puts "hello"
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert _source_block(_wrapper(result.doctree()))["language"] == "ruby"


def test_sphinx_builtin_lexer_alias_is_honoured(tmp_path: Path) -> None:
    """Sphinx's own built-in aliases count as registered too, so ``none`` — a
    valid highlight language Pygments does not resolve — is honoured."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::
               :highlight: none

               content
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert _source_block(_wrapper(result.doctree()))["language"] == "none"


def test_app_registered_lexer_does_not_leak(tmp_path: Path) -> None:
    """The registry probe is read-only, and the previous test's registration is
    undone, so the name is unknown again outside that project.

    This is a canary for the ``_isolate_lexer_registries`` fixture, and is
    deliberately order-dependent: it is meaningful only when it runs after
    ``test_app_registered_lexer_is_honoured`` has registered the name, which
    file order gives us. Should it ever be run alone it passes vacuously —
    it is a guard against leakage, not a test of the probe.
    """
    from sphinx_syntax_example import _lexer_available

    assert not _lexer_available("project-markup")
    assert _lexer_available("python")


# --- the per-document numbering helper ------------------------------------

_COUNTER_CONF = CONF_CONTENT + dedent(
    '''
        from sphinx_syntax_example import SyntaxExampleDirective


        class CountedExample(SyntaxExampleDirective):
            """A directive numbering itself through the packaged helper."""

            def format_title(self, raw_title):
                return f"{raw_title or 'Example'} {self.per_document_number()}"


        def setup(app):
            app.add_directive("counted-example", CountedExample)
        '''
)


def test_per_document_number_counts_and_resets(tmp_path: Path) -> None:
    """``per_document_number`` counts from 1 within a document and starts over
    in the next one, because ``temp_data`` is per source file."""
    (tmp_path / "conf.py").write_text(_COUNTER_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. toctree::

               other

            .. counted-example::

               first

            .. counted-example:: Custom

               second
            """
        )
    )
    (tmp_path / "other.rst").write_text(
        dedent(
            """\
            Other
            =====

            .. counted-example::

               only
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == [
        "Example 1",
        "Custom 2",
    ]
    # the second document restarts at 1 rather than continuing at 3
    assert [r.astext() for r in result.doctree("other").findall(nodes.rubric)] == ["Example 1"]


def test_per_document_number_key_is_case_insensitive(tmp_path: Path) -> None:
    """reStructuredText directive names are case-insensitive, so two spellings
    of one directive share a counter rather than each starting at 1."""
    (tmp_path / "conf.py").write_text(_COUNTER_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. counted-example::

               first

            .. Counted-Example::

               second
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == [
        "Example 1",
        "Example 2",
    ]


# --- the string-markup parsing helper -------------------------------------

_ALT_MARKUP_CONF = CONF_CONTENT + dedent(
    r'''
        from docutils.parsers.rst import directives

        from sphinx_syntax_example import SyntaxExampleDirective

        ALT_MARKUP = "Alternative **output**.\n\n- one\n- two"


        class AltMarkupExample(SyntaxExampleDirective):
            """A directive that renders markup other than what it shows."""

            def source_text(self):
                return "SHOWN SOURCE"

            def render_into(self, container):
                self.nested_parse_text(ALT_MARKUP, container)


        class BrokenMarkupExample(SyntaxExampleDirective):
            """A directive whose alternative reStructuredText does not parse."""

            def render_into(self, container):
                self.nested_parse_text("A :no-such-role:`x` reference.", container)


        class BrokenMystMarkupExample(SyntaxExampleDirective):
            """A directive whose alternative MyST does not parse."""

            def render_into(self, container):
                self.nested_parse_text("A {no-such-role}`x` reference.", container)


        class AltOutputExample(SyntaxExampleDirective):
            """The ``:alt-output:`` recipe documented in the README, verbatim:
            an added option whose markup replaces the rendered output."""

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
            app.add_directive("alt-markup-example", AltMarkupExample)
            app.add_directive("broken-markup-example", BrokenMarkupExample)
            app.add_directive("broken-myst-markup-example", BrokenMystMarkupExample)
            app.add_directive("alt-output-example", AltOutputExample)
        '''
)


def _assert_alt_markup_rendered(result: BuildResult) -> None:
    """Assert the alternative markup — not the content — reached the doctree."""
    wrapper = _wrapper(result.doctree())
    assert _source_block(wrapper).astext() == "SHOWN SOURCE"
    render = _render_pane(wrapper)
    # the string was parsed as markup, not inserted as text
    assert [s.astext() for s in render.findall(nodes.strong)] == ["output"]
    bullets = list(render.findall(nodes.bullet_list))
    assert len(bullets) == 1
    assert [item.astext() for item in bullets[0].findall(nodes.list_item)] == ["one", "two"]


def test_nested_parse_text_in_rst(tmp_path: Path) -> None:
    """``nested_parse_text`` parses a string of markup into the render pane,
    using the host document's parser — reStructuredText here."""
    (tmp_path / "conf.py").write_text(_ALT_MARKUP_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. alt-markup-example::

               ignored content
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    _assert_alt_markup_rendered(result)


def test_nested_parse_text_in_myst(tmp_path: Path) -> None:
    """The same call in a MyST document parses the string as MyST, with no
    format sniffing in the helper — ``state.nested_parse`` carries the parser."""
    pytest.importorskip("myst_parser")
    (tmp_path / "conf.py").write_text(_ALT_MARKUP_CONF + "\nextensions.append('myst_parser')\n")
    (tmp_path / "index.md").write_text(
        dedent(
            """\
            # Test

            ```{alt-markup-example}
            ignored content
            ```
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    _assert_alt_markup_rendered(result)


def test_alt_output_option_recipe(tmp_path: Path) -> None:
    """The README's ``:alt-output:`` recipe works as printed: an extended
    ``option_spec``, the option's markup rendered in place of the content, and
    ``super().render_into`` still reached when the option is absent."""
    (tmp_path / "conf.py").write_text(_ALT_MARKUP_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. alt-output-example::
               :alt-output: Rendered **instead**.

               shown source

            .. alt-output-example::

               no option, so the content is rendered
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    panes = [
        (_source_block(w).astext(), _render_pane(w).astext())
        for w in result.doctree().findall(nodes.container)
        if "syntax-example" in w["classes"]
    ]
    assert panes == [
        ("shown source", "Rendered instead."),
        ("no option, so the content is rendered", "no option, so the content is rendered"),
    ]


def test_nested_parse_text_attributes_warnings(tmp_path: Path) -> None:
    """Warnings raised while parsing the string point into the directive — its
    own file, at its content offset — not at line 1 of an anonymous block."""
    (tmp_path / "conf.py").write_text(_ALT_MARKUP_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. broken-markup-example::

               ignored content
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert "no-such-role" in result.stderr
    # line 6 is the directive's content, three lines below the section title
    assert "index.rst:6:" in result.stderr


def test_nested_parse_text_attributes_warnings_in_myst(tmp_path: Path) -> None:
    """The same attribution holds on the MyST path, whose mocked state reads the
    offset relative to the directive rather than to the document.

    That is why ``content_offset`` and not ``lineno`` is the offset to pass: for
    this document the two are 0 and 5 here, against 5 and 4 in the equivalent
    reStructuredText one, so only ``content_offset`` is right in both frames of
    reference. (Since MyST's own value is 0 for a plain fence, this pins the
    ``lineno`` confusion rather than distinguishing 0 from ``content_offset``.)
    """
    pytest.importorskip("myst_parser")
    (tmp_path / "conf.py").write_text(_ALT_MARKUP_CONF + "\nextensions.append('myst_parser')\n")
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. toctree::

               page
            """
        )
    )
    # padded above the directive so a document-relative reading of the offset
    # could not coincide with the directive-relative one
    (tmp_path / "page.md").write_text(
        dedent(
            """\
            # Page

            some text

            ```{broken-myst-markup-example}
            ignored content
            ```
            """
        )
    )
    result = run_sphinxbuild(tmp_path)
    assert "no-such-role" in result.stderr
    # Line 6 is the directive's content, inside the fence opened on line 5. The
    # path is matched loosely because myst-parser 4.x reported it as
    # ``page.md.rst``; only the line number is this test's subject.
    assert re.search(r"page\.md(\.rst)?:6:", result.stderr)


# --- opt-in numbering (``syntax_example_numbering``) ----------------------

_NUMBERING_CONF = CONF_CONTENT + "\nsyntax_example_numbering = True\n"

_NUMBERING_SUBCLASS_CONF = _NUMBERING_CONF + dedent(
    '''
        from sphinx_syntax_example import SyntaxExampleDirective


        class NeedExample(SyntaxExampleDirective):
            """An alias with its own label, counted independently."""

            default_title = "Need example"


        class NoTitleExample(SyntaxExampleDirective):
            """An alias with no label for a number to decorate."""

            default_title = ""


        class OwnNumbering(SyntaxExampleDirective):
            """An alias that overrides ``format_title``, and so opts out."""

            def format_title(self, raw_title):
                return f"{raw_title or 'Example'} A"


        def setup(app):
            app.add_directive("need-example", NeedExample)
            app.add_directive("no-title-example", NoTitleExample)
            app.add_directive("own-numbering", OwnNumbering)
        '''
)


def test_numbering_disabled_by_default(tmp_path: Path) -> None:
    """Without the config value the titles are exactly the unnumbered ones."""
    (tmp_path / "conf.py").write_text(CONF_CONTENT)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::

               first

            .. syntax-example:: Custom

               second
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == ["Example", "Custom"]


def test_numbering_enabled(tmp_path: Path) -> None:
    """With ``syntax_example_numbering`` the default title becomes a numbered
    label, and an argument becomes its subtitle — sphinx-needs' shape."""
    (tmp_path / "conf.py").write_text(_NUMBERING_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::

               first

            .. syntax-example:: Custom

               second
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == [
        "Example 1",
        "Example 2: Custom",
    ]


def test_numbering_resets_per_document(tmp_path: Path) -> None:
    """The counter is per document, so a second document starts again at 1."""
    (tmp_path / "conf.py").write_text(_NUMBERING_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. toctree::

               other

            .. syntax-example::

               first

            .. syntax-example::

               second
            """
        )
    )
    (tmp_path / "other.rst").write_text(
        dedent(
            """\
            Other
            =====

            .. syntax-example::

               only
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == [
        "Example 1",
        "Example 2",
    ]
    assert [r.astext() for r in result.doctree("other").findall(nodes.rubric)] == ["Example 1"]


def test_numbering_alias_counts_independently(tmp_path: Path) -> None:
    """Each registered directive name gets its own counter, so an alias in the
    same document numbers from 1 rather than sharing the run."""
    (tmp_path / "conf.py").write_text(_NUMBERING_SUBCLASS_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. syntax-example::

               first

            .. need-example::

               aliased

            .. syntax-example::

               second
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == [
        "Example 1",
        "Need example 1",
        "Example 2",
    ]


def test_numbering_does_not_touch_an_overridden_format_title(tmp_path: Path) -> None:
    """A subclass that overrides ``format_title`` opts out of the config value
    entirely, rather than being numbered behind its own back."""
    (tmp_path / "conf.py").write_text(_NUMBERING_SUBCLASS_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. own-numbering::

               first

            .. own-numbering:: Custom

               second
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == [
        "Example A",
        "Custom A",
    ]


def test_numbering_leaves_a_labelless_subclass_alone(tmp_path: Path) -> None:
    """Numbering decorates a label, so an empty ``default_title`` is untouched:
    the title stays suppressed, or stays exactly the argument."""
    (tmp_path / "conf.py").write_text(_NUMBERING_SUBCLASS_CONF)
    (tmp_path / "index.rst").write_text(
        dedent(
            """\
            Test
            ====

            .. no-title-example::

               first

            .. no-title-example:: Custom

               second
            """
        )
    )
    result = run_sphinxbuild(tmp_path, warningiserror=True)
    assert not result.stderr
    assert [r.astext() for r in result.doctree().findall(nodes.rubric)] == ["Custom"]
