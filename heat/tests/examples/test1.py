###
### an unparented test -- no encapsulating class, just any fn starting with
### 'test'.
## http://darcs.idyll.org/~t/projects/nose-demo/simple/tests/test_stuff.py.html
###

import sys
import nose
from nose.plugins.attrib import attr
from nose import with_setup

# module level


def setUp():
    print "test1 setup complete"


def tearDown():
    print "test1 teardown complete"


@with_setup(setUp, tearDown)  # test level
@attr(tag=['example', 'func'])
@attr(speed='fast')
def test_a():
    assert 'a' == 'a'
    print "assert a"


def test_b():
    assert 'b' == 'b'
    print "assert b"

if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
