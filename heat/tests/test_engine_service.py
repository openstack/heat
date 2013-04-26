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


import os
import json

import mox
from oslo.config import cfg

from heat.common import context
from heat.common import exception
from heat.tests.v1_1 import fakes
import heat.engine.api as engine_api
import heat.db.api as db_api
from heat.common import identifier
from heat.common import template_format
from heat.engine import parser
from heat.engine import service
from heat.engine.properties import Properties
from heat.engine.resources import instance as instances
from heat.engine import watchrule
from heat.openstack.common import threadgroup
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db


tests_dir = os.path.dirname(os.path.realpath(__file__))
templates_dir = os.path.normpath(os.path.join(tests_dir,
                                              os.path.pardir, os.path.pardir,
                                              'templates'))


def create_context(mocks, user='stacks_test_user',
                   tenant='test_admin', ctx=None):
    ctx = ctx or context.get_admin_context()
    mocks.StubOutWithMock(ctx, 'username')
    mocks.StubOutWithMock(ctx, 'tenant_id')
    ctx.username = user
    ctx.tenant_id = tenant
    return ctx


def get_wordpress_stack(stack_name, ctx):
    tmpl_path = os.path.join(templates_dir,
                             'WordPress_Single_Instance_gold.template')
    with open(tmpl_path) as f:
        t = template_format.parse(f.read())

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
    server_userdata = instance._build_userdata(instance.properties['UserData'])
    mocks.StubOutWithMock(fc.servers, 'create')
    fc.servers.create(image=744, flavor=3, key_name='test',
                      name='%s.WebServer' % stack.name, security_groups=None,
                      userdata=server_userdata, scheduler_hints=None,
                      meta=None, nics=None,
                      availability_zone=None).AndReturn(
                          fc.servers.list()[-1])
    return fc


class DummyThreadGroup(object):
    def __init__(self):
        self.threads = []

    def add_timer(self, interval, callback, initial_delay=None,
                  *args, **kwargs):
        pass

    def add_thread(self, callback, *args, **kwargs):
        self.threads.append(callback)
        pass

    def stop(self):
        pass

    def wait(self):
        pass


class stackCreateTest(HeatTestCase):
    def setUp(self):
        super(stackCreateTest, self).setUp()
        setup_dummy_db()

    def test_wordpress_single_instance_stack_create(self):
        stack = get_wordpress_stack('test_stack', create_context(self.m))
        setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.assertNotEqual(stack.resources['WebServer'], None)
        self.assertTrue(stack.resources['WebServer'].resource_id > 0)
        self.assertNotEqual(stack.resources['WebServer'].ipaddress, '0.0.0.0')

    def test_wordpress_single_instance_stack_delete(self):
        ctx = create_context(self.m, tenant='test_delete_tenant')
        stack = get_wordpress_stack('test_stack', ctx)
        fc = setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack_id = stack.store()
        stack.create()

        db_s = db_api.stack_get(ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.assertNotEqual(stack.resources['WebServer'], None)
        self.assertTrue(stack.resources['WebServer'].resource_id > 0)

        self.m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(service.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)

        stack.delete()

        self.assertEqual(stack.resources['WebServer'].state, 'DELETE_COMPLETE')
        self.assertEqual(db_api.stack_get(ctx, stack_id), None)
        self.assertEqual(db_s.status, 'DELETE_COMPLETE')


class stackServiceCreateUpdateDeleteTest(HeatTestCase):

    def setUp(self):
        super(stackServiceCreateUpdateDeleteTest, self).setUp()
        self.username = 'stack_service_create_test_user'
        self.tenant = 'stack_service_create_test_tenant'
        setup_dummy_db()
        self.ctx = create_context(self.m, self.username, self.tenant)

        self.man = service.EngineService('a-host', 'a-topic')

    def test_stack_create(self):
        stack_name = 'service_create_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(parser, 'Parameters')
        self.m.StubOutWithMock(parser, 'Stack')

        parser.Template(template).AndReturn(stack.t)
        parser.Parameters(stack_name,
                          stack.t,
                          params).AndReturn(stack.parameters)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.parameters).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.StubOutWithMock(threadgroup, 'ThreadGroup')
        threadgroup.ThreadGroup().AndReturn(DummyThreadGroup())

        self.m.ReplayAll()

        result = self.man.create_stack(self.ctx, stack_name,
                                       template, params, {})
        self.assertEqual(result, stack.identifier())
        self.assertTrue(isinstance(result, dict))
        self.assertTrue(result['stack_id'])
        self.m.VerifyAll()

    def test_stack_create_verify_err(self):
        stack_name = 'service_create_verify_err_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(parser, 'Parameters')
        self.m.StubOutWithMock(parser, 'Stack')

        parser.Template(template).AndReturn(stack.t)
        parser.Parameters(stack_name,
                          stack.t,
                          params).AndReturn(stack.parameters)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.parameters).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndRaise(exception.StackValidationFailed(
            message='fubar'))

        self.m.ReplayAll()

        self.assertRaises(
            exception.StackValidationFailed,
            self.man.create_stack,
            self.ctx, stack_name,
            template, params, {})
        self.m.VerifyAll()

    def test_stack_create_invalid_stack_name(self):
        stack_name = 'service_create/test_stack'
        stack = get_wordpress_stack('test_stack', self.ctx)

        self.assertRaises(ValueError,
                          self.man.create_stack,
                          self.ctx, stack_name, stack.t, {}, {})

    def test_stack_create_invalid_resource_name(self):
        stack_name = 'service_create_test_stack_invalid_res'
        stack = get_wordpress_stack(stack_name, self.ctx)
        tmpl = dict(stack.t)
        tmpl['Resources']['Web/Server'] = tmpl['Resources']['WebServer']
        del tmpl['Resources']['WebServer']

        self.assertRaises(ValueError,
                          self.man.create_stack,
                          self.ctx, stack_name,
                          stack.t, {}, {})

    def test_stack_validate(self):
        stack_name = 'service_create_test_validate'
        stack = get_wordpress_stack(stack_name, self.ctx)
        setup_mocks(self.m, stack)

        template = dict(stack.t)
        template['Parameters']['KeyName']['Default'] = 'test'
        resource = stack['WebServer']

        self.m.ReplayAll()

        resource.properties = Properties(
            resource.properties_schema,
            {
                'ImageId': 'foo',
                'KeyName': 'test',
                'InstanceType': 'm1.large'
            })
        stack.validate()

        resource.properties = Properties(
            resource.properties_schema,
            {
                'KeyName': 'test',
                'InstanceType': 'm1.large'
            })
        self.assertRaises(exception.StackValidationFailed, stack.validate)

    def test_stack_delete(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        s = db_api.stack_get(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')

        parser.Stack.load(self.ctx, stack=s).AndReturn(stack)

        self.m.ReplayAll()

        self.assertEqual(self.man.delete_stack(self.ctx, stack.identifier()),
                         None)
        self.m.VerifyAll()

    def test_stack_delete_nonexist(self):
        stack_name = 'service_delete_nonexist_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        self.assertRaises(exception.StackNotFound,
                          self.man.delete_stack,
                          self.ctx, stack.identifier())
        self.m.VerifyAll()

    def test_stack_update(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        sid = old_stack.store()
        s = db_api.stack_get(self.ctx, sid)

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(parser, 'Parameters')

        parser.Template(template).AndReturn(stack.t)
        parser.Parameters(stack_name,
                          stack.t,
                          params).AndReturn(stack.parameters)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.parameters).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.ReplayAll()

        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, {})
        self.assertEqual(result, old_stack.identifier())
        self.assertTrue(isinstance(result, dict))
        self.assertTrue(result['stack_id'])
        self.m.VerifyAll()

    def test_stack_update_verify_err(self):
        stack_name = 'service_update_verify_err_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.store()
        sid = old_stack.store()
        s = db_api.stack_get(self.ctx, sid)

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(parser, 'Parameters')

        parser.Template(template).AndReturn(stack.t)
        parser.Parameters(stack_name,
                          stack.t,
                          params).AndReturn(stack.parameters)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.parameters).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndRaise(exception.StackValidationFailed(
            message='fubar'))

        self.m.ReplayAll()

        self.assertRaises(
            exception.StackValidationFailed,
            self.man.update_stack,
            self.ctx, old_stack.identifier(),
            template, params, {})
        self.m.VerifyAll()

    def test_stack_update_nonexist(self):
        stack_name = 'service_update_nonexist_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        self.assertRaises(exception.StackNotFound,
                          self.man.update_stack,
                          self.ctx, stack.identifier(), template, params, {})
        self.m.VerifyAll()


class stackServiceTestBase(HeatTestCase):

    tenant = 'stack_service_test_tenant'

    def tearDown(self):
        super(stackServiceTestBase, self).tearDown()
        # testtools runs cleanups *after* tearDown, but we need to mock some
        # things now.
        self.m.UnsetStubs()

        m = mox.Mox()
        create_context(m, self.username, self.tenant, ctx=self.stack.context)
        fc = setup_mocks(m, self.stack)
        m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(service.clients.novaclient.exceptions.NotFound(404))
        m.ReplayAll()

        self.stack.delete()

        m.UnsetStubs()

    def setUp(self):
        setup_dummy_db()
        m = mox.Mox()
        self.username = 'stack_service_test_user'
        ctx = create_context(m, self.username, self.tenant)
        self.stack_name = 'service_test_stack'

        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')

        stack = get_wordpress_stack(self.stack_name, ctx)

        setup_mocks(m, stack)
        m.ReplayAll()

        stack.store()
        stack.create()
        self.stack = stack
        self.stack_identity = stack.identifier()

        m.UnsetStubs()

        super(stackServiceTestBase, self).setUp()
        self.m.UnsetStubs()
        self.ctx = create_context(self.m, self.username, self.tenant)
        setup_mocks(self.m, self.stack)


class stackServiceTest(stackServiceTestBase):

    def setUp(self):
        super(stackServiceTest, self).setUp()
        self.m.ReplayAll()

        self.man = service.EngineService('a-host', 'a-topic')

    def test_stack_identify(self):
        identity = self.man.identify_stack(self.ctx, self.stack_name)
        self.assertEqual(identity, self.stack_identity)

    def test_stack_identify_uuid(self):
        identity = self.man.identify_stack(self.ctx, self.stack.id)
        self.assertEqual(identity, self.stack_identity)

    def test_stack_identify_nonexist(self):
        self.assertRaises(exception.StackNotFound, self.man.identify_stack,
                          self.ctx, 'wibble')

    def test_stack_create_existing(self):
        self.assertRaises(exception.StackExists, self.man.create_stack,
                          self.ctx, self.stack_name, self.stack.t, {}, {})

    def test_stack_by_name_tenants(self):
        self.assertEqual(self.stack.id,
                         db_api.stack_get_by_name(self.ctx,
                                                  self.stack_name).id)
        ctx2 = create_context(self.m, self.username,
                              'stack_service_test_tenant2')
        self.assertEqual(None, db_api.stack_get_by_name(ctx2, self.stack_name))

    def test_stack_event_list(self):
        events = self.man.list_events(self.ctx, self.stack_identity)

        self.assertEqual(len(events), 2)
        for ev in events:
            self.assertTrue('event_identity' in ev)
            self.assertEqual(type(ev['event_identity']), dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertTrue('logical_resource_id' in ev)
            self.assertEqual(ev['logical_resource_id'], 'WebServer')

            self.assertTrue('physical_resource_id' in ev)

            self.assertTrue('resource_properties' in ev)
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            user_data = ev['resource_properties']['UserData']
            self.assertNotEqual(user_data.find('wordpress'), -1)
            self.assertEqual(ev['resource_properties']['ImageId'],
                             'F17-x86_64-gold')
            self.assertEqual(ev['resource_properties']['InstanceType'],
                             'm1.large')

            self.assertTrue('resource_status' in ev)
            self.assertTrue(ev['resource_status'] in ('IN_PROGRESS',
                                                      'CREATE_COMPLETE'))

            self.assertTrue('resource_status_reason' in ev)
            self.assertEqual(ev['resource_status_reason'], 'state changed')

            self.assertTrue('resource_type' in ev)
            self.assertEqual(ev['resource_type'], 'AWS::EC2::Instance')

            self.assertTrue('stack_identity' in ev)

            self.assertTrue('stack_name' in ev)
            self.assertEqual(ev['stack_name'], self.stack_name)

            self.assertTrue('event_time' in ev)

    def test_stack_list_all(self):
        sl = self.man.list_stacks(self.ctx)

        self.assertEqual(len(sl), 1)
        for s in sl:
            self.assertTrue('creation_time' in s)
            self.assertTrue('updated_time' in s)
            self.assertTrue('stack_identity' in s)
            self.assertNotEqual(s['stack_identity'], None)
            self.assertTrue('stack_name' in s)
            self.assertEqual(s['stack_name'], self.stack_name)
            self.assertTrue('stack_status' in s)
            self.assertTrue('stack_status_reason' in s)
            self.assertTrue('description' in s)
            self.assertNotEqual(s['description'].find('WordPress'), -1)

    def test_stack_describe_nonexistent(self):
        nonexist = dict(self.stack_identity)
        nonexist['stack_name'] = 'wibble'
        self.assertRaises(exception.StackNotFound,
                          self.man.show_stack,
                          self.ctx, nonexist)

    def test_stack_describe_bad_tenant(self):
        nonexist = dict(self.stack_identity)
        nonexist['tenant'] = 'wibble'
        self.assertRaises(exception.InvalidTenant,
                          self.man.show_stack,
                          self.ctx, nonexist)

    def test_stack_describe(self):
        sl = self.man.show_stack(self.ctx, self.stack_identity)

        self.assertEqual(len(sl), 1)

        s = sl[0]
        self.assertTrue('creation_time' in s)
        self.assertTrue('updated_time' in s)
        self.assertTrue('stack_identity' in s)
        self.assertNotEqual(s['stack_identity'], None)
        self.assertTrue('stack_name' in s)
        self.assertEqual(s['stack_name'], self.stack_name)
        self.assertTrue('stack_status' in s)
        self.assertTrue('stack_status_reason' in s)
        self.assertTrue('description' in s)
        self.assertNotEqual(s['description'].find('WordPress'), -1)
        self.assertTrue('parameters' in s)

    def test_stack_describe_all(self):
        sl = self.man.show_stack(self.ctx, None)

        self.assertEqual(len(sl), 1)

        s = sl[0]
        self.assertTrue('creation_time' in s)
        self.assertTrue('updated_time' in s)
        self.assertTrue('stack_identity' in s)
        self.assertNotEqual(s['stack_identity'], None)
        self.assertTrue('stack_name' in s)
        self.assertEqual(s['stack_name'], self.stack_name)
        self.assertTrue('stack_status' in s)
        self.assertTrue('stack_status_reason' in s)
        self.assertTrue('description' in s)
        self.assertNotEqual(s['description'].find('WordPress'), -1)
        self.assertTrue('parameters' in s)

    def test_list_resource_types(self):
        resources = self.man.list_resource_types(self.ctx)
        self.assertTrue(isinstance(resources, list))
        self.assertTrue('AWS::EC2::Instance' in resources)

    def test_stack_resource_describe(self):
        r = self.man.describe_stack_resource(self.ctx, self.stack_identity,
                                             'WebServer')

        self.assertTrue('resource_identity' in r)
        self.assertTrue('description' in r)
        self.assertTrue('updated_time' in r)
        self.assertTrue('stack_identity' in r)
        self.assertNotEqual(r['stack_identity'], None)
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
        nonexist = dict(self.stack_identity)
        nonexist['stack_name'] = 'foo'
        self.assertRaises(exception.StackNotFound,
                          self.man.describe_stack_resource,
                          self.ctx, nonexist, 'WebServer')

    def test_stack_resource_describe_nonexist_resource(self):
        self.assertRaises(exception.ResourceNotFound,
                          self.man.describe_stack_resource,
                          self.ctx, self.stack_identity, 'foo')

    def test_stack_resource_describe_stack_user_deny(self):
        self.ctx.roles = [cfg.CONF.heat_stack_user_role]
        self.m.StubOutWithMock(service.EngineService, '_authorize_stack_user')
        service.EngineService._authorize_stack_user(self.ctx, mox.IgnoreArg(),
                                                    'foo').AndReturn(False)
        self.m.ReplayAll()
        self.assertRaises(exception.Forbidden,
                          self.man.describe_stack_resource,
                          self.ctx, self.stack_identity, 'foo')

    def test_stack_authorize_stack_user_nocreds(self):
        self.assertFalse(self.man._authorize_stack_user(self.ctx,
                                                        self.stack_identity,
                                                        'foo'))

    def test_stack_authorize_stack_user_attribute_error(self):
        self.m.StubOutWithMock(json, 'loads')
        json.loads(mox.IgnoreArg()).AndRaise(AttributeError)
        self.assertFalse(self.man._authorize_stack_user(self.ctx,
                                                        self.stack_identity,
                                                        'foo'))

    def test_stack_authorize_stack_user_type_error(self):
        self.m.StubOutWithMock(json, 'loads')
        json.loads(mox.IgnoreArg()).AndRaise(TypeError)
        self.assertFalse(self.man._authorize_stack_user(self.ctx,
                                                        self.stack_identity,
                                                        'foo'))

    def test_stack_resources_describe(self):
        resources = self.man.describe_stack_resources(self.ctx,
                                                      self.stack_identity,
                                                      'WebServer')

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('resource_identity' in r)
        self.assertTrue('description' in r)
        self.assertTrue('updated_time' in r)
        self.assertTrue('stack_identity' in r)
        self.assertNotEqual(r['stack_identity'], None)
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
                                                      self.stack_identity,
                                                      None)

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('logical_resource_id' in r)
        self.assertEqual(r['logical_resource_id'], 'WebServer')

    def test_stack_resources_describe_bad_lookup(self):
        self.assertRaises(TypeError,
                          self.man.describe_stack_resources,
                          self.ctx, None, 'WebServer')

    def test_stack_resources_describe_nonexist_stack(self):
        nonexist = dict(self.stack_identity)
        nonexist['stack_name'] = 'foo'
        self.assertRaises(exception.StackNotFound,
                          self.man.describe_stack_resources,
                          self.ctx, nonexist, 'WebServer')

    def test_find_physical_resource(self):
        resources = self.man.describe_stack_resources(self.ctx,
                                                      self.stack_identity,
                                                      None)
        phys_id = resources[0]['physical_resource_id']

        result = self.man.find_physical_resource(self.ctx, phys_id)
        self.assertTrue(isinstance(result, dict))
        resource_identity = identifier.ResourceIdentifier(**result)
        self.assertEqual(resource_identity.stack(), self.stack_identity)
        self.assertEqual(resource_identity.resource_name, 'WebServer')

    def test_find_physical_resource_nonexist(self):
        self.assertRaises(exception.PhysicalResourceNotFound,
                          self.man.find_physical_resource,
                          self.ctx, 'foo')

    def test_stack_resources_list(self):
        resources = self.man.list_stack_resources(self.ctx,
                                                  self.stack_identity)

        self.assertEqual(len(resources), 1)
        r = resources[0]
        self.assertTrue('resource_identity' in r)
        self.assertTrue('updated_time' in r)
        self.assertTrue('physical_resource_id' in r)
        self.assertTrue('logical_resource_id' in r)
        self.assertEqual(r['logical_resource_id'], 'WebServer')
        self.assertTrue('resource_status' in r)
        self.assertTrue('resource_status_reason' in r)
        self.assertTrue('resource_type' in r)

    def test_stack_resources_list_nonexist_stack(self):
        nonexist = dict(self.stack_identity)
        nonexist['stack_name'] = 'foo'
        self.assertRaises(exception.StackNotFound,
                          self.man.list_stack_resources,
                          self.ctx, nonexist)

    def test_metadata(self):
        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        pre_update_meta = self.stack['WebServer'].metadata
        result = self.man.metadata_update(self.ctx,
                                          dict(self.stack_identity),
                                          'WebServer', test_metadata)
        # metadata_update is a no-op for all resources except
        # WaitConditionHandle so we don't expect this to have changed
        self.assertEqual(result, pre_update_meta)

    def test_metadata_err_stack(self):
        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        nonexist = dict(self.stack_identity)
        nonexist['stack_name'] = 'foo'
        self.assertRaises(exception.StackNotFound,
                          self.man.metadata_update,
                          self.ctx, nonexist,
                          'WebServer', test_metadata)

    def test_metadata_err_resource(self):
        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        self.assertRaises(exception.ResourceNotFound,
                          self.man.metadata_update,
                          self.ctx, dict(self.stack_identity),
                          'NooServer', test_metadata)

    def test_show_watch(self):
        # Insert two dummy watch rules into the DB
        values = {'stack_id': self.stack.id,
                  'state': 'NORMAL',
                  'name': u'HttpFailureAlarm',
                  'rule': {u'EvaluationPeriods': u'1',
                           u'AlarmActions': [u'WebServerRestartPolicy'],
                           u'AlarmDescription': u'Restart the WikiDatabase',
                           u'Namespace': u'system/linux',
                           u'Period': u'300',
                           u'ComparisonOperator': u'GreaterThanThreshold',
                           u'Statistic': u'SampleCount',
                           u'Threshold': u'2',
                           u'MetricName': u'ServiceFailure'}}
        db_ret = db_api.watch_rule_create(self.ctx, values)
        self.assertNotEqual(db_ret, None)
        values['name'] = "AnotherWatch"
        db_ret = db_api.watch_rule_create(self.ctx, values)
        self.assertNotEqual(db_ret, None)

        # watch_name=None should return both watches
        result = self.man.show_watch(self.ctx, watch_name=None)
        self.assertEqual(2, len(result))

        # watch_name="HttpFailureAlarm" should return only one
        result = self.man.show_watch(self.ctx, watch_name="HttpFailureAlarm")
        self.assertEqual(1, len(result))

        self.assertRaises(exception.WatchRuleNotFound,
                          self.man.show_watch,
                          self.ctx, watch_name="nonexistent")

        # Check the response has all keys defined in the engine API
        for key in engine_api.WATCH_KEYS:
            self.assertTrue(key in result[0])

        # Cleanup, delete the dummy rules
        db_api.watch_rule_delete(self.ctx, "HttpFailureAlarm")
        db_api.watch_rule_delete(self.ctx, "AnotherWatch")

    def test_show_watch_metric(self):
        # Insert dummy watch rule into the DB
        values = {'stack_id': self.stack.id,
                  'state': 'NORMAL',
                  'name': u'HttpFailureAlarm',
                  'rule': {u'EvaluationPeriods': u'1',
                           u'AlarmActions': [u'WebServerRestartPolicy'],
                           u'AlarmDescription': u'Restart the WikiDatabase',
                           u'Namespace': u'system/linux',
                           u'Period': u'300',
                           u'ComparisonOperator': u'GreaterThanThreshold',
                           u'Statistic': u'SampleCount',
                           u'Threshold': u'2',
                           u'MetricName': u'ServiceFailure'}}
        db_ret = db_api.watch_rule_create(self.ctx, values)
        self.assertNotEqual(db_ret, None)

        # And add a metric datapoint
        watch = db_api.watch_rule_get_by_name(self.ctx, "HttpFailureAlarm")
        self.assertNotEqual(watch, None)
        values = {'watch_rule_id': watch.id,
                  'data': {u'Namespace': u'system/linux',
                           u'ServiceFailure': {
                           u'Units': u'Counter', u'Value': 1}}}
        watch = db_api.watch_data_create(self.ctx, values)

        # Check there is one result returned
        result = self.man.show_watch_metric(self.ctx, namespace=None,
                                            metric_name=None)
        self.assertEqual(1, len(result))

        # Create another metric datapoint and check we get two
        watch = db_api.watch_data_create(self.ctx, values)
        result = self.man.show_watch_metric(self.ctx, namespace=None,
                                            metric_name=None)
        self.assertEqual(2, len(result))

        # Cleanup, delete the dummy rule
        db_api.watch_rule_delete(self.ctx, "HttpFailureAlarm")

        # Check the response has all keys defined in the engine API
        for key in engine_api.WATCH_DATA_KEYS:
            self.assertTrue(key in result[0])

    def test_set_watch_state(self):
        # Insert dummy watch rule into the DB
        values = {'stack_id': self.stack.id,
                  'state': 'NORMAL',
                  'name': u'OverrideAlarm',
                  'rule': {u'EvaluationPeriods': u'1',
                           u'AlarmActions': [u'WebServerRestartPolicy'],
                           u'AlarmDescription': u'Restart the WikiDatabase',
                           u'Namespace': u'system/linux',
                           u'Period': u'300',
                           u'ComparisonOperator': u'GreaterThanThreshold',
                           u'Statistic': u'SampleCount',
                           u'Threshold': u'2',
                           u'MetricName': u'ServiceFailure'}}
        db_ret = db_api.watch_rule_create(self.ctx, values)
        self.assertNotEqual(db_ret, None)

        class DummyAction:
            alarm = "dummyfoo"

        dummy_action = DummyAction()
        self.m.StubOutWithMock(parser.Stack, '__getitem__')
        parser.Stack.__getitem__(
            'WebServerRestartPolicy').AndReturn(dummy_action)

        # Replace the real stack threadgroup with a dummy one, so we can
        # check the function returned on ALARM is correctly scheduled
        self.man.stg[self.stack.id] = DummyThreadGroup()

        self.m.ReplayAll()

        state = watchrule.WatchRule.NODATA
        result = self.man.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(result[engine_api.WATCH_STATE_VALUE], state)
        self.assertEqual(self.man.stg[self.stack.id].threads, [])

        state = watchrule.WatchRule.NORMAL
        result = self.man.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(result[engine_api.WATCH_STATE_VALUE], state)
        self.assertEqual(self.man.stg[self.stack.id].threads, [])

        state = watchrule.WatchRule.ALARM
        result = self.man.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(result[engine_api.WATCH_STATE_VALUE], state)
        self.assertEqual(self.man.stg[self.stack.id].threads,
                         [DummyAction.alarm])

        # Cleanup, delete the dummy rule
        db_api.watch_rule_delete(self.ctx, "OverrideAlarm")

    def test_set_watch_state_badstate(self):
        # Insert dummy watch rule into the DB
        values = {'stack_id': self.stack.id,
                  'state': 'NORMAL',
                  'name': u'OverrideAlarm2',
                  'rule': {u'EvaluationPeriods': u'1',
                           u'AlarmActions': [u'WebServerRestartPolicy'],
                           u'AlarmDescription': u'Restart the WikiDatabase',
                           u'Namespace': u'system/linux',
                           u'Period': u'300',
                           u'ComparisonOperator': u'GreaterThanThreshold',
                           u'Statistic': u'SampleCount',
                           u'Threshold': u'2',
                           u'MetricName': u'ServiceFailure'}}
        db_ret = db_api.watch_rule_create(self.ctx, values)
        self.assertNotEqual(db_ret, None)

        for state in ["HGJHGJHG", "1234", "!\*(&%"]:
            self.assertRaises(ValueError,
                              self.man.set_watch_state,
                              self.ctx, watch_name="OverrideAlarm2",
                              state=state)

        # Cleanup, delete the dummy rule
        db_api.watch_rule_delete(self.ctx, "OverrideAlarm2")

    def test_set_watch_state_noexist(self):
        state = watchrule.WatchRule.ALARM   # State valid
        self.assertRaises(exception.WatchRuleNotFound,
                          self.man.set_watch_state,
                          self.ctx, watch_name="nonexistent", state=state)


class stackServiceTestEmpty(stackServiceTestBase):

    def setUp(self):
        super(stackServiceTestEmpty, self).setUp()

        # Change to a new, empty tenant context
        self.ctx = create_context(self.m, self.username,
                                  'stack_list_all_empty_tenant')
        self.m.ReplayAll()

        self.man = service.EngineService('a-host', 'a-topic')

    def test_stack_list_all_empty(self):
        sl = self.man.list_stacks(self.ctx)

        self.assertEqual(len(sl), 0)

    def test_stack_describe_all_empty(self):
        sl = self.man.show_stack(self.ctx, None)

        self.assertEqual(len(sl), 0)
