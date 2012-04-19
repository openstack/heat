=====================================
Heat Testing Infrastructure
=====================================

A note of clarification is in order, to help those who are new to testing in
Heat:

- actual unit tests are created in the "tests" directory;
- the "testing" directory is used to house the infrastructure needed to support
  testing in Heat.

This README file attempts to provide current and prospective contributors with
everything they need to know in order to start creating unit tests and
utilizing the convenience code provided in nova.testing.


Test Types: Unit vs. Functional vs. Integration
-----------------------------------------------

TBD

Writing Unit Tests
------------------

TBD

Using Fakes
~~~~~~~~~~~

TBD

test.TestCase
-------------
The TestCase class from heat.test (generally imported as test) will
automatically manage self.stubs using the stubout module and self.mox
using the mox module during the setUp step. They will automatically
verify and clean up during the tearDown step.

If using test.TestCase, calling the super class setUp is required and
calling the super class tearDown is required to be last if tearDown
is overriden.

Writing Functional Tests
------------------------

TBD

Writing Integration Tests
-------------------------

TBD

Tests and assertRaises
----------------------
When asserting that a test should raise an exception, test against the
most specific exception possible. An overly broad exception type (like
Exception) can mask errors in the unit test itself.

Example::
TBD
