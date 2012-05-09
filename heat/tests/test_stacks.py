import sys
import os

import nose
import unittest
import mox
import json
import sqlalchemy

from nose.plugins.attrib import attr
from nose import with_setup

from heat.tests.v1_1 import fakes
from heat.engine import instance as instances
import heat.db as db_api
from heat.engine import parser

@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class instancesTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()

    def tearDown(self):
        self.m.UnsetStubs()
        print "instancesTest teardown complete"

    def test_wordpress_single_instance_stack_create(self):
        f = open('../../templates/WordPress_Single_Instance_gold.template')
        t = json.loads(f.read())
        f.close()

        params = {}
        parameters = {}
        params['KeyStoneCreds'] = None
        t['Parameters']['KeyName']['Value'] = 'test'
        stack = parser.Stack('test_stack', t, 0, params)
        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        instances.Instance.nova().AndReturn(self.fc)
        instances.Instance.nova().AndReturn(self.fc)
        instances.Instance.nova().AndReturn(self.fc)
 
        #instance = instances.Instance('WebServer',\
        #                              t['Resources']['WebServer'], stack)
        instance = stack.resources['WebServer']
        instance.itype_oflavor['m1.large'] = 'm1.large'
        instance.stack.resolve_attributes(instance.t)
        instance.stack.resolve_joins(instance.t)
        instance.stack.resolve_base64(instance.t)
       
        server_userdata = instance._build_userdata(\
                                instance.t['Properties']['UserData'])
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(image=744, flavor=3, key_name='test',\
                name='WebServer', security_groups=None,\
                userdata=server_userdata).\
                AndReturn(self.fc.servers.list()[1])
        self.m.ReplayAll()

        stack.create_blocking()
        assert(stack.resources['WebServer'] != None)
        assert(stack.resources['WebServer'].instance_id > 0)
        assert(stack.resources['WebServer'].ipaddress != '0.0.0.0')
    
    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
