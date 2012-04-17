import sys

import os
import nose
import unittest
import mox
from nose.plugins.attrib import attr
from nose import with_setup
from tests.v1_1 import fakes
from heat.engine import resources
from heat.common import config
import heat.db as db_api

@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class ResourcesTest(unittest.TestCase):
    _mox = None

    def setUp(self):
        cs = fakes.FakeClient()
        self._mox = mox.Mox()
        sql_connection = 'sqlite://heat.db'
        conf = config.HeatEngineConfigOpts()
        db_api.configure(conf)

    def tearDown(self):
        print "ResourcesTest teardown complete"

    def test_initialize_resource_from_template(self):
        f = open('templates/WordPress_Single_Instance_gold.template')
        t = f.read()
        f.close()

        stack = self._mox.CreateMockAnything()
        stack.id().AndReturn(1)
        
        self._mox.StubOutWithMock(stack, 'resolve_static_refs')
        stack.resolve_static_refs(t).AndReturn(t)
        
        self._mox.StubOutWithMock(stack, 'resolve_find_in_map')
        stack.resolve_find_in_map(t).AndReturn(t)

        self._mox.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name', stack).AndReturn(None)

        self._mox.ReplayAll()
        resource = resources.Resource('test_resource_name', t, stack)

        assert isinstance(resource, resources.Resource)

    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
   
