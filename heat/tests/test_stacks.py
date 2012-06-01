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
from heat.engine import manager


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class stacksTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')

    def tearDown(self):
        self.m.UnsetStubs()
        print "stackTest teardown complete"

    # We use this in a number of tests so it's factored out here.
    def start_wordpress_stack(self, stack_name):
        f = open("%s/WordPress_Single_Instance_gold.template" % self.path)
        t = json.loads(f.read())
        f.close()
        params = {}
        parameters = {}
        t['Parameters']['KeyName']['Value'] = 'test'
        stack = parser.Stack(None, stack_name, t, 0, params)
        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        instances.Instance.nova().AndReturn(self.fc)
        instances.Instance.nova().AndReturn(self.fc)
        instances.Instance.nova().AndReturn(self.fc)
        instance = stack.resources['WebServer']
        instance.itype_oflavor['m1.large'] = 'm1.large'
        instance.calculate_properties()
        server_userdata = instance._build_userdata(
                                instance.properties['UserData'])
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(image=744, flavor=3, key_name='test',
                name='WebServer', security_groups=None,
                userdata=server_userdata).\
                AndReturn(self.fc.servers.list()[-1])
        return stack

    def test_wordpress_single_instance_stack_create(self):
        stack = self.start_wordpress_stack('test_stack')
        self.m.ReplayAll()
        stack.create_blocking()
        assert(stack.resources['WebServer'] is not None)
        assert(stack.resources['WebServer'].instance_id > 0)
        assert(stack.resources['WebServer'].ipaddress != '0.0.0.0')

    def test_wordpress_single_instance_stack_delete(self):
        stack = self.start_wordpress_stack('test_stack')
        self.m.ReplayAll()
        rt = {}
        rt['template'] = stack.t
        rt['stack_name'] = stack.name
        new_rt = db_api.raw_template_create(None, rt)
        s = {}
        s['name'] = stack.name
        s['raw_template_id'] = new_rt.id
        new_s = db_api.stack_create(None, s)
        stack.id = new_s.id
        pt = {}
        pt['template'] = stack.t
        pt['raw_template_id'] = new_rt.id
        new_pt = db_api.parsed_template_create(None, pt)
        stack.create_blocking()
        assert(stack.resources['WebServer'] is not None)
        assert(stack.resources['WebServer'].instance_id > 0)
        stack.delete_blocking()
        assert(stack.resources['WebServer'].state == 'DELETE_COMPLETE')
        assert(stack.t['stack_status'] == 'DELETE_COMPLETE')

    def test_stack_event_list(self):
        stack = self.start_wordpress_stack('test_event_list_stack')
        self.m.ReplayAll()
        rt = {}
        rt['template'] = stack.t
        rt['stack_name'] = stack.name
        new_rt = db_api.raw_template_create(None, rt)
        s = {}
        s['name'] = stack.name
        s['raw_template_id'] = new_rt.id
        new_s = db_api.stack_create(None, s)
        stack.id = new_s.id
        pt = {}
        pt['template'] = stack.t
        pt['raw_template_id'] = new_rt.id
        new_pt = db_api.parsed_template_create(None, pt)
        stack.create_blocking()
        assert(stack.resources['WebServer'] is not None)
        assert(stack.resources['WebServer'].instance_id > 0)

        m = manager.EngineManager()
        events = db_api.event_get_all_by_stack(None, stack.id)
        for ev in events:
            result = m.parse_event(ev)
            assert(result['EventId'] > 0)
            assert(result['StackName'] == "test_event_list_stack")
            # This is one of CREATE_COMPLETE or CREATE_IN_PROGRESS,
            # just did this to make it easy.
            assert(result['ResourceStatus'].find('CREATE') != -1)
            assert(result['ResourceType'] == 'AWS::EC2::Instance')
            assert(result['ResourceStatusReason'] == 'state changed')
            assert(result['LogicalResourceId'] == 'WebServer')
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            assert(result['ResourceProperties']['UserData'].find('wordpress')
                   != -1)
            assert(result['ResourceProperties']['ImageId']
                   == 'F16-x86_64-gold')
            assert(result['ResourceProperties']['InstanceType'] == 'm1.large')

    def test_stack_list(self):
        self.m.StubOutWithMock(manager.EngineManager, '_authenticate')
        manager.EngineManager._authenticate(None).AndReturn(True)
        stack = self.start_wordpress_stack('test_stack_list')
        rt = {}
        rt['template'] = stack.t
        rt['stack_name'] = stack.name
        new_rt = db_api.raw_template_create(None, rt)
        s = {}
        s['name'] = stack.name
        s['raw_template_id'] = new_rt.id
        new_s = db_api.stack_create(None, s)
        stack.id = new_s.id
        pt = {}
        pt['template'] = stack.t
        pt['raw_template_id'] = new_rt.id
        new_pt = db_api.parsed_template_create(None, pt)
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()
        stack.create_blocking()

        f = open("%s/WordPress_Single_Instance_gold.template" % self.path)
        t = json.loads(f.read())
        params = {}
        parameters = {}
        t['Parameters']['KeyName']['Value'] = 'test'
        stack = parser.Stack(None, 'test_stack_list', t, 0, params)

        man = manager.EngineManager()
        sl = man.list_stacks(None, params)

        assert(len(sl) > 0)
        for s in sl['stacks']:
            assert(s['stack_id'] > 0)
            assert(s['template_description'].find('WordPress') != -1)

    # allows testing of the test directly
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
