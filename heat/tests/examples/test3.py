###
### the standard unittest-derived test
### http://darcs.idyll.org/~t/projects/nose-demo/simple/tests/test_stuff.py.html
###

import sys
import nose
import unittest
from nose.plugins.attrib import attr

# sets attribute on all test methods
@attr(tag=['example', 'unittest'])
@attr(speed='fast')
class ExampleTest(unittest.TestCase):
    def test_a(self):
        self.assert_(1 == 1)
    def setUp(self):
        print "test3 setup complete"
    def tearDown(self):
        print "test3 teardown complete"


if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
