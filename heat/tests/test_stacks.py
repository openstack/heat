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


tests_dir = os.path.dirname(os.path.realpath(__file__))
templates_dir = os.path.normpath(os.path.join(tests_dir,
                                              os.path.pardir, os.path.pardir,
                                              'templates'))


def create_context(mocks, user='stacks_test_user', ctx=None):
    ctx = ctx or context.get_admin_context()
    mocks.StubOutWithMock(ctx, 'username')
    ctx.username = user
    mocks.StubOutWithMock(auth, 'authenticate')
    return ctx


def get_wordpress_stack(stack_name, ctx):
    tmpl_path = os.path.join(templates_dir,
                             'WordPress_Single_Instance_gold.template')
    with open(tmpl_path) as f:
        t = json.load(f)

    template = parser.Template(t)
    parameters = parser.Parameters(stack_name, template,
                                   {'KeyName': 'test'})

    stack = parser.Stack(ctx, stack_name, template, parameters)

    return stack


def setup_mocks(mocks, stack):
    fc = fakes.FakeClient()
    mocks.StubOutWithMock(instances.Instance, 'nova')
    instances.Instance.nova().MultipleTimes().AndReturn(fc)

    instance = stack.resources['WebServer']
    instance.itype_oflavor['m1.large'] = 'm1.large'
    instance.calculate_properties()
    server_userdata = instance._build_userdata(instance.properties['UserData'])
    mocks.StubOutWithMock(fc.servers, 'create')
    fc.servers.create(image=744, flavor=3, key_name='test',
                      name='WebServer', security_groups=None,
                      userdata=server_userdata, scheduler_hints=None,
                      meta=None).AndReturn(fc.servers.list()[-1])


@attr(tag=['unit', 'stack'])
@attr(speed='slow')
class stackCreateTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()

    def tearDown(self):
        self.m.UnsetStubs()
        print "stackTest teardown complete"

    def test_wordpress_single_instance_stack_create(self):
        stack = get_wordpress_stack('test_stack', create_context(self.m))
        setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.assertNotEqual(stack.resources['WebServer'], None)
        self.assertTrue(stack.resources['WebServer'].instance_id > 0)
        self.assertNotEqual(stack.resources['WebServer'].ipaddress, '0.0.0.0')

    def test_wordpress_single_instance_stack_delete(self):
        ctx = create_context(self.m, 'test_delete_user')
        stack = get_wordpress_stack('test_stack', ctx)
        setup_mocks(self.m, stack)
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


@attr(tag=['unit', 'engine-api', 'engine-manager'])
@attr(speed='fast')
class stackManagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = mox.Mox()
        cls.username = 'stack_manager_test_user'
        ctx = create_context(m, cls.username)
        cls.stack_name = 'manager_test_stack'

        stack = get_wordpress_stack(cls.stack_name, ctx)
        setup_mocks(m, stack)
        m.ReplayAll()

        stack.store()
        stack.create()
        cls.stack = stack

        m.UnsetStubs()

    @classmethod
    def tearDownClass(cls):
        cls = cls
        m = mox.Mox()
        create_context(m, cls.username, ctx=cls.stack.context)
        setup_mocks(m, cls.stack)
        m.ReplayAll()

        cls.stack.delete()

        m.UnsetStubs()

    def setUp(self):
        self.m = mox.Mox()
        self.ctx = create_context(self.m, self.username)
        auth.authenticate(self.ctx).AndReturn(True)
        setup_mocks(self.m, self.stack)
        self.m.ReplayAll()

        self.man = manager.EngineManager()

    def tearDown(self):
        self.m.UnsetStubs()

    def test_stack_event_list(self):
        el = self.man.list_events(self.ctx, self.stack_name, {})

        self.assertTrue('events' in el)
        events = el['events']

        self.assertEqual(len(events), 2)
        for ev in events:
            self.assertTrue('EventId' in ev)
            self.assertTrue(ev['EventId'] > 0)

            self.assertTrue('LogicalResourceId' in ev)
            self.assertEqual(ev['LogicalResourceId'], 'WebServer')

            self.assertTrue('PhysicalResourceId' in ev)

            self.assertTrue('ResourceProperties' in ev)
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            user_data = ev['ResourceProperties']['UserData']
            self.assertNotEqual(user_data.find('wordpress'), -1)
            self.assertEqual(ev['ResourceProperties']['ImageId'],
                             'F16-x86_64-gold')
            self.assertEqual(ev['ResourceProperties']['InstanceType'],
                             'm1.large')

            self.assertTrue('ResourceStatus' in ev)
            self.assertTrue(ev['ResourceStatus'] in ('IN_PROGRESS',
                                                     'CREATE_COMPLETE'))

            self.assertTrue('ResourceStatusReason' in ev)
            self.assertEqual(ev['ResourceStatusReason'], 'state changed')

            self.assertTrue('ResourceType' in ev)
            self.assertEqual(ev['ResourceType'], 'AWS::EC2::Instance')

            self.assertTrue('StackId' in ev)

            self.assertTrue('StackName' in ev)
            self.assertEqual(ev['StackName'], self.stack_name)

            self.assertTrue('Timestamp' in ev)

    def test_stack_list(self):
        sl = self.man.list_stacks(self.ctx, {})

        self.assertTrue(len(sl['stacks']) > 0)
        for s in sl['stacks']:
            self.assertTrue('CreationTime' in s)
            self.assertTrue('LastUpdatedTime' in s)
            self.assertTrue('StackId' in s)
            self.assertNotEqual(s['StackId'], None)
            self.assertTrue('StackName' in s)
            self.assertTrue('StackStatus' in s)
            self.assertTrue('StackStatusReason' in s)
            self.assertTrue('TemplateDescription' in s)
            self.assertNotEqual(s['TemplateDescription'].find('WordPress'), -1)

    def test_stack_describe_all(self):
        sl = self.man.show_stack(self.ctx, None, {})

        self.assertEqual(len(sl['stacks']), 1)
        for s in sl['stacks']:
            self.assertNotEqual(s['StackId'], None)
            self.assertNotEqual(s['Description'].find('WordPress'), -1)

    def test_stack_describe_all_empty(self):
        self.tearDown()
        self.username = 'stack_describe_all_empty_user'
        self.setUp()

        sl = self.man.show_stack(self.ctx, None, {})

        self.assertEqual(len(sl['stacks']), 0)

    def test_stack_describe_nonexistent(self):
        self.assertRaises(AttributeError,
                          self.man.show_stack,
                          self.ctx, 'wibble', {})

    def test_stack_describe(self):
        sl = self.man.show_stack(self.ctx, self.stack_name, {})

        self.assertEqual(len(sl['stacks']), 1)

        s = sl['stacks'][0]
        self.assertTrue('CreationTime' in s)
        self.assertTrue('LastUpdatedTime' in s)
        self.assertTrue('StackId' in s)
        self.assertNotEqual(s['StackId'], None)
        self.assertTrue('StackName' in s)
        self.assertEqual(s['StackName'], self.stack_name)
        self.assertTrue('StackStatus' in s)
        self.assertTrue('StackStatusReason' in s)
        self.assertTrue('Description' in s)
        self.assertNotEqual(s['Description'].find('WordPress'), -1)
        self.assertTrue('Parameters' in s)

    def test_stack_resource_describe(self):
        r = self.man.describe_stack_resource(self.ctx, self.stack_name,
                                             'WebServer')

        self.assertTrue('Description' in r)
        self.assertTrue('LastUpdatedTimestamp' in r)
        self.assertTrue('StackId' in r)
        self.assertNotEqual(r['StackId'], None)
        self.assertTrue('StackName' in r)
        self.assertEqual(r['StackName'], self.stack_name)
        self.assertTrue('Metadata' in r)
        self.assertTrue('ResourceStatus' in r)
        self.assertTrue('ResourceStatusReason' in r)
        self.assertTrue('ResourceType' in r)
        self.assertTrue('PhysicalResourceId' in r)
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')

    def test_stack_resource_describe_nonexist_stack(self):
        self.assertRaises(AttributeError,
                          self.man.describe_stack_resource,
                          self.ctx, 'foo', 'WebServer')

    def test_stack_resource_describe_nonexist_resource(self):
        self.assertRaises(AttributeError,
                          self.man.describe_stack_resource,
                          self.ctx, self.stack_name, 'foo')

    def test_stack_resources_describe(self):
        resources = self.man.describe_stack_resources(self.ctx,
                                                      self.stack_name,
                                                      None, 'WebServer')

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('Description' in r)
        self.assertTrue('Timestamp' in r)
        self.assertTrue('StackId' in r)
        self.assertNotEqual(r['StackId'], None)
        self.assertTrue('StackName' in r)
        self.assertEqual(r['StackName'], self.stack_name)
        self.assertTrue('ResourceStatus' in r)
        self.assertTrue('ResourceStatusReason' in r)
        self.assertTrue('ResourceType' in r)
        self.assertTrue('PhysicalResourceId' in r)
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')

    def test_stack_resources_describe_no_filter(self):
        resources = self.man.describe_stack_resources(self.ctx,
                                                 self.stack_name,
                                                 None, None)

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')

    def test_stack_resources_describe_bad_lookup(self):
        self.assertRaises(AttributeError,
                          self.man.describe_stack_resources,
                          self.ctx, None, None, 'WebServer')

    def test_stack_resources_describe_nonexist_stack(self):
        self.assertRaises(AttributeError,
                          self.man.describe_stack_resources,
                          self.ctx, 'foo', None, 'WebServer')

    def test_stack_resources_describe_nonexist_physid(self):
        self.assertRaises(AttributeError,
                          self.man.describe_stack_resources,
                          self.ctx, None, 'foo', 'WebServer')

    def test_stack_resources_list(self):
        resources = self.man.list_stack_resources(self.ctx, self.stack_name)

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('LastUpdatedTimestamp' in r)
        self.assertTrue('PhysicalResourceId' in r)
        self.assertTrue('LogicalResourceId' in r)
        self.assertEqual(r['LogicalResourceId'], 'WebServer')
        self.assertTrue('ResourceStatus' in r)
        self.assertTrue('ResourceStatusReason' in r)
        self.assertTrue('ResourceType' in r)

    def test_stack_resources_list_nonexist_stack(self):
        self.assertRaises(AttributeError,
                          self.man.list_stack_resources,
                          self.ctx, 'foo')


# allows testing of the test directly
if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
