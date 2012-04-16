###
### non-unittest derived test -- class is instantiated, then functions
### starting with 'test' are executed.
### http://darcs.idyll.org/~t/projects/nose-demo/simple/tests/test_stuff.py.html
###

import sys
import nose
from nose.plugins.attrib import attr

# sets attribute on all test methods


@attr(tag=['example', 'class'])
@attr(speed='fast')
class TestClass:
    def test2(self):
        assert 'b' == 'b'
        print "assert b"

    def setUp(self):
        print "test2 setup complete"

    def tearDown(self):
        print "test2 teardown complete"


if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
