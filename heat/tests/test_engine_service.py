#
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

import datetime
import sys
import uuid

import eventlet
from eventlet import event as grevent
import mock
import mox
from oslo_config import cfg
from oslo_messaging.rpc import dispatcher
from oslo_serialization import jsonutils as json
from oslo_utils import timeutils
import six

from heat.common import context
from heat.common import exception
from heat.common import identifier
from heat.common import messaging
from heat.common import service_utils
from heat.common import template_format
from heat.db import api as db_api
from heat.engine.clients.os import glance
from heat.engine.clients.os import keystone
from heat.engine.clients.os import nova
from heat.engine.clients.os import swift
from heat.engine import dependencies
from heat.engine import environment
from heat.engine import properties
from heat.engine import resource as res
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine import service
from heat.engine import service_software_config
from heat.engine import service_stack_watch
from heat.engine import stack as parser
from heat.engine import stack_lock
from heat.engine import template as templatem
from heat.engine import watchrule
from heat.engine import worker
from heat.objects import event as event_object
from heat.objects import resource as resource_objects
from heat.objects import service as service_objects
from heat.objects import software_deployment as software_deployment_object
from heat.objects import stack as stack_object
from heat.objects import stack_lock as stack_lock_object
from heat.objects import watch_data as watch_data_object
from heat.objects import watch_rule as watch_rule_object
from heat.openstack.common import threadgroup
from heat.rpc import api as rpc_api
from heat.rpc import worker_api
from heat.tests import common
from heat.tests import fakes as test_fakes
from heat.tests import generic_resource as generic_rsrc
from heat.tests.nova import fakes as fakes_nova
from heat.tests import utils

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')
cfg.CONF.import_opt('enable_stack_abandon', 'heat.common.config')

wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''

wp_template_no_default = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''

policy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "alarming",
  "Resources" : {
    "WebServerScaleDownPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : "",
        "Cooldown" : "60",
        "ScalingAdjustment" : "-1"
      }
    },
    "Random" : {
      "Type" : "OS::Heat::RandomString"
    }
  }
}
'''

user_policy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a User",
  "Parameters" : {},
  "Resources" : {
    "CfnUser" : {
      "Type" : "AWS::IAM::User",
      "Properties" : {
        "Policies" : [ { "Ref": "WebServerAccessPolicy"} ]
      }
    },
    "WebServerAccessPolicy" : {
      "Type" : "OS::Heat::AccessPolicy",
      "Properties" : {
        "AllowedResources" : [ "WebServer" ]
      }
    },
    "HostKeys" : {
      "Type" : "AWS::IAM::AccessKey",
      "Properties" : {
        "UserName" : {"Ref": "CfnUser"}
      }
    },
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''

server_config_template = '''
heat_template_version: 2013-05-23
resources:
  WebServer:
    type: OS::Nova::Server
'''


def get_wordpress_stack(stack_name, ctx):
    t = template_format.parse(wp_template)
    template = templatem.Template(
        t, env=environment.Environment({'KeyName': 'test'}))
    stack = parser.Stack(ctx, stack_name, template)
    return stack


def get_wordpress_stack_no_params(stack_name, ctx):
    t = template_format.parse(wp_template)
    template = templatem.Template(t)
    stack = parser.Stack(ctx, stack_name, template)
    return stack


def get_stack(stack_name, ctx, template):
    t = template_format.parse(template)
    template = templatem.Template(t)
    stack = parser.Stack(ctx, stack_name, template)
    return stack


def setup_keystone_mocks(mocks, stack):
    fkc = test_fakes.FakeKeystoneClient()
    mocks.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
    keystone.KeystoneClientPlugin._create().AndReturn(fkc)


def setup_mock_for_image_constraint(mocks, imageId_input,
                                    imageId_output=744):
    mocks.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
    glance.GlanceClientPlugin.get_image_id(
        imageId_input).MultipleTimes().AndReturn(imageId_output)


def setup_mocks(mocks, stack, mock_image_constraint=True,
                mock_keystone=True):
    fc = fakes_nova.FakeClient()
    mocks.StubOutWithMock(instances.Instance, 'nova')
    instances.Instance.nova().MultipleTimes().AndReturn(fc)
    mocks.StubOutWithMock(nova.NovaClientPlugin, '_create')
    nova.NovaClientPlugin._create().AndReturn(fc)
    instance = stack['WebServer']
    metadata = instance.metadata_get()
    if mock_image_constraint:
        setup_mock_for_image_constraint(mocks,
                                        instance.t['Properties']['ImageId'])

    if mock_keystone:
        setup_keystone_mocks(mocks, stack)

    user_data = instance.properties['UserData']
    server_userdata = instance.client_plugin().build_userdata(
        metadata, user_data, 'ec2-user')
    mocks.StubOutWithMock(nova.NovaClientPlugin, 'build_userdata')
    nova.NovaClientPlugin.build_userdata(
        metadata,
        instance.t['Properties']['UserData'],
        'ec2-user').AndReturn(server_userdata)

    mocks.StubOutWithMock(fc.servers, 'create')
    fc.servers.create(
        image=744,
        flavor=3,
        key_name='test',
        name=utils.PhysName(stack.name, 'WebServer'),
        security_groups=None,
        userdata=server_userdata,
        scheduler_hints=None,
        meta=None,
        nics=None,
        availability_zone=None,
        block_device_mapping=None).AndReturn(fc.servers.list()[4])
    return fc


def setup_stack(stack_name, ctx, create_res=True):
    stack = get_wordpress_stack(stack_name, ctx)
    stack.store()
    if create_res:
        m = mox.Mox()
        setup_mocks(m, stack)
        m.ReplayAll()
        stack.create()
        m.UnsetStubs()
    return stack


def clean_up_stack(stack, delete_res=True):
    if delete_res:
        m = mox.Mox()
        fc = fakes_nova.FakeClient()
        m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(fc)
        m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(fakes_nova.fake_exception())
        m.ReplayAll()
    stack.delete()
    if delete_res:
        m.UnsetStubs()


def stack_context(stack_name, create_res=True):
    """
    Decorator which creates a stack by using the test case's context and
    deletes it afterwards to ensure tests clean up their stacks regardless
    of test success/failure
    """
    def stack_delete(test_fn):
        @six.wraps(test_fn)
        def wrapped_test(test_case, *args, **kwargs):
            def create_stack():
                ctx = getattr(test_case, 'ctx', None)
                if ctx is not None:
                    stack = setup_stack(stack_name, ctx, create_res)
                    setattr(test_case, 'stack', stack)

            def delete_stack():
                stack = getattr(test_case, 'stack', None)
                if stack is not None and stack.id is not None:
                    clean_up_stack(stack, delete_res=create_res)

            create_stack()
            try:
                test_fn(test_case, *args, **kwargs)
            except Exception:
                exc_class, exc_val, exc_tb = sys.exc_info()
                try:
                    delete_stack()
                finally:
                    raise exc_class, exc_val, exc_tb
            else:
                delete_stack()

        return wrapped_test
    return stack_delete


class DummyThread(object):

    def link(self, callback, *args):
        pass


class DummyThreadGroup(object):
    def __init__(self):
        self.threads = []

    def add_timer(self, interval, callback, initial_delay=None,
                  *args, **kwargs):
        self.threads.append(callback)

    def stop_timers(self):
        pass

    def add_thread(self, callback, *args, **kwargs):
        # just to make _start_with_trace() easier to test:
        # callback == _start_with_trace
        # args[0] == trace_info
        # args[1] == actual_callback
        callback = args[1]
        self.threads.append(callback)
        return DummyThread()

    def stop(self, graceful=False):
        pass

    def wait(self):
        pass


class StackCreateTest(common.HeatTestCase):
    def setUp(self):
        super(StackCreateTest, self).setUp()

    def test_wordpress_single_instance_stack_create(self):
        stack = get_wordpress_stack('test_stack', utils.dummy_context())
        setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.assertIsNotNone(stack['WebServer'])
        self.assertTrue(stack['WebServer'].resource_id > 0)
        self.assertNotEqual(stack['WebServer'].ipaddress, '0.0.0.0')

    def test_wordpress_single_instance_stack_adopt(self):
        t = template_format.parse(wp_template)
        template = templatem.Template(t)
        ctx = utils.dummy_context()
        adopt_data = {
            'resources': {
                'WebServer': {
                    'resource_id': 'test-res-id'
                }
            }
        }
        stack = parser.Stack(ctx,
                             'test_stack',
                             template,
                             adopt_stack_data=adopt_data)

        setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.adopt()

        self.assertIsNotNone(stack['WebServer'])
        self.assertEqual('test-res-id', stack['WebServer'].resource_id)
        self.assertEqual((stack.ADOPT, stack.COMPLETE), stack.state)

    def test_wordpress_single_instance_stack_adopt_fail(self):
        t = template_format.parse(wp_template)
        template = templatem.Template(t)
        ctx = utils.dummy_context()
        adopt_data = {
            'resources': {
                'WebServer1': {
                    'resource_id': 'test-res-id'
                }
            }
        }
        stack = parser.Stack(ctx,
                             'test_stack',
                             template,
                             adopt_stack_data=adopt_data)

        setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.adopt()
        self.assertIsNotNone(stack['WebServer'])
        expected = ('Resource ADOPT failed: Exception: resources.WebServer: '
                    'Resource ID was not provided.')
        self.assertEqual(expected, stack.status_reason)
        self.assertEqual((stack.ADOPT, stack.FAILED), stack.state)

    def test_wordpress_single_instance_stack_delete(self):
        ctx = utils.dummy_context()
        stack = get_wordpress_stack('test_stack', ctx)
        fc = setup_mocks(self.m, stack, mock_keystone=False)
        self.m.ReplayAll()
        stack_id = stack.store()
        stack.create()

        db_s = stack_object.Stack.get_by_id(ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.assertIsNotNone(stack['WebServer'])
        self.assertTrue(stack['WebServer'].resource_id > 0)

        self.m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(fakes_nova.fake_exception())
        mox.Replay(get)
        stack.delete()

        rsrc = stack['WebServer']
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual((stack.DELETE, stack.COMPLETE), rsrc.state)
        self.assertIsNone(stack_object.Stack.get_by_id(ctx, stack_id))

        db_s.refresh()
        self.assertEqual('DELETE', db_s.action)
        self.assertEqual('COMPLETE', db_s.status, )


class StackServiceCreateUpdateDeleteTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceCreateUpdateDeleteTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.patch('heat.engine.service.warnings')
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.create_periodic_tasks()

    def _test_stack_create(self, stack_name):
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t, owner_id=None,
                     nested_depth=0, user_creds_id=None,
                     stack_user_project_id=None,
                     convergence=False,
                     parent_resource=None).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.StubOutWithMock(threadgroup, 'ThreadGroup')
        threadgroup.ThreadGroup().AndReturn(DummyThreadGroup())

        self.m.ReplayAll()

        result = self.man.create_stack(self.ctx, stack_name,
                                       template, params, None, {})
        self.assertEqual(stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.m.VerifyAll()

    def test_stack_create(self):
        stack_name = 'service_create_test_stack'
        self._test_stack_create(stack_name)

    def test_stack_create_equals_max_per_tenant(self):
        cfg.CONF.set_override('max_stacks_per_tenant', 1)
        stack_name = 'service_create_test_stack_equals_max'
        self._test_stack_create(stack_name)

    def test_stack_create_exceeds_max_per_tenant(self):
        cfg.CONF.set_override('max_stacks_per_tenant', 0)
        stack_name = 'service_create_test_stack_exceeds_max'
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._test_stack_create, stack_name)
        self.assertEqual(exception.RequestLimitExceeded, ex.exc_info[0])
        self.assertIn("You have reached the maximum stacks per tenant",
                      six.text_type(ex.exc_info[1]))

    def test_stack_create_verify_err(self):
        stack_name = 'service_create_verify_err_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     owner_id=None,
                     nested_depth=0,
                     user_creds_id=None,
                     stack_user_project_id=None,
                     convergence=False,
                     parent_resource=None).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndRaise(exception.StackValidationFailed(
            message='fubar'))

        self.m.ReplayAll()

        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.create_stack,
            self.ctx, stack_name,
            template, params, None, {})
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])
        self.m.VerifyAll()

    def _get_stack_adopt_data_and_template(self, environment=None):
        template = {
            "heat_template_version": "2013-05-23",
            "parameters": {"app_dbx": {"type": "string"}},
            "resources": {"res1": {"type": "GenericResourceType"}}}

        adopt_data = {
            "status": "COMPLETE",
            "name": "rtrove1",
            "environment": environment,
            "template": template,
            "action": "CREATE",
            "id": "8532f0d3-ea84-444e-b2bb-2543bb1496a4",
            "resources": {"res1": {
                    "status": "COMPLETE",
                    "name": "database_password",
                    "resource_id": "yBpuUROjfGQ2gKOD",
                    "action": "CREATE",
                    "type": "GenericResourceType",
                    "metadata": {}}}}
        return template, adopt_data

    def test_stack_adopt_with_params(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        environment = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_stack_adopt_data_and_template(
            environment)
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        result = self.man.create_stack(self.ctx, "test_adopt_stack",
                                       template, {}, None,
                                       {'adopt_stack_data': str(adopt_data)})

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(environment['parameters'],
                         stack.raw_template.environment['parameters'])

    def test_stack_adopt_saves_input_params(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        environment = {'parameters': {"app_dbx": "foo"}}
        input_params = {
            "parameters": {"app_dbx": "bar"}
        }
        template, adopt_data = self._get_stack_adopt_data_and_template(
            environment)
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        result = self.man.create_stack(self.ctx, "test_adopt_stack",
                                       template, input_params, None,
                                       {'adopt_stack_data': str(adopt_data)})

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(input_params['parameters'],
                         stack.raw_template.environment['parameters'])

    def test_stack_adopt_stack_state(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        env = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_stack_adopt_data_and_template(
            env)
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        result = self.man.create_stack(self.ctx, "test_adopt_stack",
                                       template, {}, None,
                                       {'adopt_stack_data': str(adopt_data)})

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual((parser.Stack.ADOPT, parser.Stack.IN_PROGRESS),
                         (stack.action, stack.status))

    def test_stack_adopt_disabled(self):
        # to test disable stack adopt
        cfg.CONF.set_override('enable_stack_adopt', False)
        environment = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_stack_adopt_data_and_template(
            environment)
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.create_stack,
            self.ctx, "test_adopt_stack_disabled",
            template, {}, None,
            {'adopt_stack_data': str(adopt_data)})
        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertIn('Stack Adopt', six.text_type(ex.exc_info[1]))

    def test_stack_create_invalid_stack_name(self):
        stack_name = 'service_create/test_stack'
        stack = get_wordpress_stack('test_stack', self.ctx)

        self.assertRaises(dispatcher.ExpectedException,
                          self.man.create_stack,
                          self.ctx, stack_name, stack.t.t, {}, None, {})

    def test_stack_create_enabled_convergence_engine(self):
        cfg.CONF.set_override('convergence_engine', True)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack, self.ctx, 'test',
                               wp_template, {}, None, {})
        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertEqual('Convergence engine is not supported.',
                         six.text_type(ex.exc_info[1]))

    def test_stack_create_invalid_resource_name(self):
        stack_name = 'service_create_test_stack_invalid_res'
        stack = get_wordpress_stack(stack_name, self.ctx)
        tmpl = dict(stack.t)
        tmpl['Resources']['Web/Server'] = tmpl['Resources']['WebServer']
        del tmpl['Resources']['WebServer']

        self.assertRaises(dispatcher.ExpectedException,
                          self.man.create_stack,
                          self.ctx, stack_name,
                          stack.t.t, {}, None, {})

    def test_stack_create_AuthorizationFailure(self):
        stack_name = 'service_create_test_stack_AuthorizationFailure'
        stack = get_wordpress_stack(stack_name, self.ctx)
        self.m.StubOutWithMock(parser.Stack, 'create_stack_user_project_id')
        parser.Stack.create_stack_user_project_id().AndRaise(
            exception.AuthorizationFailure)
        self.assertRaises(dispatcher.ExpectedException,
                          self.man.create_stack,
                          self.ctx, stack_name,
                          stack.t.t, {}, None, {})

    def test_stack_create_no_credentials(self):
        cfg.CONF.set_default('deferred_auth_method', 'password')
        stack_name = 'test_stack_create_no_credentials'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)
        # force check for credentials on create
        stack['WebServer'].requires_deferred_auth = True

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        ctx_no_pwd = utils.dummy_context(password=None)
        ctx_no_user = utils.dummy_context(user=None)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(ctx_no_pwd, stack.name,
                     stack.t, owner_id=None,
                     nested_depth=0, user_creds_id=None,
                     stack_user_project_id=None,
                     convergence=False,
                     parent_resource=None).AndReturn(stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(ctx_no_user, stack.name,
                     stack.t, owner_id=None,
                     nested_depth=0, user_creds_id=None,
                     stack_user_project_id=None,
                     convergence=False,
                     parent_resource=None).AndReturn(stack)

        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack,
                               ctx_no_pwd, stack_name,
                               template, params, None, {}, None)
        self.assertEqual(exception.MissingCredentialError, ex.exc_info[0])
        self.assertEqual(
            'Missing required credential: X-Auth-Key',
            six.text_type(ex.exc_info[1]))

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack,
                               ctx_no_user, stack_name,
                               template, params, None, {})
        self.assertEqual(exception.MissingCredentialError, ex.exc_info[0])
        self.assertEqual(
            'Missing required credential: X-Auth-User',
            six.text_type(ex.exc_info[1]))

    @mock.patch.object(stack_object.Stack, 'count_total_resources')
    def test_stack_create_total_resources_equals_max(self, ctr):
        stack_name = 'service_create_stack_total_resources_equals_max'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {
                   'A': {'Type': 'GenericResourceType'},
                   'B': {'Type': 'GenericResourceType'},
                   'C': {'Type': 'GenericResourceType'}}}
        ctr.return_value = 3

        template = templatem.Template(tpl)
        stack = parser.Stack(self.ctx, stack_name, template)

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     owner_id=None,
                     nested_depth=0,
                     user_creds_id=None,
                     stack_user_project_id=None,
                     convergence=False,
                     parent_resource=None).AndReturn(stack)

        self.m.ReplayAll()

        cfg.CONF.set_override('max_resources_per_stack', 3)

        result = self.man.create_stack(self.ctx, stack_name, template, params,
                                       None, {})
        self.m.VerifyAll()
        self.assertEqual(stack.identifier(), result)
        self.assertEqual(3, stack.total_resources())
        self.man.thread_group_mgr.groups[stack.id].wait()
        stack.delete()

    def test_stack_create_total_resources_exceeds_max(self):
        stack_name = 'service_create_stack_total_resources_exceeds_max'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {
                   'A': {'Type': 'GenericResourceType'},
                   'B': {'Type': 'GenericResourceType'},
                   'C': {'Type': 'GenericResourceType'}}}
        cfg.CONF.set_override('max_resources_per_stack', 2)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.create_stack, self.ctx, stack_name,
                               tpl, params, None, {})
        self.assertEqual(exception.RequestLimitExceeded, ex.exc_info[0])
        self.assertIn(exception.StackResourceLimitExceeded.msg_fmt,
                      six.text_type(ex.exc_info[1]))

    @mock.patch.object(instances.Instance, 'validate')
    @mock.patch.object(parser.Stack, 'total_resources')
    def test_stack_create_max_unlimited(self, total_res_mock, validate_mock):
        total_res_mock.return_value = 9999
        validate_mock.return_value = None
        cfg.CONF.set_override('max_resources_per_stack', -1)
        stack_name = 'service_create_test_max_unlimited'
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {}}
        tmpl = templatem.Template(tpl)
        stack = parser.Stack(self.ctx, stack_name, tmpl)
        self.man.create_stack(self.ctx, stack_name, stack.t.t, {}, None, {})

    def test_stack_validate(self):
        stack_name = 'service_create_test_validate'
        stack = get_wordpress_stack(stack_name, self.ctx)
        setup_mocks(self.m, stack, mock_image_constraint=False)
        resource = stack['WebServer']

        setup_mock_for_image_constraint(self.m, 'CentOS 5.2')
        self.m.ReplayAll()

        resource.properties = properties.Properties(
            resource.properties_schema,
            {
                'ImageId': 'CentOS 5.2',
                'KeyName': 'test',
                'InstanceType': 'm1.large'
            },
            context=self.ctx)
        stack.validate()

        resource.properties = properties.Properties(
            resource.properties_schema,
            {
                'KeyName': 'test',
                'InstanceType': 'm1.large'
            },
            context=self.ctx)
        self.assertRaises(exception.StackValidationFailed, stack.validate)

    def test_stack_delete(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        s = stack_object.Stack.get_by_id(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')

        parser.Stack.load(self.ctx, stack=s).AndReturn(stack)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def test_stack_delete_nonexist(self):
        stack_name = 'service_delete_nonexist_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.delete_stack,
                               self.ctx, stack.identifier())
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_delete_acquired_lock(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn(self.man.engine_id)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def test_stack_delete_acquired_lock_stop_timers(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn(self.man.engine_id)
        self.m.ReplayAll()

        self.man.thread_group_mgr.add_timer(stack.id, 'test')
        self.assertEqual(1, len(self.man.thread_group_mgr.groups[sid].timers))
        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.assertEqual(0, len(self.man.thread_group_mgr.groups[sid].timers))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def test_stack_delete_current_engine_active_lock(self):
        self.man.start()
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, self.man.engine_id)

        # Create a fake ThreadGroup too
        self.man.thread_group_mgr.groups[stack.id] = DummyThreadGroup()

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn(self.man.engine_id)
        # this is to simulate lock release on DummyThreadGroup stop
        self.m.StubOutWithMock(stack_lock.StackLock, 'acquire')
        stack_lock.StackLock.acquire().AndReturn(None)

        self.m.StubOutWithMock(self.man.thread_group_mgr, 'stop')
        self.man.thread_group_mgr.stop(stack.id).AndReturn(None)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.m.VerifyAll()

    def test_stack_delete_other_engine_active_lock_failed(self):
        self.man.start()
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, "other-engine-fake-uuid")

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")

        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(
            self.ctx, "other-engine-fake-uuid").AndReturn(True)

        self.m.StubOutWithMock(self.man, '_remote_call')
        self.man._remote_call(
            self.ctx, 'other-engine-fake-uuid', 'stop_stack',
            stack_identity=mox.IgnoreArg()
        ).AndReturn(False)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.delete_stack,
                               self.ctx, stack.identifier())
        self.assertEqual(exception.StopActionFailed, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_delete_other_engine_active_lock_succeeded(self):
        self.man.start()
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, "other-engine-fake-uuid")

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")

        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(
            self.ctx, "other-engine-fake-uuid").AndReturn(True)

        self.m.StubOutWithMock(self.man, '_remote_call')
        self.man._remote_call(
            self.ctx, 'other-engine-fake-uuid', 'stop_stack',
            stack_identity=mox.IgnoreArg()).AndReturn(None)

        self.m.StubOutWithMock(stack_lock.StackLock, 'acquire')
        stack_lock.StackLock.acquire().AndReturn(None)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def test_stack_delete_other_dead_engine_active_lock(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        stack_lock_object.StackLock.create(stack.id, "other-engine-fake-uuid")

        st = stack_object.Stack.get_by_id(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")

        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(
            self.ctx, "other-engine-fake-uuid").AndReturn(False)

        self.m.StubOutWithMock(stack_lock.StackLock, 'acquire')
        stack_lock.StackLock.acquire().AndReturn(None)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def _stub_update_mocks(self, stack_to_load, stack_to_return):
        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=stack_to_load
                          ).AndReturn(stack_to_return)

        self.m.StubOutWithMock(templatem, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')

    def test_stack_update(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        old_stack = get_wordpress_stack(stack_name, self.ctx)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stack = get_wordpress_stack(stack_name, self.ctx)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False,
                     current_traversal=None,
                     disable_rollback=True,
                     nested_depth=0,
                     owner_id=None,
                     parent_resource=None,
                     stack_user_project_id='1234',
                     strict_validate=True,
                     tenant_id='test_tenant_id',
                     timeout_mins=60,
                     user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        evt_mock = self.m.CreateMockAnything()
        self.m.StubOutWithMock(grevent, 'Event')
        grevent.Event().AndReturn(evt_mock)
        self.m.StubOutWithMock(threadgroup, 'ThreadGroup')
        threadgroup.ThreadGroup().AndReturn(DummyThreadGroup())

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.assertEqual([evt_mock], self.man.thread_group_mgr.events[sid])
        self.m.VerifyAll()

    def test_stack_update_existing_parameters(self):
        '''Use a template with default parameter and no input parameter
        then update with a template without default and no input
        parameter, using the existing parameter.
        '''
        stack_name = 'service_update_test_stack_existing_parameters'
        no_params = {}
        with_params = {'KeyName': 'foo'}

        old_stack = get_wordpress_stack_no_params(stack_name, self.ctx)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        t = template_format.parse(wp_template_no_default)
        env = environment.Environment({'parameters': with_params,
                                       'resource_registry': {'rsc': 'test'}})
        template = templatem.Template(t, env=env)
        stack = parser.Stack(self.ctx, stack_name, template)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(wp_template_no_default,
                           files=None, env=old_stack.env).AndReturn(stack.t)
        environment.Environment(no_params).AndReturn(old_stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False, current_traversal=None,
                     disable_rollback=True, nested_depth=0,
                     owner_id=None, parent_resource=None,
                     stack_user_project_id='1234',
                     strict_validate=True,
                     tenant_id='test_tenant_id', timeout_mins=60,
                     user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        evt_mock = self.m.CreateMockAnything()
        self.m.StubOutWithMock(grevent, 'Event')
        grevent.Event().AndReturn(evt_mock)
        self.m.StubOutWithMock(threadgroup, 'ThreadGroup')
        threadgroup.ThreadGroup().AndReturn(DummyThreadGroup())

        self.m.ReplayAll()

        api_args = {rpc_api.PARAM_TIMEOUT: 60,
                    rpc_api.PARAM_EXISTING: True}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       wp_template_no_default, no_params,
                                       None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.assertEqual([evt_mock], self.man.thread_group_mgr.events[sid])
        self.m.VerifyAll()

    def test_stack_update_reuses_api_params(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.timeout_mins = 1
        old_stack.disable_rollback = False
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        stack = get_wordpress_stack(stack_name, self.ctx)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False, current_traversal=None,
                     disable_rollback=False, nested_depth=0,
                     owner_id=None, parent_resource=None,
                     stack_user_project_id='1234',
                     strict_validate=True,
                     tenant_id='test_tenant_id', timeout_mins=1,
                     user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.StubOutWithMock(threadgroup, 'ThreadGroup')
        threadgroup.ThreadGroup().AndReturn(DummyThreadGroup())

        self.m.ReplayAll()

        api_args = {}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.m.VerifyAll()

    def test_stack_cancel_update_same_engine(self):
        stack_name = 'service_update_cancel_test_stack'
        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.state_set(old_stack.UPDATE, old_stack.IN_PROGRESS,
                            'test_override')
        old_stack.disable_rollback = False
        old_stack.store()
        load_mock = self.patchobject(parser.Stack, 'load')
        load_mock.return_value = old_stack
        lock_mock = self.patchobject(stack_lock.StackLock, 'try_acquire')
        lock_mock.return_value = self.man.engine_id
        self.patchobject(self.man.thread_group_mgr, 'send')
        self.man.stack_cancel_update(self.ctx, old_stack.identifier())
        self.man.thread_group_mgr.send.assert_called_once_with(old_stack.id,
                                                               'cancel')

    def test_stack_cancel_update_different_engine(self):
        stack_name = 'service_update_cancel_test_stack'
        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.state_set(old_stack.UPDATE, old_stack.IN_PROGRESS,
                            'test_override')
        old_stack.disable_rollback = False
        old_stack.store()
        load_mock = self.patchobject(parser.Stack, 'load')
        load_mock.return_value = old_stack
        lock_mock = self.patchobject(stack_lock.StackLock, 'try_acquire')
        another_engine_has_lock = str(uuid.uuid4())
        lock_mock.return_value = another_engine_has_lock
        self.patchobject(stack_lock.StackLock,
                         'engine_alive').return_value(True)
        self.man.listener = mock.Mock()
        self.man.listener.SEND = 'send'
        self.man._client = messaging.get_rpc_client(
            version=self.man.RPC_API_VERSION)
        # In fact the another engine is not alive, so the call will timeout
        self.assertRaises(dispatcher.ExpectedException,
                          self.man.stack_cancel_update,
                          self.ctx, old_stack.identifier())

    def test_stack_cancel_update_wrong_state_fails(self):
        stack_name = 'service_update_cancel_test_stack'
        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.state_set(old_stack.UPDATE, old_stack.COMPLETE,
                            'test_override')
        old_stack.store()
        load_mock = self.patchobject(parser.Stack, 'load')
        load_mock.return_value = old_stack

        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.stack_cancel_update, self.ctx, old_stack.identifier())

        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertIn("Cancelling update when stack is "
                      "('UPDATE', 'COMPLETE')",
                      six.text_type(ex.exc_info[1]))

    @mock.patch.object(stack_object.Stack, 'count_total_resources')
    def test_stack_update_equals(self, ctr):
        stack_name = 'test_stack_update_equals_resource_limit'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {
                   'A': {'Type': 'GenericResourceType'},
                   'B': {'Type': 'GenericResourceType'},
                   'C': {'Type': 'GenericResourceType'}}}

        template = templatem.Template(tpl)

        old_stack = parser.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)
        ctr.return_value = 3

        stack = parser.Stack(self.ctx, stack_name, template)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False, current_traversal=None,
                     disable_rollback=True, nested_depth=0,
                     owner_id=None, parent_resource=None,
                     stack_user_project_id='1234', strict_validate=True,
                     tenant_id='test_tenant_id',
                     timeout_mins=60, user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.StubOutWithMock(threadgroup, 'ThreadGroup')
        threadgroup.ThreadGroup().AndReturn(DummyThreadGroup())

        self.m.ReplayAll()

        cfg.CONF.set_override('max_resources_per_stack', 3)

        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        root_stack_id = old_stack.root_stack_id()
        self.assertEqual(3, old_stack.total_resources(root_stack_id))
        self.m.VerifyAll()

    def test_stack_update_stack_id_equal(self):
        stack_name = 'test_stack_update_stack_id_equal'
        res._register_class('ResourceWithPropsType',
                            generic_rsrc.ResourceWithProps)
        tpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'A': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'AWS::StackId'}
                    }
                }
            }
        }

        template = templatem.Template(tpl)

        create_stack = parser.Stack(self.ctx, stack_name, template)
        sid = create_stack.store()
        create_stack.create()
        self.assertEqual((create_stack.CREATE, create_stack.COMPLETE),
                         create_stack.state)

        s = stack_object.Stack.get_by_id(self.ctx, sid)

        old_stack = parser.Stack.load(self.ctx, stack=s)

        self.assertEqual((old_stack.CREATE, old_stack.COMPLETE),
                         old_stack.state)
        self.assertEqual(create_stack.identifier().arn(),
                         old_stack['A'].properties['Foo'])

        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(
            self.ctx,
            stack=s).AndReturn(old_stack)

        self.m.ReplayAll()

        result = self.man.update_stack(self.ctx, create_stack.identifier(),
                                       tpl, {}, None, {})

        self.man.thread_group_mgr.groups[sid].wait()

        self.assertEqual((old_stack.UPDATE, old_stack.COMPLETE),
                         old_stack.state)
        self.assertEqual(create_stack.identifier(), result)
        self.assertIsNotNone(create_stack.identifier().stack_id)
        self.assertEqual(create_stack.identifier().arn(),
                         old_stack['A'].properties['Foo'])

        self.assertEqual(create_stack['A'].id, old_stack['A'].id)
        self.man.thread_group_mgr.groups[sid].wait()

        self.m.VerifyAll()

    def test_stack_update_exceeds_resource_limit(self):
        stack_name = 'test_stack_update_exceeds_resource_limit'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources': {
                   'A': {'Type': 'GenericResourceType'},
                   'B': {'Type': 'GenericResourceType'},
                   'C': {'Type': 'GenericResourceType'}}}

        template = templatem.Template(tpl)
        old_stack = parser.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        self.assertIsNotNone(sid)

        cfg.CONF.set_override('max_resources_per_stack', 2)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack, self.ctx,
                               old_stack.identifier(), tpl, params,
                               None, {})
        self.assertEqual(exception.RequestLimitExceeded, ex.exc_info[0])
        self.assertIn(exception.StackResourceLimitExceeded.msg_fmt,
                      six.text_type(ex.exc_info[1]))

    def test_stack_update_verify_err(self):
        stack_name = 'service_update_verify_err_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.store()
        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)
        stack = get_wordpress_stack(stack_name, self.ctx)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=stack.env).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     convergence=False, current_traversal=None,
                     disable_rollback=True, nested_depth=0,
                     owner_id=None, parent_resource=None,
                     stack_user_project_id='1234', strict_validate=True,
                     tenant_id='test_tenant_id',
                     timeout_mins=60, user_creds_id=u'1',
                     username='test_username').AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndRaise(exception.StackValidationFailed(
            message='fubar'))

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.update_stack,
            self.ctx, old_stack.identifier(),
            template, params, None, api_args)
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_update_nonexist(self):
        stack_name = 'service_update_nonexist_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack,
                               self.ctx, stack.identifier(), template,
                               params, None, {})
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_update_no_credentials(self):
        cfg.CONF.set_default('deferred_auth_method', 'password')
        stack_name = 'test_stack_update_no_credentials'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        # force check for credentials on create
        old_stack['WebServer'].requires_deferred_auth = True

        sid = old_stack.store()
        old_stack.set_stack_user_project_id('1234')
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        self.ctx = utils.dummy_context(password=None)

        self.m.StubOutWithMock(self.man, '_get_stack')

        self.man._get_stack(self.ctx, old_stack.identifier()).AndReturn(s)

        self._stub_update_mocks(s, old_stack)

        templatem.Template(template, files=None,
                           env=old_stack.env).AndReturn(old_stack.t)
        environment.Environment(params).AndReturn(old_stack.env)
        parser.Stack(self.ctx, old_stack.name,
                     old_stack.t,
                     convergence=False,
                     current_traversal=None,
                     disable_rollback=True,
                     nested_depth=0,
                     owner_id=None,
                     parent_resource=None,
                     stack_user_project_id='1234',
                     strict_validate=True,
                     tenant_id='test_tenant_id',
                     timeout_mins=60,
                     user_creds_id=u'1',
                     username='test_username').AndReturn(old_stack)

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack, self.ctx,
                               old_stack.identifier(),
                               template, params, None, api_args)
        self.assertEqual(exception.MissingCredentialError, ex.exc_info[0])
        self.assertEqual(
            'Missing required credential: X-Auth-Key',
            six.text_type(ex.exc_info[1]))

        self.m.VerifyAll()

    def test_validate_deferred_auth_context_trusts(self):
        stack = get_wordpress_stack('test_deferred_auth', self.ctx)
        stack['WebServer'].requires_deferred_auth = True
        ctx = utils.dummy_context(user=None, password=None)
        cfg.CONF.set_default('deferred_auth_method', 'trusts')

        # using trusts, no username or password required
        self.man._validate_deferred_auth_context(ctx, stack)

    def test_validate_deferred_auth_context_not_required(self):
        stack = get_wordpress_stack('test_deferred_auth', self.ctx)
        stack['WebServer'].requires_deferred_auth = False
        ctx = utils.dummy_context(user=None, password=None)
        cfg.CONF.set_default('deferred_auth_method', 'password')

        # stack performs no deferred operations, so no username or
        # password required
        self.man._validate_deferred_auth_context(ctx, stack)

    def test_validate_deferred_auth_context_missing_credentials(self):
        stack = get_wordpress_stack('test_deferred_auth', self.ctx)
        stack['WebServer'].requires_deferred_auth = True
        cfg.CONF.set_default('deferred_auth_method', 'password')

        # missing username
        ctx = utils.dummy_context(user=None)
        ex = self.assertRaises(exception.MissingCredentialError,
                               self.man._validate_deferred_auth_context,
                               ctx, stack)
        self.assertEqual('Missing required credential: X-Auth-User',
                         six.text_type(ex))

        # missing password
        ctx = utils.dummy_context(password=None)
        ex = self.assertRaises(exception.MissingCredentialError,
                               self.man._validate_deferred_auth_context,
                               ctx, stack)
        self.assertEqual('Missing required credential: X-Auth-Key',
                         six.text_type(ex))


class StackServiceUpdateActionsNotSupportedTest(common.HeatTestCase):

    scenarios = [
        ('suspend_in_progress', dict(action='SUSPEND', status='IN_PROGRESS')),
        ('suspend_complete', dict(action='SUSPEND', status='COMPLETE')),
        ('suspend_failed', dict(action='SUSPEND', status='FAILED')),
        ('delete_in_progress', dict(action='DELETE', status='IN_PROGRESS')),
        ('delete_complete', dict(action='DELETE', status='COMPLETE')),
        ('delete_failed', dict(action='DELETE', status='FAILED')),
    ]

    def setUp(self):
        super(StackServiceUpdateActionsNotSupportedTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.patch('heat.engine.service.warnings')
        self.man = service.EngineService('a-host', 'a-topic')

    def test_stack_update_actions_not_supported(self):
        stack_name = '%s-%s' % (self.action, self.status)

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.action = self.action
        old_stack.status = self.status

        sid = old_stack.store()
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

        self.m.ReplayAll()

        params = {'foo': 'bar'}
        template = '{ "Resources": {} }'
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.update_stack,
                               self.ctx, old_stack.identifier(), template,
                               params, None, {})
        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.m.VerifyAll()


class StackServiceActionsTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceActionsTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.patch('heat.engine.service.warnings')
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.create_periodic_tasks()

    def test_stack_suspend(self):
        stack_name = 'service_suspend_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()
        s = stack_object.Stack.get_by_id(self.ctx, sid)

        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(stack)

        thread = self.m.CreateMockAnything()
        thread.link(mox.IgnoreArg(), stack.id).AndReturn(None)
        self.m.StubOutWithMock(service.ThreadGroupManager, 'start')
        service.ThreadGroupManager.start(sid, mox.IgnoreArg(),
                                         stack).AndReturn(thread)
        self.m.ReplayAll()

        result = self.man.stack_suspend(self.ctx, stack.identifier())
        self.assertIsNone(result)

        self.m.VerifyAll()

    @stack_context('service_resume_test_stack', False)
    def test_stack_resume(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        thread = self.m.CreateMockAnything()
        thread.link(mox.IgnoreArg(), self.stack.id).AndReturn(None)
        self.m.StubOutWithMock(service.ThreadGroupManager, 'start')
        service.ThreadGroupManager.start(self.stack.id, mox.IgnoreArg(),
                                         self.stack).AndReturn(thread)

        self.m.ReplayAll()

        result = self.man.stack_resume(self.ctx, self.stack.identifier())
        self.assertIsNone(result)
        self.m.VerifyAll()

    def test_stack_suspend_nonexist(self):
        stack_name = 'service_suspend_nonexist_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.stack_suspend, self.ctx,
                               stack.identifier())
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_resume_nonexist(self):
        stack_name = 'service_resume_nonexist_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.man.stack_resume, self.ctx,
                               stack.identifier())
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def _mock_thread_start(self, stack_id, func, *args, **kwargs):
        func(*args, **kwargs)
        return mock.Mock()

    @mock.patch.object(service.ThreadGroupManager, 'start')
    @mock.patch.object(parser.Stack, 'load')
    def test_stack_check(self, mock_load, mock_start):
        stack = get_wordpress_stack('test_stack_check', self.ctx)
        stack.store()
        stack.check = mock.Mock()
        mock_load.return_value = stack
        mock_start.side_effect = self._mock_thread_start

        self.man.stack_check(self.ctx, stack.identifier())
        self.assertTrue(stack.check.called)


class StackServiceAuthorizeTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceAuthorizeTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.patch('heat.engine.service.warnings')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.engine_id = 'engine-fake-uuid'
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')
        res._register_class('ResourceWithPropsType',
                            generic_rsrc.ResourceWithProps)

    @stack_context('service_authorize_stack_user_nocreds_test_stack')
    def test_stack_authorize_stack_user_nocreds(self):
        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))

    @stack_context('service_authorize_user_attribute_error_test_stack')
    def test_stack_authorize_stack_user_attribute_error(self):
        self.m.StubOutWithMock(json, 'loads')
        json.loads(None).AndRaise(AttributeError)
        self.m.ReplayAll()
        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))
        self.m.VerifyAll()

    @stack_context('service_authorize_stack_user_type_error_test_stack')
    def test_stack_authorize_stack_user_type_error(self):
        self.m.StubOutWithMock(json, 'loads')
        json.loads(mox.IgnoreArg()).AndRaise(TypeError)
        self.m.ReplayAll()

        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))

        self.m.VerifyAll()

    def test_stack_authorize_stack_user(self):
        self.ctx = utils.dummy_context()
        self.ctx.aws_creds = '{"ec2Credentials": {"access": "4567"}}'
        stack = get_stack('stack_authorize_stack_user',
                          self.ctx,
                          user_policy_template)
        self.stack = stack
        fc = setup_mocks(self.m, stack)
        self.m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(fakes_nova.fake_exception())

        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.assertTrue(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))

        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'CfnUser'))

        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'NoSuchResource'))

        self.stack.delete()
        self.m.VerifyAll()

    def test_stack_authorize_stack_user_user_id(self):
        self.ctx = utils.dummy_context(user_id=str(uuid.uuid4()))
        stack = get_stack('stack_authorize_stack_user',
                          self.ctx,
                          server_config_template)
        self.stack = stack

        def handler(resource_name):
            return resource_name == 'WebServer'

        self.stack.register_access_allowed_handler(self.ctx.user_id, handler)

        # matching credential_id and resource_name
        self.assertTrue(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))

        # not matching resource_name
        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'NoSuchResource'))

        # not matching credential_id
        self.ctx.user_id = str(uuid.uuid4())
        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))


class StackServiceTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.patch('heat.engine.service.warnings')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.create_periodic_tasks()
        self.eng.engine_id = 'engine-fake-uuid'
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')
        res._register_class('ResourceWithPropsType',
                            generic_rsrc.ResourceWithProps)

    def test_make_sure_rpc_version(self):
        self.assertEqual(
            '1.7',
            service.EngineService.RPC_API_VERSION,
            ('RPC version is changed, please update this test to new version '
             'and make sure additional test cases are added for RPC APIs '
             'added in new version'))

    @mock.patch.object(service_stack_watch.StackWatch, 'start_watch_task')
    @mock.patch.object(service.stack_object.Stack, 'get_all')
    @mock.patch.object(service.service.Service, 'start')
    def test_start_watches_all_stacks(self, mock_super_start, mock_get_all,
                                      start_watch_task):
        s1 = mock.Mock(id=1)
        s2 = mock.Mock(id=2)
        mock_get_all.return_value = [s1, s2]
        start_watch_task.return_value = None

        self.eng.thread_group_mgr = None
        self.eng.create_periodic_tasks()

        mock_get_all.assert_called_once_with(mock.ANY, tenant_safe=False)
        calls = start_watch_task.call_args_list
        self.assertEqual(2, start_watch_task.call_count)
        self.assertIn(mock.call(1, mock.ANY), calls)
        self.assertIn(mock.call(2, mock.ANY), calls)

    @stack_context('service_identify_test_stack', False)
    def test_stack_identify(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        identity = self.eng.identify_stack(self.ctx, self.stack.name)
        self.assertEqual(self.stack.identifier(), identity)

        self.m.VerifyAll()

    @stack_context('ef0c41a4-644f-447c-ad80-7eecb0becf79', False)
    def test_stack_identify_by_name_in_uuid(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        identity = self.eng.identify_stack(self.ctx, self.stack.name)
        self.assertEqual(self.stack.identifier(), identity)

        self.m.VerifyAll()

    @stack_context('service_identify_uuid_test_stack', False)
    def test_stack_identify_uuid(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        identity = self.eng.identify_stack(self.ctx, self.stack.id)
        self.assertEqual(self.stack.identifier(), identity)

        self.m.VerifyAll()

    def test_stack_identify_nonexist(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.identify_stack, self.ctx, 'wibble')
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

    @stack_context('service_create_existing_test_stack', False)
    def test_stack_create_existing(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.create_stack, self.ctx,
                               self.stack.name, self.stack.t.t, {}, None, {})
        self.assertEqual(exception.StackExists, ex.exc_info[0])

    @stack_context('service_name_tenants_test_stack', False)
    def test_stack_by_name_tenants(self):
        self.assertEqual(
            self.stack.id,
            stack_object.Stack.get_by_name(self.ctx, self.stack.name).id)
        ctx2 = utils.dummy_context(tenant_id='stack_service_test_tenant2')
        self.assertIsNone(stack_object.Stack.get_by_name(
            ctx2,
            self.stack.name))

    @stack_context('service_event_list_test_stack')
    def test_stack_event_list(self):
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier(),
                                         show_deleted=True).AndReturn(s)
        self.m.ReplayAll()

        events = self.eng.list_events(self.ctx, self.stack.identifier())

        self.assertEqual(4, len(events))
        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertIn(ev['resource_name'],
                          ('service_event_list_test_stack', 'WebServer'))

            self.assertIn('physical_resource_id', ev)

            self.assertIn('resource_properties', ev)
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            if ev.get('resource_properties'):
                user_data = ev['resource_properties']['UserData']
                self.assertIn('wordpress', user_data)
                self.assertEqual('F17-x86_64-gold',
                                 ev['resource_properties']['ImageId'])
                self.assertEqual('m1.large',
                                 ev['resource_properties']['InstanceType'])

            self.assertEqual('CREATE', ev['resource_action'])
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_status_reason', ev)
            self.assertIn(ev['resource_status_reason'],
                          ('state changed',
                           'Stack CREATE started',
                           'Stack CREATE completed successfully'))

            self.assertIn('resource_type', ev)
            self.assertIn(ev['resource_type'],
                          ('AWS::EC2::Instance', 'OS::Heat::Stack'))

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

        self.m.VerifyAll()

    @stack_context('event_list_deleted_stack')
    def test_stack_event_list_deleted_resource(self):
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)

        thread = self.m.CreateMockAnything()
        thread.link(mox.IgnoreArg(), self.stack.id).AndReturn(None)
        thread.link(mox.IgnoreArg(), self.stack.id,
                    mox.IgnoreArg()).AndReturn(None)

        def run(stack_id, func, *args, **kwargs):
            func(*args)
            return thread
        self.eng.thread_group_mgr.start = run

        new_tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {'AResource': {'Type':
                                                'GenericResourceType'}}}

        self.m.StubOutWithMock(instances.Instance, 'handle_delete')
        instances.Instance.handle_delete()

        self.m.ReplayAll()

        result = self.eng.update_stack(self.ctx, self.stack.identifier(),
                                       new_tmpl, None, None, {})

        # The self.stack reference needs to be updated. Since the underlying
        # stack is updated in update_stack, the original reference is now
        # pointing to an orphaned stack object.
        self.stack = parser.Stack.load(self.ctx, stack_id=result['stack_id'])

        self.assertEqual(result, self.stack.identifier())
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        events = self.eng.list_events(self.ctx, self.stack.identifier())

        self.assertEqual(9, len(events))

        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertIn('physical_resource_id', ev)
            self.assertIn('resource_properties', ev)
            self.assertIn('resource_status_reason', ev)

            self.assertIn(ev['resource_action'],
                          ('CREATE', 'UPDATE', 'DELETE'))
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_type', ev)
            self.assertIn(ev['resource_type'], ('AWS::EC2::Instance',
                                                'GenericResourceType',
                                                'OS::Heat::Stack'))

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

        self.m.VerifyAll()

    @stack_context('service_event_list_test_stack')
    def test_stack_event_list_by_tenant(self):
        events = self.eng.list_events(self.ctx, None)

        self.assertEqual(4, len(events))
        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertIn(ev['resource_name'],
                          ('WebServer', 'service_event_list_test_stack'))

            self.assertIn('physical_resource_id', ev)

            self.assertIn('resource_properties', ev)
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            if ev.get('resource_properties'):
                user_data = ev['resource_properties']['UserData']
                self.assertIn('wordpress', user_data)
                self.assertEqual('F17-x86_64-gold',
                                 ev['resource_properties']['ImageId'])
                self.assertEqual('m1.large',
                                 ev['resource_properties']['InstanceType'])

            self.assertEqual('CREATE', ev['resource_action'])
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_status_reason', ev)
            self.assertIn(ev['resource_status_reason'],
                          ('state changed',
                           'Stack CREATE started',
                           'Stack CREATE completed successfully'))

            self.assertIn('resource_type', ev)
            self.assertIn(ev['resource_type'],
                          ('AWS::EC2::Instance', 'OS::Heat::Stack'))

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

        self.m.VerifyAll()

    @mock.patch.object(event_object.Event, 'get_all_by_stack')
    @mock.patch.object(service.EngineService, '_get_stack')
    def test_stack_events_list_passes_marker_and_filters(self,
                                                         mock_get_stack,
                                                         mock_events_get_all):
        limit = object()
        marker = object()
        sort_keys = object()
        sort_dir = object()
        filters = object()
        s = mock.Mock(id=1)
        mock_get_stack.return_value = s
        self.eng.list_events(self.ctx, 1, limit=limit,
                             marker=marker, sort_keys=sort_keys,
                             sort_dir=sort_dir, filters=filters)
        mock_events_get_all.assert_called_once_with(self.ctx,
                                                    1,
                                                    limit=limit,
                                                    sort_keys=sort_keys,
                                                    marker=marker,
                                                    sort_dir=sort_dir,
                                                    filters=filters)

    @mock.patch.object(event_object.Event, 'get_all_by_tenant')
    def test_tenant_events_list_passes_marker_and_filters(
            self, mock_tenant_events_get_all):
        limit = object()
        marker = object()
        sort_keys = object()
        sort_dir = object()
        filters = object()

        self.eng.list_events(self.ctx, None, limit=limit,
                             marker=marker, sort_keys=sort_keys,
                             sort_dir=sort_dir, filters=filters)
        mock_tenant_events_get_all.assert_called_once_with(self.ctx,
                                                           limit=limit,
                                                           sort_keys=sort_keys,
                                                           marker=marker,
                                                           sort_dir=sort_dir,
                                                           filters=filters)

    @stack_context('service_list_all_test_stack')
    def test_stack_list_all(self):
        self.m.StubOutWithMock(parser.Stack, '_from_db')
        parser.Stack._from_db(
            self.ctx, mox.IgnoreArg(),
            resolve_data=False
        ).AndReturn(self.stack)

        self.m.ReplayAll()
        sl = self.eng.list_stacks(self.ctx)

        self.assertEqual(1, len(sl))
        for s in sl:
            self.assertIn('creation_time', s)
            self.assertIn('updated_time', s)
            self.assertIn('stack_identity', s)
            self.assertIsNotNone(s['stack_identity'])
            self.assertIn('stack_name', s)
            self.assertEqual(self.stack.name, s['stack_name'])
            self.assertIn('stack_status', s)
            self.assertIn('stack_status_reason', s)
            self.assertIn('description', s)
            self.assertIn('WordPress', s['description'])

        self.m.VerifyAll()

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_marker_info(self, mock_stack_get_all):
        limit = object()
        marker = object()
        sort_keys = object()
        sort_dir = object()
        self.eng.list_stacks(self.ctx, limit=limit, marker=marker,
                             sort_keys=sort_keys, sort_dir=sort_dir)
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit,
                                                   sort_keys,
                                                   marker,
                                                   sort_dir,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_filtering_info(self, mock_stack_get_all):
        filters = {'foo': 'bar'}
        self.eng.list_stacks(self.ctx, filters=filters)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   filters,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_tenant_safe_defaults_to_true(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   True,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_tenant_safe_info(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, tenant_safe=False)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   False,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_nested(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_nested=True)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   True,
                                                   )

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_deleted(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_deleted=True)
        mock_stack_get_all.assert_called_once_with(mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   mock.ANY,
                                                   True,
                                                   mock.ANY,
                                                   )

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_passes_filter_info(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, filters={'foo': 'bar'})
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters={'foo': 'bar'},
                                                     tenant_safe=mock.ANY,
                                                     show_deleted=False,
                                                     show_nested=False)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_tenant_safe_default_true(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True,
                                                     show_deleted=False,
                                                     show_nested=False)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_passes_tenant_safe_info(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, tenant_safe=False)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=False,
                                                     show_deleted=False,
                                                     show_nested=False)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_show_nested(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_nested=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True,
                                                     show_deleted=False,
                                                     show_nested=True)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stack_show_deleted(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_deleted=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True,
                                                     show_deleted=True,
                                                     show_nested=False)

    @stack_context('service_abandon_stack')
    def test_abandon_stack(self):
        cfg.CONF.set_override('enable_stack_abandon', True)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        expected_res = {
            u'WebServer': {
                'action': 'CREATE',
                'metadata': {},
                'name': u'WebServer',
                'resource_data': {},
                'resource_id': '9999',
                'status': 'COMPLETE',
                'type': u'AWS::EC2::Instance'}}
        self.m.ReplayAll()
        ret = self.eng.abandon_stack(self.ctx, self.stack.identifier())
        self.assertEqual(10, len(ret))
        self.assertEqual('CREATE', ret['action'])
        self.assertEqual('COMPLETE', ret['status'])
        self.assertEqual('service_abandon_stack', ret['name'])
        self.assertEqual({}, ret['files'])
        self.assertIn('id', ret)
        self.assertEqual(expected_res, ret['resources'])
        self.assertEqual(self.stack.t.t, ret['template'])
        self.assertIn('project_id', ret)
        self.assertIn('stack_user_project_id', ret)
        self.assertIn('environment', ret)
        self.assertIn('files', ret)
        self.m.VerifyAll()
        self.eng.thread_group_mgr.groups[self.stack.id].wait()

    def test_stack_describe_nonexistent(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier,
            show_deleted=True).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier)
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_stack_describe_bad_tenant(self):
        non_exist_identifier = identifier.HeatIdentifier(
            'wibble', 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        invalid_tenant_exc = exception.InvalidTenant(target='test',
                                                     actual='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier,
            show_deleted=True).AndRaise(invalid_tenant_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier)
        self.assertEqual(exception.InvalidTenant, ex.exc_info[0])

        self.m.VerifyAll()

    @stack_context('service_describe_test_stack', False)
    def test_stack_describe(self):
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier(),
                                         show_deleted=True).AndReturn(s)
        self.m.ReplayAll()

        sl = self.eng.show_stack(self.ctx, self.stack.identifier())

        self.assertEqual(1, len(sl))

        s = sl[0]
        self.assertIn('creation_time', s)
        self.assertIn('updated_time', s)
        self.assertIn('stack_identity', s)
        self.assertIsNotNone(s['stack_identity'])
        self.assertIn('stack_name', s)
        self.assertEqual(self.stack.name, s['stack_name'])
        self.assertIn('stack_status', s)
        self.assertIn('stack_status_reason', s)
        self.assertIn('description', s)
        self.assertIn('WordPress', s['description'])
        self.assertIn('parameters', s)

        self.m.VerifyAll()

    @stack_context('service_describe_all_test_stack', False)
    def test_stack_describe_all(self):
        sl = self.eng.show_stack(self.ctx, None)

        self.assertEqual(1, len(sl))

        s = sl[0]
        self.assertIn('creation_time', s)
        self.assertIn('updated_time', s)
        self.assertIn('stack_identity', s)
        self.assertIsNotNone(s['stack_identity'])
        self.assertIn('stack_name', s)
        self.assertEqual(self.stack.name, s['stack_name'])
        self.assertIn('stack_status', s)
        self.assertIn('stack_status_reason', s)
        self.assertIn('description', s)
        self.assertIn('WordPress', s['description'])
        self.assertIn('parameters', s)

    def test_list_resource_types(self):
        resources = self.eng.list_resource_types(self.ctx)
        self.assertIsInstance(resources, list)
        self.assertIn('AWS::EC2::Instance', resources)
        self.assertIn('AWS::RDS::DBInstance', resources)

    def test_list_resource_types_deprecated(self):
        resources = self.eng.list_resource_types(self.ctx, "DEPRECATED")
        self.assertEqual(set(['OS::Neutron::RouterGateway',
                              'OS::Heat::CWLiteAlarm',
                              'OS::Heat::HARestarter']), set(resources))

    def test_list_resource_types_supported(self):
        resources = self.eng.list_resource_types(self.ctx, "SUPPORTED")
        self.assertNotIn(['OS::Neutron::RouterGateway'], resources)
        self.assertIn('AWS::EC2::Instance', resources)

    def test_resource_schema(self):
        type_name = 'ResourceWithPropsType'
        expected = {
            'resource_type': type_name,
            'properties': {
                'Foo': {
                    'type': 'string',
                    'required': False,
                    'update_allowed': False,
                    'immutable': False,
                },
                'FooInt': {
                    'type': 'integer',
                    'required': False,
                    'update_allowed': False,
                    'immutable': False,
                },
            },
            'attributes': {
                'foo': {'description': 'A generic attribute'},
                'Foo': {'description': 'Another generic attribute'},
            },
        }

        schema = self.eng.resource_schema(self.ctx, type_name=type_name)
        self.assertEqual(expected, schema)

    def _no_template_file(self, function):
        env = environment.Environment()
        info = environment.ResourceInfo(env.registry,
                                        ['ResourceWithWrongRefOnFile'],
                                        'not_existing.yaml')
        mock_iterable = mock.MagicMock(return_value=iter([info]))
        with mock.patch('heat.engine.environment.ResourceRegistry.iterable_by',
                        new=mock_iterable):
            ex = self.assertRaises(exception.StackValidationFailed,
                                   function,
                                   self.ctx,
                                   type_name='ResourceWithWrongRefOnFile')
            msg = 'Could not fetch remote template "not_existing.yaml"'
            self.assertIn(msg, six.text_type(ex))

    def test_resource_schema_no_template_file(self):
        self._no_template_file(self.eng.resource_schema)

    def test_generate_template_no_template_file(self):
        self._no_template_file(self.eng.generate_template)

    def test_resource_schema_nonexist(self):
        ex = self.assertRaises(exception.ResourceTypeNotFound,
                               self.eng.resource_schema,
                               self.ctx, type_name='Bogus')
        msg = 'The Resource Type (Bogus) could not be found.'
        self.assertEqual(msg, six.text_type(ex))

    def _test_describe_stack_resource(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        r = self.eng.describe_stack_resource(self.ctx, self.stack.identifier(),
                                             'WebServer', with_attr=None)

        self.assertIn('resource_identity', r)
        self.assertIn('description', r)
        self.assertIn('updated_time', r)
        self.assertIn('stack_identity', r)
        self.assertIsNotNone(r['stack_identity'])
        self.assertIn('stack_name', r)
        self.assertEqual(self.stack.name, r['stack_name'])
        self.assertIn('metadata', r)
        self.assertIn('resource_status', r)
        self.assertIn('resource_status_reason', r)
        self.assertIn('resource_type', r)
        self.assertIn('physical_resource_id', r)
        self.assertIn('resource_name', r)
        self.assertIn('attributes', r)
        self.assertEqual('WebServer', r['resource_name'])

        self.m.VerifyAll()

    @stack_context('service_stack_resource_describe__test_stack')
    def test_stack_resource_describe(self):
        self._test_describe_stack_resource()

    def test_stack_resource_describe_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id,
            'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

        self.m.VerifyAll()

    @stack_context('service_resource_describe_nonexist_test_stack')
    def test_stack_resource_describe_nonexist_resource(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])

        self.m.VerifyAll()

    @stack_context('service_resource_describe_noncreated_test_stack',
                   create_res=False)
    def test_stack_resource_describe_noncreated_resource(self):
        self._test_describe_stack_resource()

    @stack_context('service_resource_describe_user_deny_test_stack')
    def test_stack_resource_describe_stack_user_deny(self):
        self.ctx.roles = [cfg.CONF.heat_stack_user_role]
        self.m.StubOutWithMock(service.EngineService, '_authorize_stack_user')
        service.EngineService._authorize_stack_user(self.ctx, mox.IgnoreArg(),
                                                    'foo').AndReturn(False)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(exception.Forbidden, ex.exc_info[0])

        self.m.VerifyAll()

    @stack_context('service_resources_describe_test_stack')
    def test_stack_resources_describe(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        resources = self.eng.describe_stack_resources(self.ctx,
                                                      self.stack.identifier(),
                                                      'WebServer')

        self.assertEqual(1, len(resources))
        r = resources[0]
        self.assertIn('resource_identity', r)
        self.assertIn('description', r)
        self.assertIn('updated_time', r)
        self.assertIn('stack_identity', r)
        self.assertIsNotNone(r['stack_identity'])
        self.assertIn('stack_name', r)
        self.assertEqual(self.stack.name, r['stack_name'])
        self.assertIn('resource_status', r)
        self.assertIn('resource_status_reason', r)
        self.assertIn('resource_type', r)
        self.assertIn('physical_resource_id', r)
        self.assertIn('resource_name', r)
        self.assertEqual('WebServer', r['resource_name'])

        self.m.VerifyAll()

    @stack_context('service_resources_describe_no_filter_test_stack')
    def test_stack_resources_describe_no_filter(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        resources = self.eng.describe_stack_resources(self.ctx,
                                                      self.stack.identifier(),
                                                      None)

        self.assertEqual(1, len(resources))
        r = resources[0]
        self.assertIn('resource_name', r)
        self.assertEqual('WebServer', r['resource_name'])

        self.m.VerifyAll()

    def test_stack_resources_describe_bad_lookup(self):
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, None).AndRaise(TypeError)
        self.m.ReplayAll()

        self.assertRaises(TypeError,
                          self.eng.describe_stack_resources,
                          self.ctx, None, 'WebServer')
        self.m.VerifyAll()

    def test_stack_resources_describe_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.describe_stack_resources,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

    @stack_context('find_phys_res_stack')
    def test_find_physical_resource(self):
        resources = self.eng.describe_stack_resources(self.ctx,
                                                      self.stack.identifier(),
                                                      None)
        phys_id = resources[0]['physical_resource_id']

        result = self.eng.find_physical_resource(self.ctx, phys_id)
        self.assertIsInstance(result, dict)
        resource_identity = identifier.ResourceIdentifier(**result)
        self.assertEqual(self.stack.identifier(), resource_identity.stack())
        self.assertEqual('WebServer', resource_identity.resource_name)

    def test_find_physical_resource_nonexist(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.find_physical_resource,
                               self.ctx, 'foo')
        self.assertEqual(exception.PhysicalResourceNotFound, ex.exc_info[0])

    @stack_context('service_resources_list_test_stack')
    def test_stack_resources_list(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier())

        self.assertEqual(1, len(resources))
        r = resources[0]
        self.assertIn('resource_identity', r)
        self.assertIn('updated_time', r)
        self.assertIn('physical_resource_id', r)
        self.assertIn('resource_name', r)
        self.assertEqual('WebServer', r['resource_name'])
        self.assertIn('resource_status', r)
        self.assertIn('resource_status_reason', r)
        self.assertIn('resource_type', r)

        self.m.VerifyAll()

    @mock.patch.object(parser.Stack, 'load')
    @stack_context('service_resources_list_test_stack_with_depth')
    def test_stack_resources_list_with_depth(self, mock_load):
        mock_load.return_value = self.stack
        resources = self.stack.values()
        self.stack.iter_resources = mock.Mock(return_value=resources)
        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier(),
                                                  2)
        self.stack.iter_resources.assert_called_once_with(2)

    @mock.patch.object(parser.Stack, 'load')
    @stack_context('service_resources_list_test_stack_with_max_depth')
    def test_stack_resources_list_with_max_depth(self, mock_load):
        mock_load.return_value = self.stack
        resources = self.stack.values()
        self.stack.iter_resources = mock.Mock(return_value=resources)
        resources = self.eng.list_stack_resources(self.ctx,
                                                  self.stack.identifier(),
                                                  99)
        max_depth = cfg.CONF.max_nested_stack_depth
        self.stack.iter_resources.assert_called_once_with(max_depth)

    @mock.patch.object(parser.Stack, 'load')
    def test_stack_resources_list_deleted_stack(self, mock_load):
        stack = setup_stack('resource_list_test_deleted_stack', self.ctx)
        stack_id = stack.identifier()
        mock_load.return_value = stack
        clean_up_stack(stack)
        resources = self.eng.list_stack_resources(self.ctx, stack_id)
        self.assertEqual(1, len(resources))

        res = resources[0]
        self.assertEqual('DELETE', res['resource_action'])
        self.assertEqual('COMPLETE', res['resource_status'])

    def test_stack_resources_list_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier, show_deleted=True
        ).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.list_stack_resources,
                               self.ctx, non_exist_identifier)
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])

        self.m.VerifyAll()

    def test_signal_reception_async(self):
        stack = get_stack('signal_reception',
                          self.ctx,
                          policy_template)
        self.stack = stack
        setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_data = {'food': 'yum'}

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        # Mock out the aync work of thread starting
        self.eng.thread_group_mgr.groups[stack.id] = DummyThreadGroup()
        self.m.StubOutWithMock(self.eng.thread_group_mgr, 'start')
        self.eng.thread_group_mgr.start(stack.id,
                                        mox.IgnoreArg(),
                                        mox.IgnoreArg(),
                                        mox.IgnoreArg(),
                                        mox.IgnoreArg()).AndReturn(None)

        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy',
                                 test_data)

        self.m.VerifyAll()

        self.stack.delete()

    def test_signal_reception_sync(self):
        stack = get_stack('signal_reception',
                          self.ctx,
                          policy_template)
        self.stack = stack
        setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_data = {'food': 'yum'}

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy',
                                 test_data,
                                 sync_call=True)

        self.m.VerifyAll()
        self.stack.delete()

    def test_signal_reception_no_resource(self):
        stack = get_stack('signal_reception_no_resource',
                          self.ctx,
                          policy_template)
        setup_keystone_mocks(self.m, stack)
        self.stack = stack
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_data = {'food': 'yum'}

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'resource_does_not_exist',
                               test_data)
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])
        self.m.VerifyAll()
        self.stack.delete()

    def test_signal_reception_unavailable_resource(self):
        stack = get_stack('signal_reception_unavailable_resource',
                          self.ctx,
                          policy_template)
        stack.store()
        self.stack = stack
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(
            self.ctx, stack=mox.IgnoreArg(),
            use_stored_context=mox.IgnoreArg()
        ).AndReturn(self.stack)
        self.m.ReplayAll()

        test_data = {'food': 'yum'}
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'WebServerScaleDownPolicy',
                               test_data)
        self.assertEqual(exception.ResourceNotAvailable, ex.exc_info[0])
        self.m.VerifyAll()
        self.stack.delete()

    def test_signal_returns_metadata(self):
        stack = get_stack('signal_reception',
                          self.ctx,
                          policy_template)
        self.stack = stack
        setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        test_metadata = {'food': 'yum'}
        rsrc = stack['WebServerScaleDownPolicy']
        rsrc.metadata_set(test_metadata)

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()

        md = self.eng.resource_signal(self.ctx,
                                      dict(self.stack.identifier()),
                                      'WebServerScaleDownPolicy', None)

        self.eng.thread_group_mgr.groups[stack.id].wait()
        self.assertIsNone(md)
        self.m.VerifyAll()

    @stack_context('service_metadata_test_stack')
    def test_metadata(self):
        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        pre_update_meta = self.stack['WebServer'].metadata_get()

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)
        self.m.StubOutWithMock(instances.Instance, 'metadata_update')
        instances.Instance.metadata_update(new_metadata=test_metadata)
        self.m.ReplayAll()

        result = self.eng.metadata_update(self.ctx,
                                          dict(self.stack.identifier()),
                                          'WebServer', test_metadata)
        # metadata_update is a no-op for all resources except
        # WaitConditionHandle so we don't expect this to have changed
        self.assertEqual(pre_update_meta, result)

        self.m.VerifyAll()

    def test_metadata_err_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.metadata_update,
                               self.ctx, non_exist_identifier,
                               'WebServer', test_metadata)
        self.assertEqual(exception.StackNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    @stack_context('service_metadata_err_resource_test_stack', False)
    def test_metadata_err_resource(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.metadata_update,
                               self.ctx, dict(self.stack.identifier()),
                               'NooServer', test_metadata)
        self.assertEqual(exception.ResourceNotFound, ex.exc_info[0])

        self.m.VerifyAll()

    @stack_context('service_show_watch_test_stack', False)
    def test_show_watch(self):
        # Insert two dummy watch rules into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = []
        self.wr.append(watchrule.WatchRule(context=self.ctx,
                                           watch_name='show_watch_1',
                                           rule=rule,
                                           watch_data=[],
                                           stack_id=self.stack.id,
                                           state='NORMAL'))
        self.wr[0].store()

        self.wr.append(watchrule.WatchRule(context=self.ctx,
                                           watch_name='show_watch_2',
                                           rule=rule,
                                           watch_data=[],
                                           stack_id=self.stack.id,
                                           state='NORMAL'))
        self.wr[1].store()

        # watch_name=None should return all watches
        result = self.eng.show_watch(self.ctx, watch_name=None)
        result_names = [r.get('name') for r in result]
        self.assertIn('show_watch_1', result_names)
        self.assertIn('show_watch_2', result_names)

        result = self.eng.show_watch(self.ctx, watch_name="show_watch_1")
        self.assertEqual(1, len(result))
        self.assertIn('name', result[0])
        self.assertEqual('show_watch_1', result[0]['name'])

        result = self.eng.show_watch(self.ctx, watch_name="show_watch_2")
        self.assertEqual(1, len(result))
        self.assertIn('name', result[0])
        self.assertEqual('show_watch_2', result[0]['name'])

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_watch,
                               self.ctx, watch_name="nonexistent")
        self.assertEqual(exception.WatchRuleNotFound, ex.exc_info[0])

        # Check the response has all keys defined in the engine API
        for key in rpc_api.WATCH_KEYS:
            self.assertIn(key, result[0])

    @stack_context('service_show_watch_metric_test_stack', False)
    def test_show_watch_metric(self):
        # Insert dummy watch rule into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='show_watch_metric_1',
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack.id,
                                      state='NORMAL')
        self.wr.store()

        # And add a metric datapoint
        watch = watch_rule_object.WatchRule.get_by_name(self.ctx,
                                                        'show_watch_metric_1')
        self.assertIsNotNone(watch)
        values = {'watch_rule_id': watch.id,
                  'data': {u'Namespace': u'system/linux',
                           u'ServiceFailure': {
                               u'Units': u'Counter', u'Value': 1}}}
        watch_data_object.WatchData.create(self.ctx, values)

        # Check there is one result returned
        result = self.eng.show_watch_metric(self.ctx,
                                            metric_namespace=None,
                                            metric_name=None)
        self.assertEqual(1, len(result))

        # Create another metric datapoint and check we get two
        watch_data_object.WatchData.create(self.ctx, values)
        result = self.eng.show_watch_metric(self.ctx,
                                            metric_namespace=None,
                                            metric_name=None)
        self.assertEqual(2, len(result))

        # Check the response has all keys defined in the engine API
        for key in rpc_api.WATCH_DATA_KEYS:
            self.assertIn(key, result[0])

    @stack_context('service_show_watch_state_test_stack')
    def test_set_watch_state(self):
        # Insert dummy watch rule into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='OverrideAlarm',
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack.id,
                                      state='NORMAL')
        self.wr.store()

        class DummyAction(object):
            def signal(self):
                return "dummyfoo"

        dummy_action = DummyAction()
        self.m.StubOutWithMock(parser.Stack, 'resource_by_refid')
        parser.Stack.resource_by_refid(
            'WebServerRestartPolicy').AndReturn(dummy_action)

        # Replace the real stack threadgroup with a dummy one, so we can
        # check the function returned on ALARM is correctly scheduled
        self.eng.thread_group_mgr.groups[self.stack.id] = DummyThreadGroup()

        self.m.ReplayAll()

        state = watchrule.WatchRule.NODATA
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[rpc_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [], self.eng.thread_group_mgr.groups[self.stack.id].threads)

        state = watchrule.WatchRule.NORMAL
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[rpc_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [], self.eng.thread_group_mgr.groups[self.stack.id].threads)

        state = watchrule.WatchRule.ALARM
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[rpc_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [dummy_action.signal],
            self.eng.thread_group_mgr.groups[self.stack.id].threads)

        self.m.VerifyAll()

    @stack_context('service_show_watch_state_badstate_test_stack')
    def test_set_watch_state_badstate(self):
        # Insert dummy watch rule into the DB
        rule = {u'EvaluationPeriods': u'1',
                u'AlarmActions': [u'WebServerRestartPolicy'],
                u'AlarmDescription': u'Restart the WikiDatabase',
                u'Namespace': u'system/linux',
                u'Period': u'300',
                u'ComparisonOperator': u'GreaterThanThreshold',
                u'Statistic': u'SampleCount',
                u'Threshold': u'2',
                u'MetricName': u'ServiceFailure'}
        self.wr = watchrule.WatchRule(context=self.ctx,
                                      watch_name='OverrideAlarm2',
                                      rule=rule,
                                      watch_data=[],
                                      stack_id=self.stack.id,
                                      state='NORMAL')
        self.wr.store()

        self.m.StubOutWithMock(watchrule.WatchRule, 'set_watch_state')
        for state in ["HGJHGJHG", "1234", "!\*(&%"]:
            watchrule.WatchRule.set_watch_state(
                state).InAnyOrder().AndRaise(ValueError)
        self.m.ReplayAll()

        for state in ["HGJHGJHG", "1234", "!\*(&%"]:
            self.assertRaises(ValueError,
                              self.eng.set_watch_state,
                              self.ctx, watch_name="OverrideAlarm2",
                              state=state)

        self.m.VerifyAll()

    def test_set_watch_state_noexist(self):
        state = watchrule.WatchRule.ALARM   # State valid

        self.m.StubOutWithMock(watchrule.WatchRule, 'load')
        watchrule.WatchRule.load(
            self.ctx, "nonexistent"
        ).AndRaise(exception.WatchRuleNotFound(watch_name='test'))
        self.m.ReplayAll()

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.set_watch_state,
                               self.ctx, watch_name="nonexistent",
                               state=state)
        self.assertEqual(exception.WatchRuleNotFound, ex.exc_info[0])
        self.m.VerifyAll()

    def test_signal_calls_metadata_update(self):
        stack = get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stack
        setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        self.m.StubOutWithMock(res.Resource, 'metadata_update')
        # this will be called once for the Random resource
        res.Resource.metadata_update().AndReturn(None)
        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy', None,
                                 sync_call=True)
        self.m.VerifyAll()
        self.stack.delete()

    def test_signal_no_calls_metadata_update(self):
        stack = get_stack('signal_reception', self.ctx, policy_template)
        self.stack = stack
        setup_keystone_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()

        res.Resource.signal_needs_metadata_updates = False

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        # this will never be called
        self.m.StubOutWithMock(res.Resource, 'metadata_update')
        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy', None,
                                 sync_call=True)
        self.m.VerifyAll()
        self.stack.delete()
        res.Resource.signal_needs_metadata_updates = True

    def test_stack_list_all_empty(self):
        sl = self.eng.list_stacks(self.ctx)

        self.assertEqual(0, len(sl))

    def test_stack_describe_all_empty(self):
        sl = self.eng.show_stack(self.ctx, None)

        self.assertEqual(0, len(sl))

    def test_lazy_load_resources(self):
        stack_name = 'lazy_load_test'
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)

        lazy_load_template = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'foo'},
                    }
                }
            }
        }
        templ = templatem.Template(lazy_load_template)
        stack = parser.Stack(self.ctx, stack_name, templ)

        self.assertIsNone(stack._resources)
        self.assertIsNone(stack._dependencies)

        resources = stack.resources
        self.assertIsInstance(resources, dict)
        self.assertEqual(2, len(resources))
        self.assertIsInstance(resources.get('foo'),
                              generic_rsrc.GenericResource)
        self.assertIsInstance(resources.get('bar'),
                              generic_rsrc.ResourceWithProps)

        stack_dependencies = stack.dependencies
        self.assertIsInstance(stack_dependencies, dependencies.Dependencies)
        self.assertEqual(2, len(stack_dependencies.graph()))

    def _preview_stack(self):
        res._register_class('GenericResource1', generic_rsrc.GenericResource)
        res._register_class('GenericResource2', generic_rsrc.GenericResource)

        args = {}
        params = {}
        files = None
        stack_name = 'SampleStack'
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Description': 'Lorem ipsum.',
               'Resources': {
                   'SampleResource1': {'Type': 'GenericResource1'},
                   'SampleResource2': {'Type': 'GenericResource2'}}}

        return self.eng.preview_stack(self.ctx, stack_name, tpl,
                                      params, files, args)

    def test_preview_stack_returns_a_stack(self):
        stack = self._preview_stack()
        expected_identity = {'path': '',
                             'stack_id': 'None',
                             'stack_name': 'SampleStack',
                             'tenant': 'stack_service_test_tenant'}
        self.assertEqual(expected_identity, stack['stack_identity'])
        self.assertEqual('SampleStack', stack['stack_name'])
        self.assertEqual('Lorem ipsum.', stack['description'])

    def test_preview_stack_returns_list_of_resources_in_stack(self):
        stack = self._preview_stack()
        self.assertIsInstance(stack['resources'], list)
        self.assertEqual(2, len(stack['resources']))

        resource_types = (r['resource_type'] for r in stack['resources'])
        self.assertIn('GenericResource1', resource_types)
        self.assertIn('GenericResource2', resource_types)

        resource_names = (r['resource_name'] for r in stack['resources'])
        self.assertIn('SampleResource1', resource_names)
        self.assertIn('SampleResource2', resource_names)

    def test_preview_stack_validates_new_stack(self):
        exc = exception.StackExists(stack_name='Validation Failed')
        self.eng._validate_new_stack = mock.Mock(side_effect=exc)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._preview_stack)
        self.assertEqual(exception.StackExists, ex.exc_info[0])

    @mock.patch.object(service.api, 'format_stack_preview', new=mock.Mock())
    @mock.patch.object(service.parser, 'Stack')
    def test_preview_stack_checks_stack_validity(self, mock_parser):
        exc = exception.StackValidationFailed(message='Validation Failed')
        mock_parsed_stack = mock.Mock()
        mock_parsed_stack.validate.side_effect = exc
        mock_parser.return_value = mock_parsed_stack
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._preview_stack)
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])

    @mock.patch.object(service.stack_object.Stack, 'get_by_name')
    def test_validate_new_stack_checks_existing_stack(self, mock_stack_get):
        mock_stack_get.return_value = 'existing_db_stack'
        tmpl = templatem.Template(
            {'HeatTemplateFormatVersion': '2012-12-12'})
        self.assertRaises(exception.StackExists, self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', tmpl)

    @mock.patch.object(service.stack_object.Stack, 'count_all')
    def test_validate_new_stack_checks_stack_limit(self, mock_db_count):
        cfg.CONF.set_override('max_stacks_per_tenant', 99)
        mock_db_count.return_value = 99
        template = templatem.Template(
            {'HeatTemplateFormatVersion': '2012-12-12'})
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', template)

    def test_validate_new_stack_checks_incorrect_keywords_in_resource(self):
        template = {'heat_template_version': '2013-05-23',
                    'resources': {
                        'Res': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.eng._validate_new_stack,
                               self.ctx, 'test_existing_stack',
                               parsed_template)
        msg = (u'u\'"Type" is not a valid keyword '
               'inside a resource definition\'')
        self.assertEqual(msg, six.text_type(ex))

    def test_validate_new_stack_checks_incorrect_sections(self):
        template = {'heat_template_version': '2013-05-23',
                    'unknown_section': {
                        'Res': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.eng._validate_new_stack,
                               self.ctx, 'test_existing_stack',
                               parsed_template)
        msg = u'The template section is invalid: unknown_section'
        self.assertEqual(msg, six.text_type(ex))

    def test_validate_new_stack_checks_resource_limit(self):
        cfg.CONF.set_override('max_resources_per_stack', 5)
        template = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {
                        'Res1': {'Type': 'GenericResource1'},
                        'Res2': {'Type': 'GenericResource1'},
                        'Res3': {'Type': 'GenericResource1'},
                        'Res4': {'Type': 'GenericResource1'},
                        'Res5': {'Type': 'GenericResource1'},
                        'Res6': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', parsed_template)

    @mock.patch.object(service_objects.Service, 'get_all')
    @mock.patch.object(service_utils, 'format_service')
    def test_service_get_all(self, mock_format_service, mock_get_all):
        mock_get_all.return_value = [mock.Mock()]
        mock_format_service.return_value = mock.Mock()
        self.assertEqual(1, len(self.eng.list_services(self.ctx)))
        self.assertTrue(mock_get_all.called)
        mock_format_service.assert_called_once_with(mock.ANY)

    @mock.patch.object(service_objects.Service, 'update_by_id')
    @mock.patch.object(service_objects.Service, 'create')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_start(self,
                                         mock_admin_context,
                                         mock_service_create,
                                         mock_service_update):
        self.eng.service_id = None
        mock_admin_context.return_value = self.ctx
        srv = dict(id='mock_id')
        mock_service_create.return_value = srv
        self.eng.service_manage_report()
        mock_admin_context.assert_called_once_with()
        mock_service_create.assert_called_once_with(
            self.ctx,
            dict(host=self.eng.host,
                 hostname=self.eng.hostname,
                 binary=self.eng.binary,
                 engine_id=self.eng.engine_id,
                 topic=self.eng.topic,
                 report_interval=cfg.CONF.periodic_interval))
        self.assertEqual(self.eng.service_id, srv['id'])
        mock_service_update.assert_called_once_with(
            self.ctx,
            self.eng.service_id,
            dict(deleted_at=None))

    @mock.patch.object(service_objects.Service, 'get_all_by_args')
    @mock.patch.object(service_objects.Service, 'delete')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_cleanup(self,
                                           mock_admin_context,
                                           mock_service_delete,
                                           mock_get_all):
        mock_admin_context.return_value = self.ctx
        ages_a_go = datetime.datetime.utcnow() - datetime.timedelta(
            seconds=4000)
        mock_get_all.return_value = [{'id': 'foo',
                                      'deleted_at': None,
                                      'updated_at': ages_a_go}]
        self.eng.service_manage_cleanup()
        mock_admin_context.assert_called_once_with()
        mock_get_all.assert_called_once_with(self.ctx,
                                             self.eng.host,
                                             self.eng.binary,
                                             self.eng.hostname)
        mock_service_delete.assert_called_once_with(
            self.ctx, 'foo')

    @mock.patch.object(service_objects.Service, 'update_by_id')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_update(
            self,
            mock_admin_context,
            mock_service_update):
        self.eng.service_id = 'mock_id'
        mock_admin_context.return_value = self.ctx
        self.eng.service_manage_report()
        mock_admin_context.assert_called_once_with()
        mock_service_update.assert_called_once_with(
            self.ctx,
            'mock_id',
            dict(deleted_at=None))

    @mock.patch.object(service_objects.Service, 'update_by_id')
    @mock.patch.object(context, 'get_admin_context')
    def test_service_manage_report_update_fail(
            self,
            mock_admin_context,
            mock_service_update):
        self.eng.service_id = 'mock_id'
        mock_admin_context.return_value = self.ctx
        mock_service_update.side_effect = Exception()
        self.eng.service_manage_report()
        msg = 'Service %s update failed' % self.eng.service_id
        self.assertIn(msg, self.LOG.output)

    def test_stop_rpc_server(self):
        with mock.patch.object(self.eng,
                               '_rpc_server') as mock_rpc_server:
            self.eng._stop_rpc_server()
            mock_rpc_server.stop.assert_called_once_with()
            mock_rpc_server.wait.assert_called_once_with()

    def _test_engine_service_start(
            self,
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method):
        self.patchobject(self.eng, 'service_manage_cleanup')
        self.patchobject(self.eng, 'reset_stack_status')
        self.eng.start()

        # engine id
        sample_uuid_method.assert_called_once_with()
        sampe_uuid = sample_uuid_method.return_value
        self.assertEqual(sampe_uuid,
                         self.eng.engine_id,
                         'Failed to generated engine_id')

        # Thread group manager
        thread_group_manager_class.assert_called_once_with()
        thread_group_manager = thread_group_manager_class.return_value
        self.assertEqual(thread_group_manager,
                         self.eng.thread_group_mgr,
                         'Failed to create Thread Group Manager')

        # Engine Listener
        engine_listener_class.assert_called_once_with(
            self.eng.host,
            self.eng.engine_id,
            self.eng.thread_group_mgr
        )
        engine_lister = engine_listener_class.return_value
        engine_lister.start.assert_called_once_with()

        # Worker Service
        if cfg.CONF.convergence_engine:
            worker_service_class.assert_called_once_with(
                host=self.eng.host,
                topic=worker_api.TOPIC,
                engine_id=self.eng.engine_id,
                thread_group_mgr=self.eng.thread_group_mgr
            )
            worker_service = worker_service_class.return_value
            worker_service.start.assert_called_once_with()

        # RPC Target
        target_class.assert_called_once_with(
            version=service.EngineService.RPC_API_VERSION,
            server=self.eng.host,
            topic=self.eng.topic)

        # RPC server
        target = target_class.return_value
        rpc_server_method.assert_called_once_with(target,
                                                  self.eng)
        rpc_server = rpc_server_method.return_value
        self.assertEqual(rpc_server,
                         self.eng._rpc_server,
                         "Failed to create RPC server")

        rpc_server.start.assert_called_once_with()

        # RPC client
        rpc_client = rpc_client_class.return_value
        rpc_client_class.assert_called_once_with(
            version=service.EngineService.RPC_API_VERSION)
        self.assertEqual(rpc_client,
                         self.eng._client,
                         "Failed to create RPC client")

        # Manage Thread group
        thread_group_class.assert_called_once_with()
        manage_thread_group = thread_group_class.return_value
        manage_thread_group.add_timer.assert_called_once_with(
            cfg.CONF.periodic_interval,
            self.eng.service_manage_report
        )

    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch.object(stack_object.Stack, 'get_all')
    @mock.patch('heat.engine.stack_lock.StackLock',
                return_value=mock.Mock())
    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(context, 'get_admin_context')
    def test_engine_reset_stack_status(
            self,
            mock_admin_context,
            mock_stack_load,
            mock_stacklock,
            mock_get_all,
            mock_thread):
        mock_admin_context.return_value = self.ctx

        db_stack = mock.MagicMock()
        db_stack.id = 'foo'
        db_stack.status = 'IN_PROGRESS'
        db_stack.status_reason = None
        mock_get_all.return_value = [db_stack]

        fake_stack = mock.MagicMock()
        fake_stack.action = 'CREATE'
        fake_stack.id = 'foo'
        fake_stack.status = 'IN_PROGRESS'
        fake_stack.state_set.return_value = None
        mock_stack_load.return_value = fake_stack

        fake_lock = mock.MagicMock()
        fake_lock.get_engine_id.return_value = 'old-engine'
        fake_lock.acquire.return_value = None
        mock_stacklock.return_value = fake_lock

        self.eng.thread_group_mgr = mock_thread

        self.eng.reset_stack_status()

        mock_admin_context.assert_called_once_with()
        filters = {'status': parser.Stack.IN_PROGRESS}
        mock_get_all.assert_called_once_with(self.ctx,
                                             filters=filters,
                                             tenant_safe=False)
        mock_stack_load.assert_called_once_with(self.ctx,
                                                stack=db_stack,
                                                use_stored_context=True)
        mock_thread.start_with_acquired_lock.assert_called_once_with(
            fake_stack, fake_lock, fake_stack.state_set, fake_stack.action,
            fake_stack.FAILED, 'Engine went down during stack CREATE'
        )

    @mock.patch('heat.common.messaging.get_rpc_server',
                return_value=mock.Mock())
    @mock.patch('oslo_messaging.Target',
                return_value=mock.Mock())
    @mock.patch('heat.common.messaging.get_rpc_client',
                return_value=mock.Mock())
    @mock.patch('heat.engine.stack_lock.StackLock.generate_engine_id',
                return_value='sample-uuid')
    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.EngineListener',
                return_value=mock.Mock())
    @mock.patch('heat.openstack.common.threadgroup.ThreadGroup',
                return_value=mock.Mock())
    def test_engine_service_start_in_non_convergence_mode(
            self,
            thread_group_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method):
        cfg.CONF.set_default('convergence_engine', False)
        self._test_engine_service_start(
            thread_group_class,
            None,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method
        )

    @mock.patch('heat.common.messaging.get_rpc_server',
                return_value=mock.Mock())
    @mock.patch('oslo_messaging.Target',
                return_value=mock.Mock())
    @mock.patch('heat.common.messaging.get_rpc_client',
                return_value=mock.Mock())
    @mock.patch('heat.engine.stack_lock.StackLock.generate_engine_id',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch('heat.engine.service.EngineListener',
                return_value=mock.Mock())
    @mock.patch('heat.engine.worker.WorkerService',
                return_value=mock.Mock())
    @mock.patch('heat.openstack.common.threadgroup.ThreadGroup',
                return_value=mock.Mock())
    def test_engine_service_start_in_convergence_mode(
            self,
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method):
        cfg.CONF.set_default('convergence_engine', True)
        self._test_engine_service_start(
            thread_group_class,
            worker_service_class,
            engine_listener_class,
            thread_group_manager_class,
            sample_uuid_method,
            rpc_client_class,
            target_class,
            rpc_server_method
        )

    def _test_engine_service_stop(
            self,
            service_delete_method,
            admin_context_method):
        cfg.CONF.set_default('periodic_interval', 60)
        self.patchobject(self.eng, 'service_manage_cleanup')
        self.patchobject(self.eng, 'reset_stack_status')

        self.eng.start()
        # Add dummy thread group to test thread_group_mgr.stop() is executed?
        self.eng.thread_group_mgr.groups['sample-uuid'] = DummyThreadGroup()
        self.eng.service_id = 'sample-service-uuid'

        self.eng.stop()

        # RPC server
        self.eng._stop_rpc_server.assert_called_once_with()

        if cfg.CONF.convergence_engine:
            # WorkerService
            self.eng.worker_service.stop.assert_called_once_with()

        # Wait for all active threads to be finished
        self.eng.thread_group_mgr.stop.assert_called_with(
            'sample-uuid',
            True)

        # # Manage Thread group
        self.eng.manage_thread_grp.stop.assert_called_with(False)

        # Service delete
        admin_context_method.assert_called_once_with()
        ctxt = admin_context_method.return_value
        service_delete_method.assert_called_once_with(
            ctxt,
            self.eng.service_id
        )

    @mock.patch.object(service.EngineService,
                       '_stop_rpc_server')
    @mock.patch.object(worker.WorkerService,
                       'stop')
    @mock.patch.object(threadgroup.ThreadGroup,
                       'stop')
    @mock.patch.object(service.ThreadGroupManager,
                       'stop')
    @mock.patch('heat.common.context.get_admin_context',
                return_value=mock.Mock())
    @mock.patch('heat.objects.service.Service.delete',
                return_value=mock.Mock())
    def test_engine_service_stop_in_convergence_mode(
            self,
            service_delete_method,
            admin_context_method,
            thread_group_mgr_stop,
            thread_group_stop,
            worker_service_stop,
            rpc_server_stop):
        cfg.CONF.set_default('convergence_engine', True)
        self._test_engine_service_stop(
            service_delete_method,
            admin_context_method
        )

    @mock.patch.object(service.EngineService,
                       '_stop_rpc_server')
    @mock.patch.object(threadgroup.ThreadGroup,
                       'stop')
    @mock.patch.object(service.ThreadGroupManager,
                       'stop')
    @mock.patch('heat.common.context.get_admin_context',
                return_value=mock.Mock())
    @mock.patch('heat.objects.service.Service.delete',
                return_value=mock.Mock())
    def test_engine_service_stop_in_non_convergence_mode(
            self,
            service_delete_method,
            admin_context_method,
            thread_group_mgr_stop,
            thread_group_stop,
            rpc_server_stop):
        cfg.CONF.set_default('convergence_engine', False)
        self._test_engine_service_stop(
            service_delete_method,
            admin_context_method
        )


class SoftwareConfigServiceTest(common.HeatTestCase):

    def setUp(self):
        super(SoftwareConfigServiceTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.patch('heat.engine.service.warnings')
        self.engine = service.EngineService('a-host', 'a-topic')

    def _create_software_config(
            self, group='Heat::Shell', name='config_mysql', config=None,
            inputs=None, outputs=None, options=None):
        inputs = inputs or []
        outputs = outputs or []
        options = options or {}
        return self.engine.create_software_config(
            self.ctx, group, name, config, inputs, outputs, options)

    def test_show_software_config(self):
        config_id = str(uuid.uuid4())

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_software_config,
                               self.ctx, config_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        config = self._create_software_config()
        config_id = config['id']
        self.assertEqual(
            config, self.engine.show_software_config(self.ctx, config_id))

    def test_create_software_config(self):
        config = self._create_software_config()
        self.assertIsNotNone(config)
        config_id = config['id']
        config = self._create_software_config()
        self.assertNotEqual(config_id, config['id'])
        kwargs = {
            'group': 'Heat::Chef',
            'name': 'config_heat',
            'config': '...',
            'inputs': [{'name': 'mode'}],
            'outputs': [{'name': 'endpoint'}],
            'options': {}
        }
        config = self._create_software_config(**kwargs)
        config_id = config['id']
        config = self.engine.show_software_config(self.ctx, config_id)
        self.assertEqual(kwargs['group'], config['group'])
        self.assertEqual(kwargs['name'], config['name'])
        self.assertEqual(kwargs['config'], config['config'])
        self.assertEqual(kwargs['inputs'], config['inputs'])
        self.assertEqual(kwargs['outputs'], config['outputs'])
        self.assertEqual(kwargs['options'], config['options'])

    def test_delete_software_config(self):
        config = self._create_software_config()
        self.assertIsNotNone(config)
        config_id = config['id']
        self.engine.delete_software_config(self.ctx, config_id)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_software_config,
                               self.ctx, config_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

    def _create_software_deployment(self, config_id=None, input_values=None,
                                    action='INIT',
                                    status='COMPLETE', status_reason='',
                                    config_group=None,
                                    server_id=str(uuid.uuid4()),
                                    config_name=None,
                                    stack_user_project_id=None):
        input_values = input_values or {}
        if config_id is None:
            config = self._create_software_config(group=config_group,
                                                  name=config_name)
            config_id = config['id']
        return self.engine.create_software_deployment(
            self.ctx, server_id, config_id, input_values,
            action, status, status_reason, stack_user_project_id)

    def test_list_software_deployments(self):
        stack_name = 'test_list_software_deployments'
        stack = get_wordpress_stack(stack_name, self.ctx)

        setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        server = stack['WebServer']
        server_id = server.resource_id

        deployment = self._create_software_deployment(
            server_id=server_id)
        deployment_id = deployment['id']
        self.assertIsNotNone(deployment)

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=None)
        self.assertIsNotNone(deployments)
        deployment_ids = [x['id'] for x in deployments]
        self.assertIn(deployment_id, deployment_ids)
        self.assertIn(deployment, deployments)

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=str(uuid.uuid4()))
        self.assertEqual([], deployments)

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=server.resource_id)
        self.assertEqual([deployment], deployments)

        rs = resource_objects.Resource.get_by_physical_resource_id(
            self.ctx, server_id)
        self.assertEqual(deployment['config_id'],
                         rs.rsrc_metadata.get('deployments')[0]['id'])

    def test_metadata_software_deployments(self):
        stack_name = 'test_list_software_deployments'
        stack = get_wordpress_stack(stack_name, self.ctx)

        setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack.store()
        stack.create()
        server = stack['WebServer']
        server_id = server.resource_id

        stack_user_project_id = str(uuid.uuid4())
        d1 = self._create_software_deployment(
            config_group='mygroup',
            server_id=server_id,
            config_name='02_second',
            stack_user_project_id=stack_user_project_id)
        d2 = self._create_software_deployment(
            config_group='mygroup',
            server_id=server_id,
            config_name='01_first',
            stack_user_project_id=stack_user_project_id)
        d3 = self._create_software_deployment(
            config_group='myothergroup',
            server_id=server_id,
            config_name='03_third',
            stack_user_project_id=stack_user_project_id)
        metadata = self.engine.metadata_software_deployments(
            self.ctx, server_id=server_id)
        self.assertEqual(3, len(metadata))
        self.assertEqual('mygroup', metadata[1]['group'])
        self.assertEqual('mygroup', metadata[0]['group'])
        self.assertEqual('myothergroup', metadata[2]['group'])
        self.assertEqual(d1['config_id'], metadata[1]['id'])
        self.assertEqual(d2['config_id'], metadata[0]['id'])
        self.assertEqual(d3['config_id'], metadata[2]['id'])
        self.assertEqual('01_first', metadata[0]['name'])
        self.assertEqual('02_second', metadata[1]['name'])
        self.assertEqual('03_third', metadata[2]['name'])

        # assert that metadata via metadata_software_deployments matches
        # metadata via server resource
        rs = resource_objects.Resource.get_by_physical_resource_id(
            self.ctx, server_id)
        self.assertEqual(metadata,
                         rs.rsrc_metadata.get('deployments'))

        deployments = self.engine.metadata_software_deployments(
            self.ctx, server_id=str(uuid.uuid4()))
        self.assertEqual([], deployments)

        # assert get results when the context tenant_id matches
        # the stored stack_user_project_id
        ctx = utils.dummy_context(tenant_id=stack_user_project_id)
        metadata = self.engine.metadata_software_deployments(
            ctx, server_id=server_id)
        self.assertEqual(3, len(metadata))

        # assert get no results when the context tenant_id is unknown
        ctx = utils.dummy_context(tenant_id=str(uuid.uuid4()))
        metadata = self.engine.metadata_software_deployments(
            ctx, server_id=server_id)
        self.assertEqual(0, len(metadata))

    def test_show_software_deployment(self):
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_software_deployment,
                               self.ctx, deployment_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        deployment = self._create_software_deployment()
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        self.assertEqual(
            deployment,
            self.engine.show_software_deployment(self.ctx, deployment_id))

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       '_push_metadata_software_deployments')
    def test_signal_software_deployment(self, pmsd):
        self.assertRaises(ValueError,
                          self.engine.signal_software_deployment,
                          self.ctx, None, {}, None)
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.signal_software_deployment,
                               self.ctx, deployment_id, {}, None)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        deployment = self._create_software_deployment()
        deployment_id = deployment['id']

        # signal is ignore unless deployment is IN_PROGRESS
        self.assertIsNone(self.engine.signal_software_deployment(
            self.ctx, deployment_id, {}, None))

        # simple signal, no data
        deployment = self._create_software_deployment(
            action='INIT', status='IN_PROGRESS')
        deployment_id = deployment['id']
        self.assertEqual(
            'deployment succeeded',
            self.engine.signal_software_deployment(
                self.ctx, deployment_id, {}, None))
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('COMPLETE', sd.status)
        self.assertEqual('Outputs received', sd.status_reason)
        self.assertEqual({
            'deploy_status_code': None,
            'deploy_stderr': None,
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

        # simple signal, some data
        config = self._create_software_config(outputs=[{'name': 'foo'}])
        deployment = self._create_software_deployment(
            config_id=config['id'], action='INIT', status='IN_PROGRESS')
        deployment_id = deployment['id']
        result = self.engine.signal_software_deployment(
            self.ctx,
            deployment_id,
            {'foo': 'bar', 'deploy_status_code': 0},
            None)
        self.assertEqual('deployment succeeded', result)
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('COMPLETE', sd.status)
        self.assertEqual('Outputs received', sd.status_reason)
        self.assertEqual({
            'deploy_status_code': 0,
            'foo': 'bar',
            'deploy_stderr': None,
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

        # failed signal on deploy_status_code
        config = self._create_software_config(outputs=[
            {'name': 'foo'}])
        deployment = self._create_software_deployment(
            config_id=config['id'], action='INIT', status='IN_PROGRESS')
        deployment_id = deployment['id']
        result = self.engine.signal_software_deployment(
            self.ctx,
            deployment_id,
            {
                'foo': 'bar',
                'deploy_status_code': -1,
                'deploy_stderr': 'Its gone Pete Tong'
            },
            None)
        self.assertEqual('deployment failed (-1)', result)
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('FAILED', sd.status)
        self.assertEqual(
            ('deploy_status_code : Deployment exited with non-zero '
             'status code: -1'),
            sd.status_reason)
        self.assertEqual({
            'deploy_status_code': -1,
            'foo': 'bar',
            'deploy_stderr': 'Its gone Pete Tong',
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

        # failed signal on error_output foo
        config = self._create_software_config(outputs=[
            {'name': 'foo', 'error_output': True}])
        deployment = self._create_software_deployment(
            config_id=config['id'], action='INIT', status='IN_PROGRESS')
        deployment_id = deployment['id']
        result = self.engine.signal_software_deployment(
            self.ctx,
            deployment_id,
            {
                'foo': 'bar',
                'deploy_status_code': -1,
                'deploy_stderr': 'Its gone Pete Tong'
            },
            None)
        self.assertEqual('deployment failed', result)
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('FAILED', sd.status)
        self.assertEqual(
            ('foo : bar, deploy_status_code : Deployment exited with '
             'non-zero status code: -1'),
            sd.status_reason)
        self.assertEqual({
            'deploy_status_code': -1,
            'foo': 'bar',
            'deploy_stderr': 'Its gone Pete Tong',
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

    def test_create_software_deployment(self):
        kwargs = {
            'group': 'Heat::Chef',
            'name': 'config_heat',
            'config': '...',
            'inputs': [{'name': 'mode'}],
            'outputs': [{'name': 'endpoint'}],
            'options': {}
        }
        config = self._create_software_config(**kwargs)
        config_id = config['id']
        kwargs = {
            'config_id': config_id,
            'input_values': {'mode': 'standalone'},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': ''
        }
        deployment = self._create_software_deployment(**kwargs)
        deployment_id = deployment['id']
        deployment = self.engine.show_software_deployment(
            self.ctx, deployment_id)
        self.assertEqual(deployment_id, deployment['id'])
        self.assertEqual(kwargs['input_values'], deployment['input_values'])

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       '_refresh_software_deployment')
    def test_show_software_deployment_refresh(
            self, _refresh_software_deployment):
        temp_url = ('http://192.0.2.1/v1/AUTH_a/b/c'
                    '?temp_url_sig=ctemp_url_expires=1234')
        config = self._create_software_config(inputs=[
            {
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'TEMP_URL_SIGNAL'
            }, {
                'name': 'deploy_signal_id',
                'type': 'String',
                'value': temp_url
            }
        ])

        deployment = self._create_software_deployment(
            status='IN_PROGRESS', config_id=config['id'])

        deployment_id = deployment['id']
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        _refresh_software_deployment.return_value = sd
        self.assertEqual(
            deployment,
            self.engine.show_software_deployment(self.ctx, deployment_id))
        self.assertEqual(
            (self.ctx, sd, temp_url),
            _refresh_software_deployment.call_args[0])

    def test_update_software_deployment_new_config(self):

        server_id = str(uuid.uuid4())
        self.m.StubOutWithMock(
            self.engine.software_config,
            '_push_metadata_software_deployments')

        # push on create
        self.engine.software_config._push_metadata_software_deployments(
            self.ctx, server_id).AndReturn(None)
        # push on update with new config_id
        self.engine.software_config._push_metadata_software_deployments(
            self.ctx, server_id).AndReturn(None)

        self.m.ReplayAll()

        deployment = self._create_software_deployment(server_id=server_id)
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        deployment_action = deployment['action']
        self.assertEqual('INIT', deployment_action)
        config_id = deployment['config_id']
        self.assertIsNotNone(config_id)
        updated = self.engine.update_software_deployment(
            self.ctx, deployment_id=deployment_id, config_id=config_id,
            input_values={}, output_values={}, action='DEPLOY',
            status='WAITING', status_reason='', updated_at=None)
        self.assertIsNotNone(updated)
        self.assertEqual(config_id, updated['config_id'])
        self.assertEqual('DEPLOY', updated['action'])
        self.assertEqual('WAITING', updated['status'])
        self.m.VerifyAll()

    def test_update_software_deployment_status(self):

        server_id = str(uuid.uuid4())
        self.m.StubOutWithMock(
            self.engine.software_config,
            '_push_metadata_software_deployments')
        # push on create
        self.engine.software_config._push_metadata_software_deployments(
            self.ctx, server_id).AndReturn(None)
        # _push_metadata_software_deployments should not be called
        # on update because config_id isn't being updated
        self.m.ReplayAll()
        deployment = self._create_software_deployment(server_id=server_id)

        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        deployment_action = deployment['action']
        self.assertEqual('INIT', deployment_action)
        updated = self.engine.update_software_deployment(
            self.ctx, deployment_id=deployment_id, config_id=None,
            input_values=None, output_values={}, action='DEPLOY',
            status='WAITING', status_reason='', updated_at=None)
        self.assertIsNotNone(updated)
        self.assertEqual('DEPLOY', updated['action'])
        self.assertEqual('WAITING', updated['status'])
        self.m.VerifyAll()

    def test_update_software_deployment_fields(self):

        deployment = self._create_software_deployment()
        deployment_id = deployment['id']
        config_id = deployment['config_id']

        def check_software_deployment_updated(**kwargs):
            values = {
                'config_id': None,
                'input_values': {},
                'output_values': {},
                'action': {},
                'status': 'WAITING',
                'status_reason': ''
            }
            values.update(kwargs)
            updated = self.engine.update_software_deployment(
                self.ctx, deployment_id, updated_at=None, **values)
            for key, value in six.iteritems(kwargs):
                self.assertEqual(value, updated[key])

        check_software_deployment_updated(config_id=config_id)
        check_software_deployment_updated(input_values={'foo': 'fooooo'})
        check_software_deployment_updated(output_values={'bar': 'baaaaa'})
        check_software_deployment_updated(action='DEPLOY')
        check_software_deployment_updated(status='COMPLETE')
        check_software_deployment_updated(status_reason='Done!')

    def test_delete_software_deployment(self):
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.delete_software_deployment,
                               self.ctx, deployment_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        deployment = self._create_software_deployment()
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=None)
        deployment_ids = [x['id'] for x in deployments]
        self.assertIn(deployment_id, deployment_ids)
        self.engine.delete_software_deployment(self.ctx, deployment_id)
        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=None)
        deployment_ids = [x['id'] for x in deployments]
        self.assertNotIn(deployment_id, deployment_ids)

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(service_software_config.requests, 'put')
    def test_push_metadata_software_deployments(
            self, put, res_get, res_upd, md_sd):
        rs = mock.Mock()
        rs.rsrc_metadata = {'original': 'metadata'}
        rs.id = '1234'
        rs.atomic_key = 1
        rs.data = []
        res_get.return_value = rs
        res_upd.return_value = 1

        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments

        result_metadata = {
            'original': 'metadata',
            'deployments': {'deploy': 'this'}
        }

        self.engine.software_config._push_metadata_software_deployments(
            self.ctx, '1234')
        res_upd.assert_called_once_with(
            self.ctx, '1234', {'rsrc_metadata': result_metadata}, 1)
        put.side_effect = Exception('Unexpected requests.put')

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(service_software_config.requests, 'put')
    def test_push_metadata_software_deployments_retry(
            self, put, res_get, res_upd, md_sd):
        rs = mock.Mock()
        rs.rsrc_metadata = {'original': 'metadata'}
        rs.id = '1234'
        rs.atomic_key = 1
        rs.data = []
        res_get.return_value = rs
        # zero update means another transaction updated
        res_upd.return_value = 0

        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments

        self.assertRaises(
            exception.DeploymentConcurrentTransaction,
            self.engine.software_config._push_metadata_software_deployments,
            self.ctx,
            '1234')
        # retry ten times then the final failure
        self.assertEqual(11, res_upd.call_count)
        put.assert_not_called()

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(service_software_config.requests, 'put')
    def test_push_metadata_software_deployments_temp_url(
            self, put, res_get, res_upd, md_sd):
        rs = mock.Mock()
        rs.rsrc_metadata = {'original': 'metadata'}
        rs.id = '1234'
        rs.atomic_key = 1
        rd = mock.Mock()
        rd.key = 'metadata_put_url'
        rd.value = 'http://192.168.2.2/foo/bar'
        rs.data = [rd]
        res_get.return_value = rs
        res_upd.return_value = 1

        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments

        result_metadata = {
            'original': 'metadata',
            'deployments': {'deploy': 'this'}
        }

        self.engine.software_config._push_metadata_software_deployments(
            self.ctx, '1234')
        res_upd.assert_called_once_with(
            self.ctx, '1234', {'rsrc_metadata': result_metadata}, 1)

        put.assert_called_once_with(
            'http://192.168.2.2/foo/bar', json.dumps(result_metadata))

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'signal_software_deployment')
    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    def test_refresh_software_deployment(self, scc, ssd):
        temp_url = ('http://192.0.2.1/v1/AUTH_a/b/c'
                    '?temp_url_sig=ctemp_url_expires=1234')
        container = 'b'
        object_name = 'c'

        config = self._create_software_config(inputs=[
            {
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'TEMP_URL_SIGNAL'
            }, {
                'name': 'deploy_signal_id',
                'type': 'String',
                'value': temp_url
            }
        ])

        timeutils.set_time_override(
            datetime.datetime(2013, 1, 23, 22, 48, 5, 0))
        self.addCleanup(timeutils.clear_time_override)
        now = timeutils.utcnow()
        then = now - datetime.timedelta(0, 60)

        last_modified_1 = 'Wed, 23 Jan 2013 22:47:05 GMT'
        last_modified_2 = 'Wed, 23 Jan 2013 22:48:05 GMT'

        sc = mock.MagicMock()
        headers = {
            'last-modified': last_modified_1
        }
        sc.head_object.return_value = headers
        sc.get_object.return_value = (headers, '{"foo": "bar"}')
        scc.return_value = sc

        deployment = self._create_software_deployment(
            status='IN_PROGRESS', config_id=config['id'])

        deployment_id = six.text_type(deployment['id'])
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)

        # poll with missing object
        swift_exc = swift.SwiftClientPlugin.exceptions_module
        sc.head_object.side_effect = swift_exc.ClientException(
            'Not found', http_status=404)

        self.assertEqual(
            sd,
            self.engine.software_config._refresh_software_deployment(
                self.ctx, sd, temp_url))
        sc.head_object.assert_called_once_with(container, object_name)
        # no call to get_object or signal_last_modified
        self.assertEqual([], sc.get_object.mock_calls)
        self.assertEqual([], ssd.mock_calls)

        # poll with other error
        sc.head_object.side_effect = swift_exc.ClientException(
            'Ouch', http_status=409)
        self.assertRaises(
            swift_exc.ClientException,
            self.engine.software_config._refresh_software_deployment,
            self.ctx,
            sd,
            temp_url)
        # no call to get_object or signal_last_modified
        self.assertEqual([], sc.get_object.mock_calls)
        self.assertEqual([], ssd.mock_calls)
        sc.head_object.side_effect = None

        # first poll populates data signal_last_modified
        self.engine.software_config._refresh_software_deployment(
            self.ctx, sd, temp_url)
        sc.head_object.assert_called_with(container, object_name)
        sc.get_object.assert_called_once_with(container, object_name)
        # signal_software_deployment called with signal
        ssd.assert_called_once_with(self.ctx, deployment_id, {u"foo": u"bar"},
                                    timeutils.strtime(then))

        # second poll updated_at populated with first poll last-modified
        software_deployment_object.SoftwareDeployment.update_by_id(
            self.ctx, deployment_id, {'updated_at': then})
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual(then, sd.updated_at)
        self.engine.software_config._refresh_software_deployment(
            self.ctx, sd, temp_url)
        sc.get_object.assert_called_once_with(container, object_name)
        # signal_software_deployment has not been called again
        ssd.assert_called_once_with(self.ctx, deployment_id, {"foo": "bar"},
                                    timeutils.strtime(then))

        # third poll last-modified changed, new signal
        headers['last-modified'] = last_modified_2
        sc.head_object.return_value = headers
        sc.get_object.return_value = (headers, '{"bar": "baz"}')
        self.engine.software_config._refresh_software_deployment(
            self.ctx, sd, temp_url)

        # two calls to signal_software_deployment, for then and now
        self.assertEqual(2, len(ssd.mock_calls))
        ssd.assert_called_with(self.ctx, deployment_id, {"bar": "baz"},
                               timeutils.strtime(now))

        # four polls result in only two signals, for then and now
        software_deployment_object.SoftwareDeployment.update_by_id(
            self.ctx, deployment_id, {'updated_at': now})
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.engine.software_config._refresh_software_deployment(
            self.ctx, sd, temp_url)
        self.assertEqual(2, len(ssd.mock_calls))


class ThreadGroupManagerTest(common.HeatTestCase):
    def setUp(self):
        super(ThreadGroupManagerTest, self).setUp()
        self.f = 'function'
        self.fargs = ('spam', 'ham', 'eggs')
        self.fkwargs = {'foo': 'bar'}
        self.cnxt = 'ctxt'
        self.engine_id = 'engine_id'
        self.stack = mock.Mock()
        self.lock_mock = mock.Mock()
        self.stlock_mock = self.patch('heat.engine.service.stack_lock')
        self.stlock_mock.StackLock.return_value = self.lock_mock
        self.tg_mock = mock.Mock()
        self.thg_mock = self.patch('heat.engine.service.threadgroup')
        self.thg_mock.ThreadGroup.return_value = self.tg_mock
        self.cfg_mock = self.patch('heat.engine.service.cfg')

    def test_tgm_start_with_lock(self):
        thm = service.ThreadGroupManager()
        with self.patchobject(thm, 'start_with_acquired_lock'):
            mock_thread_lock = mock.Mock()
            mock_thread_lock.__enter__ = mock.Mock(return_value=None)
            mock_thread_lock.__exit__ = mock.Mock(return_value=None)
            self.lock_mock.thread_lock.return_value = mock_thread_lock
            thm.start_with_lock(self.cnxt, self.stack, self.engine_id, self.f,
                                *self.fargs, **self.fkwargs)
            self.stlock_mock.StackLock.assert_called_with(self.cnxt,
                                                          self.stack,
                                                          self.engine_id)

            thm.start_with_acquired_lock.assert_called_once_with(
                self.stack, self.lock_mock,
                self.f, *self.fargs, **self.fkwargs)

    def test_tgm_start(self):
        stack_id = 'test'

        thm = service.ThreadGroupManager()
        ret = thm.start(stack_id, self.f, *self.fargs, **self.fkwargs)

        self.assertEqual(self.tg_mock, thm.groups['test'])
        self.tg_mock.add_thread.assert_called_with(
            thm._start_with_trace, None,
            self.f, *self.fargs, **self.fkwargs)
        self.assertEqual(ret, self.tg_mock.add_thread())

    def test_tgm_add_timer(self):
        stack_id = 'test'

        thm = service.ThreadGroupManager()
        thm.add_timer(stack_id, self.f, *self.fargs, **self.fkwargs)

        self.assertEqual(self.tg_mock, thm.groups[stack_id])
        self.tg_mock.add_timer.assert_called_with(
            self.cfg_mock.CONF.periodic_interval,
            self.f, *self.fargs, **self.fkwargs)

    def test_tgm_add_event(self):
        stack_id = 'add_events_test'
        e1, e2 = mock.Mock(), mock.Mock()
        thm = service.ThreadGroupManager()
        thm.add_event(stack_id, e1)
        thm.add_event(stack_id, e2)
        self.assertEqual([e1, e2], thm.events[stack_id])

    def test_tgm_remove_event(self):
        stack_id = 'add_events_test'
        e1, e2 = mock.Mock(), mock.Mock()
        thm = service.ThreadGroupManager()
        thm.add_event(stack_id, e1)
        thm.add_event(stack_id, e2)
        thm.remove_event(None, stack_id, e2)
        self.assertEqual([e1], thm.events[stack_id])
        thm.remove_event(None, stack_id, e1)
        self.assertNotIn(stack_id, thm.events)

    def test_tgm_send(self):
        stack_id = 'send_test'
        e1, e2 = mock.MagicMock(), mock.Mock()
        thm = service.ThreadGroupManager()
        thm.add_event(stack_id, e1)
        thm.add_event(stack_id, e2)
        thm.send(stack_id, 'test_message')


class ThreadGroupManagerStopTest(common.HeatTestCase):
    def test_tgm_stop(self):
        stack_id = 'test'
        done = []

        def function():
            while True:
                eventlet.sleep()

        def linked(gt, thread):
            for i in range(10):
                eventlet.sleep()
            done.append(thread)

        thm = service.ThreadGroupManager()
        thm.add_event(stack_id, mock.Mock())
        thread = thm.start(stack_id, function)
        thread.link(linked, thread)

        thm.stop(stack_id)

        self.assertIn(thread, done)
        self.assertNotIn(stack_id, thm.groups)
        self.assertNotIn(stack_id, thm.events)


class SnapshotServiceTest(common.HeatTestCase):

    def setUp(self):
        super(SnapshotServiceTest, self).setUp()
        self.ctx = utils.dummy_context()

        self.m.ReplayAll()
        self.engine = service.EngineService('a-host', 'a-topic')
        self.engine.create_periodic_tasks()
        utils.setup_dummy_db()
        self.addCleanup(self.m.VerifyAll)

    def _create_stack(self, stub=True):
        stack = get_wordpress_stack('stack', self.ctx)
        sid = stack.store()

        s = stack_object.Stack.get_by_id(self.ctx, sid)
        if stub:
            self.m.StubOutWithMock(parser.Stack, 'load')
        stack.state_set(stack.CREATE, stack.COMPLETE, 'mock completion')
        parser.Stack.load(self.ctx, stack=s).MultipleTimes().AndReturn(stack)
        return stack

    def test_show_snapshot_not_found(self):
        snapshot_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_snapshot,
                               self.ctx, None, snapshot_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

    def test_create_snapshot(self):
        stack = self._create_stack()
        self.m.ReplayAll()
        snapshot = self.engine.stack_snapshot(
            self.ctx, stack.identifier(), 'snap1')
        self.assertIsNotNone(snapshot['id'])
        self.assertIsNotNone(snapshot['creation_time'])
        self.assertEqual('snap1', snapshot['name'])
        self.assertEqual("IN_PROGRESS", snapshot['status'])
        self.engine.thread_group_mgr.groups[stack.id].wait()
        snapshot = self.engine.show_snapshot(
            self.ctx, stack.identifier(), snapshot['id'])
        self.assertEqual("COMPLETE", snapshot['status'])
        self.assertEqual("SNAPSHOT", snapshot['data']['action'])
        self.assertEqual("COMPLETE", snapshot['data']['status'])
        self.assertEqual(stack.id, snapshot['data']['id'])
        self.assertIsNotNone(stack.updated_time)
        self.assertIsNotNone(snapshot['creation_time'])

    def test_create_snapshot_action_in_progress(self):
        stack = self._create_stack()
        self.m.ReplayAll()
        stack.state_set(stack.UPDATE, stack.IN_PROGRESS, 'test_override')
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.stack_snapshot,
                               self.ctx, stack.identifier(), 'snap_none')
        self.assertEqual(exception.ActionInProgress, ex.exc_info[0])
        msg = ("Stack stack already has an action (%(action)s) "
               "in progress.") % {'action': stack.action}
        self.assertEqual(msg, six.text_type(ex.exc_info[1]))

    def test_delete_snapshot_not_found(self):
        stack = self._create_stack()
        self.m.ReplayAll()
        snapshot_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.delete_snapshot,
                               self.ctx, stack.identifier(), snapshot_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

    def test_delete_snapshot(self):
        stack = self._create_stack()
        self.m.ReplayAll()
        snapshot = self.engine.stack_snapshot(
            self.ctx, stack.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stack.id].wait()
        snapshot_id = snapshot['id']
        self.engine.delete_snapshot(self.ctx, stack.identifier(), snapshot_id)
        self.engine.thread_group_mgr.groups[stack.id].wait()
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_snapshot, self.ctx,
                               stack.identifier(), snapshot_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

    def test_list_snapshots(self):
        stack = self._create_stack()
        self.m.ReplayAll()
        snapshot = self.engine.stack_snapshot(
            self.ctx, stack.identifier(), 'snap1')
        self.assertIsNotNone(snapshot['id'])
        self.assertEqual("IN_PROGRESS", snapshot['status'])
        self.engine.thread_group_mgr.groups[stack.id].wait()

        snapshots = self.engine.stack_list_snapshots(
            self.ctx, stack.identifier())
        expected = {
            "id": snapshot["id"],
            "name": "snap1",
            "status": "COMPLETE",
            "status_reason": "Stack SNAPSHOT completed successfully",
            "data": stack.prepare_abandon(),
            "creation_time": snapshot['creation_time']}
        self.assertEqual([expected], snapshots)

    def test_restore_snapshot(self):
        stack = self._create_stack()
        self.m.ReplayAll()
        snapshot = self.engine.stack_snapshot(
            self.ctx, stack.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stack.id].wait()
        snapshot_id = snapshot['id']
        self.engine.stack_restore(self.ctx, stack.identifier(), snapshot_id)
        self.engine.thread_group_mgr.groups[stack.id].wait()
        self.assertEqual((stack.RESTORE, stack.COMPLETE), stack.state)

    def test_restore_snapshot_other_stack(self):
        stack1 = self._create_stack()
        self.m.ReplayAll()
        snapshot1 = self.engine.stack_snapshot(
            self.ctx, stack1.identifier(), 'snap1')
        self.engine.thread_group_mgr.groups[stack1.id].wait()
        snapshot_id = snapshot1['id']
        self.m.UnsetStubs()
        stack2 = self._create_stack()
        self.m.ReplayAll()
        self.engine.stack_restore(self.ctx, stack2.identifier(), snapshot_id)
        self.engine.thread_group_mgr.groups[stack2.id].wait()
        self.assertEqual((stack2.RESTORE, stack2.FAILED), stack2.state)
        self.assertEqual("Can't restore snapshot from other stack",
                         stack2.status_reason)
