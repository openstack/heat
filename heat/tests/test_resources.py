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
from heat.engine import resources
from heat.engine import instance
import heat.db as db_api
from heat.engine import parser


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class ResourcesTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()

    def tearDown(self):
        self.m.UnsetStubs()
        print "ResourcesTest teardown complete"

    def test_initialize_instance_from_template(self):
        f = open('../../templates/WordPress_Single_Instance_gold.template')
        t = json.loads(f.read())
        f.close()

        params = {}
        parameters = {}
        params['KeyStoneCreds'] = None
        t['Parameters']['KeyName']['Value'] = 'test'
        stack = parser.Stack('test_stack', t, 0, params)

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',\
                                              stack).AndReturn(None)

        self.m.StubOutWithMock(instance.Instance, 'nova')
        instance.Instance.nova().AndReturn(self.fc)
        instance.Instance.nova().AndReturn(self.fc)
        instance.Instance.nova().AndReturn(self.fc)
        instance.Instance.nova().AndReturn(self.fc)

        #Need to find an easier way
        userdata = t['Resources']['WebServer']['Properties']['UserData']

        self.m.ReplayAll()

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        inst = instance.Instance('test_resource_name',\
                                 t['Resources']['WebServer'], stack)

        server_userdata = inst._build_userdata(json.dumps(userdata))
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(image=1, flavor=1, key_name='test',\
                name='test_resource_name', security_groups=None,\
                userdata=server_userdata).\
                AndReturn(self.fc.servers.list()[1])
        self.m.ReplayAll()

        inst.itype_oflavor['256 MB Server'] = '256 MB Server'
        inst.create()

        self.m.ReplayAll()

        inst.itype_oflavor['256 MB Server'] = '256 MB Server'
        inst.create()

        # this makes sure the auto increment worked on instance creation
        assert(inst.id > 0)

    def test_initialize_instance_from_template_and_delete(self):
        f = open('../../templates/WordPress_Single_Instance_gold.template')
        t = json.loads(f.read())
        f.close()

        params = {}
        parameters = {}
        params['KeyStoneCreds'] = None
        t['Parameters']['KeyName']['Value'] = 'test'
        stack = parser.Stack('test_stack', t, 0, params)

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',\
                                              stack).AndReturn(None)

        self.m.StubOutWithMock(instance.Instance, 'nova')
        instance.Instance.nova().AndReturn(self.fc)
        instance.Instance.nova().AndReturn(self.fc)
        instance.Instance.nova().AndReturn(self.fc)
        instance.Instance.nova().AndReturn(self.fc)

        #Need to find an easier way
        userdata = t['Resources']['WebServer']['Properties']['UserData']

        self.m.ReplayAll()

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        inst = instance.Instance('test_resource_name',\
                                 t['Resources']['WebServer'], stack)

        server_userdata = inst._build_userdata(json.dumps(userdata))
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(image=1, flavor=1, key_name='test',\
                name='test_resource_name', security_groups=None,\
                userdata=server_userdata).\
                AndReturn(self.fc.servers.list()[1])
        self.m.ReplayAll()

        inst.itype_oflavor['256 MB Server'] = '256 MB Server'
        inst.create()

        self.m.ReplayAll()

        inst.instance_id = 1234
        inst.itype_oflavor['256 MB Server'] = '256 MB Server'
        inst.create()

        inst.delete()
        assert(inst.instance_id == None)
        assert(inst.state == inst.DELETE_COMPLETE)

   # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
