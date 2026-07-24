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

An unknown ``:highlight:`` value falls back to the inferred language,
so a strict ``-W`` build is never broken by a typo.

Subclassing
-----------

Downstream packages can subclass ``SyntaxExampleDirective`` to build an aliased
directive (for example one with auto-numbering, or no title), customising
behaviour through the named seams ``format_title``, ``build_title_node``,
``source_text``, ``render_into`` and ``default_language``,
then registering the subclass under the alias name in their own ``setup(app)``.
See the module docstring for the full override surface.
