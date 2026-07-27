sphinx-syntax-example
=====================

    A Sphinx extension adding the ``syntax-example`` directive,
    which shows a block of markup as both its raw source and its rendered result.

.. image:: https://img.shields.io/pypi/v/sphinx-syntax-example.svg
   :target: https://pypi.org/project/sphinx-syntax-example/
   :alt: PyPI

Installation
------------

Install the package and add ``sphinx_syntax_example`` to your ``conf.py`` extensions list.

.. code-block:: bash

    pip install sphinx-syntax-example

.. code-block:: python

    extensions = [
        ...
        "sphinx_syntax_example",
        ...
    ]

Usage
-----

Write a ``syntax-example`` directive with the markup you want to demonstrate as its content.
The directive renders it twice: a highlighted source pane, then the rendered result.

.. syntax-example::

    Some **reStructuredText** with a `link <https://www.sphinx-doc.org>`__.

An optional argument sets the title shown above the block (it defaults to ``Example``):

.. syntax-example:: A custom title

    A list rendered from its source:

    - one
    - two

Highlight language
------------------

The source pane's highlight language is inferred from the document's format.
Use the ``:highlight:`` option to override it, for example to show a code sample:

.. syntax-example::
    :highlight: python

    print("hello world")

A value naming a lexer registered with ``app.add_lexer`` — one that exists only
for your project, and so is invisible to Pygments' global registry — is
honoured too. An unknown value falls back to the inferred language,
so a strict ``-W`` build is never broken by a typo.

Numbering
---------

Titles are unnumbered by default. Set ``syntax_example_numbering = True`` in
``conf.py`` to make the default title a numbered label, with any argument
carried as a subtitle — ``Example 1``, then ``Example 2: A custom title``.

The counter restarts at 1 in each document, and each registered directive name
counts independently, so a downstream alias never shares the run. Numbering
only decorates a non-empty default title: a subclass whose ``default_title`` is
``""`` is unaffected by the config value.

Either way the extension keeps no cross-document state. The counter lives in
``env.temp_data``, which Sphinx replaces for each source file it reads — and a
document is exactly the unit of both parallel reading and incremental
rebuilding, so re-reading one changed file reproduces the numbers of a full
build and nothing crosses between parallel workers.

Subclassing
-----------

Downstream packages can subclass ``SyntaxExampleDirective`` to build an aliased
directive (for example one with its own numbering scheme, its own container
nodes, or no title), customising behaviour through the named seams
``format_title``, ``build_title_node``, ``build_wrapper_node``,
``build_render_node``, ``source_text``, ``render_into`` and
``default_language``, then registering the subclass under the alias name in
their own ``setup(app)``.

The ``wrapper_classes``, ``source_classes`` and ``render_classes`` attributes
stay the single source of the CSS classes: ``run`` applies them to whatever the
node-building seams returned, so those seams choose only the node type and its
extra attributes, and an override can neither repeat the classes nor drop them.

Two helpers exist for those overrides to call: ``per_document_number()``
returns the next number in the current document, and
``nested_parse_text(text, container)`` parses a string of markup into a node
using the host document's own parser.

See the module docstring for the full override surface.
