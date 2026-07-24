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

from io import StringIO
from pathlib import Path
import pickle
import shutil
import sys
from textwrap import dedent
from types import SimpleNamespace

from docutils import nodes
import pytest
from sphinx.application import Sphinx
from sphinx.util.docutils import docutils_namespace, patch_docutils

from sphinx_syntax_example import SyntaxExampleDirective


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


def test_markdown_source_detection(tmp_path: Path) -> None:
    """In a MyST Markdown document the source pane uses a Markdown-family
    lexer, inferred from the ``.md`` source suffix."""
    myst = pytest.importorskip("myst_parser")
    assert myst  # imported for its side effect of being installable
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
                meta = self.env.metadata[self.env.docname]
                number = meta.setdefault("_ex_number", 1)
                meta["_ex_number"] = number + 1
                return f"{raw_title or 'Example'} {number}"


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
    # the source and render panes are still present
    assert _source_block(wrapper).astext() == "content"
    assert _render_pane(wrapper) is not None


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
