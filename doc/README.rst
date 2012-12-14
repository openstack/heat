===========================
Building the developer docs
===========================

For user and admin docs, go to the directory `doc/docbkx`.

Dependencies
============

Sphinx_
  You'll need sphinx (the python one) and if you are
  using the virtualenv you'll need to install it in the virtualenv
  specifically so that it can load the cinder modules.

  ::

    sudo yum install python-sphinx
    sudo pip-python install sphinxcontrib-httpdomain

Use `make`
==========

Just type make::

  make

Look in the Makefile for more targets.

To build the man pages:

  make man

To build the developer documentation as HTML:

  make html