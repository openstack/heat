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


def create_context(mocks, user='stacks_test_user',
                   tenant='test_admin', ctx=None):
    ctx = ctx or context.get_admin_context()
    mocks.StubOutWithMock(ctx, 'username')
    mocks.StubOutWithMock(ctx, 'tenant')
    ctx.username = user
    ctx.tenant = tenant
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
        ctx = create_context(self.m, tenant='test_delete_tenant')
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
        cls.tenant = 'stack_manager_test_tenant'
        ctx = create_context(m, cls.username, cls.tenant)
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
        create_context(m, cls.username, cls.tenant, ctx=cls.stack.context)
        setup_mocks(m, cls.stack)
        m.ReplayAll()

        cls.stack.delete()

        m.UnsetStubs()

    def setUp(self):
        self.m = mox.Mox()
        self.ctx = create_context(self.m, self.username, self.tenant)
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
            self.assertTrue('event_id' in ev)
            self.assertTrue(ev['event_id'] > 0)

            self.assertTrue('logical_resource_id' in ev)
            self.assertEqual(ev['logical_resource_id'], 'WebServer')

            self.assertTrue('physical_resource_id' in ev)

            self.assertTrue('resource_properties' in ev)
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            user_data = ev['resource_properties']['UserData']
            self.assertNotEqual(user_data.find('wordpress'), -1)
            self.assertEqual(ev['resource_properties']['ImageId'],
                             'F16-x86_64-gold')
            self.assertEqual(ev['resource_properties']['InstanceType'],
                             'm1.large')

            self.assertTrue('resource_status' in ev)
            self.assertTrue(ev['resource_status'] in ('IN_PROGRESS',
                                                     'CREATE_COMPLETE'))

            self.assertTrue('resource_status_reason' in ev)
            self.assertEqual(ev['resource_status_reason'], 'state changed')

            self.assertTrue('resource_type' in ev)
            self.assertEqual(ev['resource_type'], 'AWS::EC2::Instance')

            self.assertTrue('stack_id' in ev)

            self.assertTrue('stack_name' in ev)
            self.assertEqual(ev['stack_name'], self.stack_name)

            self.assertTrue('event_time' in ev)

    def test_stack_describe_all(self):
        sl = self.man.show_stack(self.ctx, None, {})

        self.assertEqual(len(sl['stacks']), 1)
        for s in sl['stacks']:
            self.assertNotEqual(s['stack_id'], None)
            self.assertNotEqual(s['description'].find('WordPress'), -1)

    def test_stack_describe_all_empty(self):
        self.tearDown()
        self.tenant = 'stack_describe_all_empty_tenant'
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
        self.assertTrue('creation_time' in s)
        self.assertTrue('updated_time' in s)
        self.assertTrue('stack_id' in s)
        self.assertNotEqual(s['stack_id'], None)
        self.assertTrue('stack_name' in s)
        self.assertEqual(s['stack_name'], self.stack_name)
        self.assertTrue('stack_status' in s)
        self.assertTrue('stack_status_reason' in s)
        self.assertTrue('description' in s)
        self.assertNotEqual(s['description'].find('WordPress'), -1)
        self.assertTrue('parameters' in s)

    def test_stack_resource_describe(self):
        r = self.man.describe_stack_resource(self.ctx, self.stack_name,
                                             'WebServer')

        self.assertTrue('description' in r)
        self.assertTrue('updated_time' in r)
        self.assertTrue('stack_id' in r)
        self.assertNotEqual(r['stack_id'], None)
        self.assertTrue('stack_name' in r)
        self.assertEqual(r['stack_name'], self.stack_name)
        self.assertTrue('metadata' in r)
        self.assertTrue('resource_status' in r)
        self.assertTrue('resource_status_reason' in r)
        self.assertTrue('resource_type' in r)
        self.assertTrue('physical_resource_id' in r)
        self.assertTrue('logical_resource_id' in r)
        self.assertEqual(r['logical_resource_id'], 'WebServer')

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
        self.assertTrue('description' in r)
        self.assertTrue('updated_time' in r)
        self.assertTrue('stack_id' in r)
        self.assertNotEqual(r['stack_id'], None)
        self.assertTrue('stack_name' in r)
        self.assertEqual(r['stack_name'], self.stack_name)
        self.assertTrue('resource_status' in r)
        self.assertTrue('resource_status_reason' in r)
        self.assertTrue('resource_type' in r)
        self.assertTrue('physical_resource_id' in r)
        self.assertTrue('logical_resource_id' in r)
        self.assertEqual(r['logical_resource_id'], 'WebServer')

    def test_stack_resources_describe_no_filter(self):
        resources = self.man.describe_stack_resources(self.ctx,
                                                 self.stack_name,
                                                 None, None)

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('logical_resource_id' in r)
        self.assertEqual(r['logical_resource_id'], 'WebServer')

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
        self.assertTrue('updated_time' in r)
        self.assertTrue('physical_resource_id' in r)
        self.assertTrue('logical_resource_id' in r)
        self.assertEqual(r['logical_resource_id'], 'WebServer')
        self.assertTrue('resource_status' in r)
        self.assertTrue('resource_status_reason' in r)
        self.assertTrue('resource_type' in r)

    def test_stack_resources_list_nonexist_stack(self):
        self.assertRaises(AttributeError,
                          self.man.list_stack_resources,
                          self.ctx, 'foo')

    def test_metadata(self):
        err, metadata = self.man.metadata_get_resource(None,
                                                       self.stack_name,
                                                       'WebServer')
        self.assertEqual(err, None)
        self.assertTrue('AWS::CloudFormation::Init' in metadata)

        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        err, result = self.man.metadata_update(None,
                                               self.stack.id, 'WebServer',
                                               test_metadata)
        self.assertEqual(err, None)
        self.assertEqual(result, test_metadata)

        err, metadata = self.man.metadata_get_resource(None,
                                                       self.stack_name,
                                                       'WebServer')
        self.assertEqual(err, None)
        self.assertFalse('AWS::CloudFormation::Init' in metadata)
        self.assertEqual(metadata, test_metadata)

# allows testing of the test directly
if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
