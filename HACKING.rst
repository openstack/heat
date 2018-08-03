Heat style commandments
=======================

- Step 1: Read the OpenStack style commandments
  https://docs.openstack.org/hacking/
- Step 2: Read on

Heat specific commandments
--------------------------

None so far

Creating unit tests
-------------------
For every new feature, unit tests should be created that both test and
(implicitly) document the usage of said features. If submitting a patch for a
bug that had no unit test, a new passing unit test should be added. If a
submitted bug fix does have a unit test, be sure to add a new one that fails
without the patch and passes with the patch.

For more information on creating unit tests and utilizing the testing
infrastructure in OpenStack Heat, please read heat/tests/testing-overview.txt.


Running tests
-------------
The testing system is based on a combination of tox and stestr. The canonical
approach to running tests is to simply run the command ``tox``. This will
create virtual environments, populate them with dependencies and run all of
the tests that OpenStack CI systems run. Behind the scenes, tox is running
``stestr run``, but is set up such that you can supply any additional
stestr arguments that are needed to tox. For example, you can run:
``tox -- --analyze-isolation`` to cause tox to tell stestr to add
``--analyze-isolation`` to its argument list.

It is also possible to run the tests inside of a virtual environment
you have created, or it is possible that you have all of the dependencies
installed locally already. In this case, you can interact with the ``stestr``
command directly. Running ``stestr run`` will run the entire test suite in
as many threads as you have CPU cores (this is the default incantation tox
uses), number of threads can be adjusted with ``--concurrency N`` argument.
``testr run --serial`` will run tests in serial process.
More information about stestr can be found at:
http://stestr.readthedocs.io

Note that unit tests use a database if available. See
``tools/test-setup.sh`` on how to set up the databases the same way as
done in the OpenStack CI systems.

Heat Specific Commandments
--------------------------

- [Heat301] Use LOG.warning() rather than LOG.warn().
- [Heat302] Python 3: do not use dict.iteritems.
- [Heat303] Python 3: do not use dict.iterkeys.
- [Heat304] Python 3: do not use dict.itervalues.

