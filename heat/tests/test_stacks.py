# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import sys
import os

import nose
import unittest
import mox
import json
import sqlalchemy
from nose.plugins.attrib import attr
from nose import with_setup

from heat.common import context
from heat.tests.v1_1 import fakes
from heat.engine import instance as instances
import heat.db as db_api
from heat.engine import parser
from heat.engine import manager
from heat.engine import auth


@attr(tag=['unit', 'resource'])
@attr(speed='slow')
class stacksTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()
        path = os.path.dirname(os.path.realpath(__file__))
        self.path = path.replace(os.path.join('heat', 'tests'), 'templates')

    def tearDown(self):
        self.m.UnsetStubs()
        print "stackTest teardown complete"

    def create_context(self, user='stacks_test_user'):
        ctx = context.get_admin_context()
        self.m.StubOutWithMock(ctx, 'username')
        ctx.username = user
        self.m.StubOutWithMock(auth, 'authenticate')
        return ctx

    # We use this in a number of tests so it's factored out here.
    def get_wordpress_stack(self, stack_name, ctx=None):
        tmpl_path = os.path.join(self.path,
                                 'WordPress_Single_Instance_gold.template')
        with open(tmpl_path) as f:
            t = json.load(f)

        template = parser.Template(t)
        parameters = parser.Parameters(stack_name, template,
                                       {'KeyName': 'test'})

        stack = parser.Stack(ctx or self.create_context(),
                             stack_name, template, parameters)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(self.fc)

        instance = stack.resources['WebServer']
        instance.itype_oflavor['m1.large'] = 'm1.large'
        instance.calculate_properties()
        server_userdata = instance._build_userdata(
                                instance.properties['UserData'])
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(image=744, flavor=3, key_name='test',
                name='WebServer', security_groups=None,
                userdata=server_userdata, scheduler_hints=None,
                meta=None).AndReturn(self.fc.servers.list()[-1])

        return stack

    def test_wordpress_single_instance_stack_create(self):
        stack = self.get_wordpress_stack('test_stack')
        self.m.ReplayAll()
        stack.create()

        self.assertNotEqual(stack.resources['WebServer'], None)
        self.assertTrue(stack.resources['WebServer'].instance_id > 0)
        self.assertNotEqual(stack.resources['WebServer'].ipaddress, '0.0.0.0')

    def test_wordpress_single_instance_stack_delete(self):
        ctx = self.create_context()
        stack = self.get_wordpress_stack('test_stack', ctx)
        self.m.ReplayAll()
        stack_id = stack.store()
        stack.create()

        db_s = db_api.stack_get(ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.assertNotEqual(stack.resources['WebServer'], None)
        self.assertTrue(stack.resources['WebServer'].instance_id > 0)

        stack.delete()

        self.assertEqual(stack.resources['WebServer'].state, 'DELETE_COMPLETE')
        self.assertEqual(db_api.stack_get(ctx, stack_id), None)
        self.assertEqual(db_s.status, 'DELETE_COMPLETE')

    def test_stack_event_list(self):
        stack = self.get_wordpress_stack('test_event_list_stack')
        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.assertNotEqual(stack.resources['WebServer'], None)
        self.assertTrue(stack.resources['WebServer'].instance_id > 0)

        m = manager.EngineManager()
        events = db_api.event_get_all_by_stack(None, stack.id)
        for ev in events:
            result = m.parse_event(ev)
            self.assertTrue(result['EventId'] > 0)
            self.assertEqual(result['StackName'], "test_event_list_stack")
            self.assertTrue(result['ResourceStatus'] in ('IN_PROGRESS',
                                                         'CREATE_COMPLETE'))
            self.assertEqual(result['ResourceType'], 'AWS::EC2::Instance')
            self.assertEqual(result['ResourceStatusReason'], 'state changed')
            self.assertEqual(result['LogicalResourceId'], 'WebServer')
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            user_data = result['ResourceProperties']['UserData']
            self.assertNotEqual(user_data.find('wordpress'), -1)
            self.assertEqual(result['ResourceProperties']['ImageId'],
                             'F16-x86_64-gold')
            self.assertEqual(result['ResourceProperties']['InstanceType'],
                             'm1.large')

    def test_stack_list(self):
        ctx = self.create_context()
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_list', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()
        sl = man.list_stacks(ctx, {})

        self.assertTrue(len(sl['stacks']) > 0)
        for s in sl['stacks']:
            self.assertTrue('CreationTime' in s)
            #self.assertTrue('LastUpdatedTime' in s)
            self.assertTrue('StackId' in s)
            self.assertNotEqual(s['StackId'], None)
            self.assertTrue('StackName' in s)
            self.assertTrue('StackStatus' in s)
            #self.assertTrue('StackStatusReason' in s)
            self.assertTrue('TemplateDescription' in s)
            self.assertNotEqual(s['TemplateDescription'].find('WordPress'), -1)

    def test_stack_describe_all(self):
        ctx = self.create_context('stack_describe_all')
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_desc_all', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()
        sl = man.show_stack(ctx, None, {})

        self.assertEqual(len(sl['stacks']), 1)
        for s in sl['stacks']:
            self.assertNotEqual(s['StackId'], None)
            self.assertNotEqual(s['Description'].find('WordPress'), -1)

    def test_stack_describe_all_empty(self):
        ctx = self.create_context('stack_describe_all_empty')
        auth.authenticate(ctx).AndReturn(True)

        self.m.ReplayAll()

        man = manager.EngineManager()
        sl = man.show_stack(ctx, None, {})

        self.assertEqual(len(sl['stacks']), 0)

    def test_stack_describe_nonexistent(self):
        ctx = self.create_context()
        auth.authenticate(ctx).AndReturn(True)

        self.m.ReplayAll()

        man = manager.EngineManager()
        sl = man.show_stack(ctx, 'wibble', {})

        self.assertEqual(len(sl['stacks']), 0)

    def test_stack_describe(self):
        ctx = self.create_context('stack_describe')
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_desc', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()
        sl = man.show_stack(ctx, 'test_stack_desc', {})

        self.assertEqual(len(sl['stacks']), 1)

        s = sl['stacks'][0]
        self.assertTrue('CreationTime' in s)
        #self.assertTrue('LastUpdatedTime' in s)
        self.assertTrue('StackId' in s)
        self.assertNotEqual(s['StackId'], None)
        self.assertTrue('StackName' in s)
        self.assertEqual(s['StackName'], 'test_stack_desc')
        self.assertTrue('StackStatus' in s)
        self.assertTrue('StackStatusReason' in s)
        self.assertTrue('Description' in s)
        self.assertNotEqual(s['Description'].find('WordPress'), -1)
        self.assertTrue('Parameters' in s)

    def test_stack_resource_describe(self):
        ctx = self.create_context('stack_res_describe')
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_res_desc', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()
        r = man.describe_stack_resource(ctx, 'test_stack_res_desc',
                                        'WebServer')

        #self.assertTrue('Description' in r)
        self.assertTrue('LastUpdatedTimestamp' in r)
        self.assertTrue('StackId' in r)
        self.assertNotEqual(r['StackId'], None)
        self.assertTrue('StackName' in r)
        self.assertEqual(r['StackName'], 'test_stack_res_desc')
        self.assertTrue('Metadata' in r)
        self.assertTrue('ResourceStatus' in r)
        self.assertTrue('ResourceStatusReason' in r)
        self.assertTrue('ResourceType' in r)
        self.assertTrue('PhysicalResourceId' in r)
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')

    def test_stack_resource_describe_nonexist_stack(self):
        ctx = self.create_context()
        auth.authenticate(ctx).AndReturn(True)

        man = manager.EngineManager()
        self.assertRaises(AttributeError,
                          man.describe_stack_resource,
                          ctx, 'foo', 'WebServer')

    def test_stack_resource_describe_nonexist_resource(self):
        ctx = self.create_context('stack_res_describe_bad_rsrc')
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_res_desc', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()

        self.assertRaises(AttributeError,
                          man.describe_stack_resource,
                          ctx, 'test_stack_res_desc', 'foo')

    def test_stack_resources_describe(self):
        ctx = self.create_context('stack_res_describe')
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_ress_desc', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()
        resources = man.describe_stack_resources(ctx, 'test_stack_ress_desc',
                                                 None, 'WebServer')

        self.assertEqual(len(resources), 1)
        r = resources[0]
        #self.assertTrue('Description' in r)
        self.assertTrue('Timestamp' in r)
        self.assertTrue('StackId' in r)
        self.assertNotEqual(r['StackId'], None)
        self.assertTrue('StackName' in r)
        self.assertEqual(r['StackName'], 'test_stack_ress_desc')
        self.assertTrue('ResourceStatus' in r)
        self.assertTrue('ResourceStatusReason' in r)
        self.assertTrue('ResourceType' in r)
        self.assertTrue('PhysicalResourceId' in r)
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')

    def test_stack_resources_describe_no_filter(self):
        ctx = self.create_context('stack_res_describe_nf')
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_ress_desc_nf', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()
        resources = man.describe_stack_resources(ctx,
                                                 'test_stack_ress_desc_nf',
                                                 None, None)

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')

    def test_stack_resources_describe_bad_lookup(self):
        ctx = self.create_context()
        auth.authenticate(ctx).AndReturn(True)

        man = manager.EngineManager()
        self.assertRaises(AttributeError,
                          man.describe_stack_resources,
                          ctx, None, None, 'WebServer')

    def test_stack_resources_describe_nonexist_stack(self):
        ctx = self.create_context()
        auth.authenticate(ctx).AndReturn(True)

        man = manager.EngineManager()
        self.assertRaises(AttributeError,
                          man.describe_stack_resources,
                          ctx, 'foo', None, 'WebServer')

    def test_stack_resources_describe_nonexist_physid(self):
        ctx = self.create_context()
        auth.authenticate(ctx).AndReturn(True)

        man = manager.EngineManager()
        self.assertRaises(AttributeError,
                          man.describe_stack_resources,
                          ctx, None, 'foo', 'WebServer')

    def test_stack_resources_list(self):
        ctx = self.create_context('stack_res_describe')
        auth.authenticate(ctx).AndReturn(True)

        stack = self.get_wordpress_stack('test_stack_ress_list', ctx)

        self.m.ReplayAll()
        stack.store()
        stack.create()

        man = manager.EngineManager()
        resources = man.list_stack_resources(ctx, 'test_stack_ress_list')

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('LastUpdatedTimestamp' in r)
        self.assertTrue('PhysicalResourceId' in r)
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')
        self.assertTrue('ResourceStatus' in r)
        #self.assertTrue('ResourceStatusReason' in r)
        self.assertTrue('ResourceType' in r)

    def test_stack_resources_list_nonexist_stack(self):
        ctx = self.create_context()
        auth.authenticate(ctx).AndReturn(True)

        man = manager.EngineManager()
        self.assertRaises(AttributeError,
                          man.list_stack_resources,
                          ctx, 'foo')


# allows testing of the test directly
if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
