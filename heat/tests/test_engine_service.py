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


import functools
import json
import sys
import uuid

from eventlet import greenpool
import mock
import mox
from oslo.config import cfg

from heat.common import exception
from heat.common import identifier
from heat.common import template_format
from heat.common import urlfetch
import heat.db.api as db_api
from heat.engine import clients
from heat.engine import dependencies
from heat.engine import environment
from heat.engine import parser
from heat.engine.properties import Properties
from heat.engine import resource as res
from heat.engine.resources import instance as instances
from heat.engine.resources import nova_utils
from heat.engine import service
from heat.engine import stack_lock
from heat.engine import watchrule
from heat.openstack.common.fixture import mockpatch
from heat.openstack.common.rpc import common as rpc_common
from heat.openstack.common.rpc import proxy
from heat.openstack.common import threadgroup
import heat.rpc.api as engine_api
from heat.tests.common import HeatTestCase
from heat.tests import fakes as test_fakes
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils
from heat.tests.v1_1 import fakes

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')

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

nested_alarm_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_nested:
    Type: AWS::CloudFormation::Stack
    Properties:
      TemplateURL: https://server.test/alarm.template
'''

alarm_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "alarming",
  "Resources" : {
    "service_alarm": {
      "Type": "AWS::CloudWatch::Alarm",
      "Properties": {
        "EvaluationPeriods": "1",
        "AlarmActions": [],
        "AlarmDescription": "do the thing",
        "Namespace": "dev/null",
        "Period": "300",
        "ComparisonOperator": "GreaterThanThreshold",
        "Statistic": "SampleCount",
        "Threshold": "2",
        "MetricName": "ServiceFailure"
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
    template = parser.Template(t)
    stack = parser.Stack(ctx, stack_name, template,
                         environment.Environment({'KeyName': 'test'}))
    return stack


def get_stack(stack_name, ctx, template):
    t = template_format.parse(template)
    template = parser.Template(t)
    stack = parser.Stack(ctx, stack_name, template)
    return stack


def setup_keystone_mocks(mocks, stack):
    fkc = test_fakes.FakeKeystoneClient()
    mocks.StubOutWithMock(stack.clients, 'keystone')
    stack.clients.keystone().MultipleTimes().AndReturn(fkc)


def setup_mocks(mocks, stack):
    fc = fakes.FakeClient()
    mocks.StubOutWithMock(instances.Instance, 'nova')
    instances.Instance.nova().MultipleTimes().AndReturn(fc)
    mocks.StubOutWithMock(clients.OpenStackClients, 'nova')
    clients.OpenStackClients.nova().MultipleTimes().AndReturn(fc)
    setup_keystone_mocks(mocks, stack)

    instance = stack['WebServer']
    user_data = instance.properties['UserData']
    server_userdata = nova_utils.build_userdata(instance, user_data,
                                                'ec2-user')
    mocks.StubOutWithMock(nova_utils, 'build_userdata')
    nova_utils.build_userdata(
        instance,
        instance.t['Properties']['UserData'],
        'ec2-user').AndReturn(server_userdata)

    mocks.StubOutWithMock(fc.servers, 'create')
    fc.servers.create(image=744, flavor=3, key_name='test',
                      name=utils.PhysName(stack.name, 'WebServer'),
                      security_groups=None,
                      userdata=server_userdata, scheduler_hints=None,
                      meta=None, nics=None,
                      availability_zone=None).AndReturn(
                          fc.servers.list()[4])
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
        fc = fakes.FakeClient()
        m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(fc)
        m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(service.clients.novaclient.exceptions.NotFound(404))
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
        @functools.wraps(test_fn)
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
            except:
                exc_class, exc_val, exc_tb = sys.exc_info()
                try:
                    delete_stack()
                finally:
                    raise exc_class, exc_val, exc_tb
            else:
                delete_stack()

        return wrapped_test
    return stack_delete


class DummyThreadGroup(object):
    def __init__(self):
        self.threads = []
        self.pool = greenpool.GreenPool(10)

    def add_timer(self, interval, callback, initial_delay=None,
                  *args, **kwargs):
        self.threads.append(callback)

    def add_thread(self, callback, *args, **kwargs):
        self.threads.append(callback)
        return self.pool.spawn(callback, *args, **kwargs)

    def stop(self):
        pass

    def wait(self):
        pass


class StackCreateTest(HeatTestCase):
    def setUp(self):
        super(StackCreateTest, self).setUp()
        utils.setup_dummy_db()

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
        template = parser.Template(t)
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
        template = parser.Template(t)
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
        expected = ('Resource ADOPT failed: Exception: Resource ID was not'
                    ' provided.')
        self.assertEqual(expected, stack.status_reason)
        self.assertEqual((stack.ADOPT, stack.FAILED), stack.state)

    def test_wordpress_single_instance_stack_delete(self):
        ctx = utils.dummy_context()
        stack = get_wordpress_stack('test_stack', ctx)
        fc = setup_mocks(self.m, stack)
        self.m.ReplayAll()
        stack_id = stack.store()
        stack.create()

        db_s = db_api.stack_get(ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.assertIsNotNone(stack['WebServer'])
        self.assertTrue(stack['WebServer'].resource_id > 0)

        self.m.StubOutWithMock(fc.client, 'get_servers_9999')
        get = fc.client.get_servers_9999
        get().AndRaise(service.clients.novaclient.exceptions.NotFound(404))
        mox.Replay(get)
        stack.delete()

        rsrc = stack['WebServer']
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual((stack.DELETE, stack.COMPLETE), rsrc.state)
        self.assertIsNone(db_api.stack_get(ctx, stack_id))
        self.assertEqual('DELETE', db_s.action)
        self.assertEqual('COMPLETE', db_s.status, )


class StackServiceCreateUpdateDeleteTest(HeatTestCase):

    def setUp(self):
        super(StackServiceCreateUpdateDeleteTest, self).setUp()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.ctx = utils.dummy_context()

        self.m.StubOutWithMock(service.EngineListener, 'start')
        service.EngineListener.start().AndReturn(None)
        self.m.ReplayAll()
        self.man = service.EngineService('a-host', 'a-topic')

    def _test_stack_create(self, stack_name):
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.env).AndReturn(stack)

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
        ex = self.assertRaises(rpc_common.ClientException,
                               self._test_stack_create, stack_name)
        self.assertEqual(ex._exc_info[0], exception.RequestLimitExceeded)
        self.assertIn("You have reached the maximum stacks per tenant",
                      str(ex._exc_info[1]))

    def test_stack_create_verify_err(self):
        stack_name = 'service_create_verify_err_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     stack.env).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndRaise(exception.StackValidationFailed(
            message='fubar'))

        self.m.ReplayAll()

        ex = self.assertRaises(
            rpc_common.ClientException,
            self.man.create_stack,
            self.ctx, stack_name,
            template, params, None, {})
        self.assertEqual(ex._exc_info[0], exception.StackValidationFailed)
        self.m.VerifyAll()

    def test_stack_create_invalid_stack_name(self):
        stack_name = 'service_create/test_stack'
        stack = get_wordpress_stack('test_stack', self.ctx)

        self.assertRaises(ValueError,
                          self.man.create_stack,
                          self.ctx, stack_name, stack.t, {}, None, {})

    def test_stack_create_invalid_resource_name(self):
        stack_name = 'service_create_test_stack_invalid_res'
        stack = get_wordpress_stack(stack_name, self.ctx)
        tmpl = dict(stack.t)
        tmpl['Resources']['Web/Server'] = tmpl['Resources']['WebServer']
        del tmpl['Resources']['WebServer']

        self.assertRaises(ValueError,
                          self.man.create_stack,
                          self.ctx, stack_name,
                          stack.t, {}, None, {})

    def test_stack_create_no_credentials(self):
        stack_name = 'test_stack_create_no_credentials'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = get_wordpress_stack(stack_name, self.ctx)
        # force check for credentials on create
        stack['WebServer'].requires_deferred_auth = True

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        ctx_no_pwd = utils.dummy_context(password=None)
        ctx_no_user = utils.dummy_context(user=None)

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(ctx_no_pwd, stack.name,
                     stack.t, stack.env).AndReturn(stack)

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(ctx_no_user, stack.name,
                     stack.t, stack.env).AndReturn(stack)

        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.create_stack,
                               ctx_no_pwd, stack_name,
                               template, params, None, {})
        self.assertEqual(ex._exc_info[0], exception.MissingCredentialError)
        self.assertEqual(
            'Missing required credential: X-Auth-Key', str(ex._exc_info[1]))

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.create_stack,
                               ctx_no_user, stack_name,
                               template, params, None, {})
        self.assertEqual(ex._exc_info[0], exception.MissingCredentialError)
        self.assertEqual(
            'Missing required credential: X-Auth-User', str(ex._exc_info[1]))

    def test_stack_create_total_resources_equals_max(self):
        stack_name = 'service_create_stack_total_resources_equals_max'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'Resources': {
               'A': {'Type': 'GenericResourceType'},
               'B': {'Type': 'GenericResourceType'},
               'C': {'Type': 'GenericResourceType'}}}

        template = parser.Template(tpl)
        stack = parser.Stack(self.ctx, stack_name, template,
                             environment.Environment({}))

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(parser, 'Stack')

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t,
                     stack.env).AndReturn(stack)

        self.m.ReplayAll()

        cfg.CONF.set_override('max_resources_per_stack', 3)

        result = self.man.create_stack(self.ctx, stack_name, template, params,
                                       None, {})
        self.m.VerifyAll()
        self.assertEqual(stack.identifier(), result)
        self.assertEqual(3, stack.total_resources())
        stack.delete()

    def test_stack_create_total_resources_exceeds_max(self):
        stack_name = 'service_create_stack_total_resources_exceeds_max'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'Resources': {
               'A': {'Type': 'GenericResourceType'},
               'B': {'Type': 'GenericResourceType'},
               'C': {'Type': 'GenericResourceType'}}}
        template = parser.Template(tpl)
        cfg.CONF.set_override('max_resources_per_stack', 2)
        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.create_stack, self.ctx, stack_name,
                               template, params, None, {})
        self.assertEqual(ex._exc_info[0], exception.RequestLimitExceeded)
        self.assertIn(exception.StackResourceLimitExceeded.msg_fmt,
                      str(ex._exc_info[1]))

    def test_stack_validate(self):
        stack_name = 'service_create_test_validate'
        stack = get_wordpress_stack(stack_name, self.ctx)
        setup_mocks(self.m, stack)

        resource = stack['WebServer']

        self.m.ReplayAll()

        resource.properties = Properties(
            resource.properties_schema,
            {
                'ImageId': 'CentOS 5.2',
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

        self.man.tg = DummyThreadGroup()

        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def test_stack_delete_nonexist(self):
        stack_name = 'service_delete_nonexist_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.delete_stack,
                               self.ctx, stack.identifier())
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)
        self.m.VerifyAll()

    def test_stack_delete_acquired_lock(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        st = db_api.stack_get(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)
        self.man.tg = DummyThreadGroup()

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn(self.man.engine_id)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def test_stack_delete_current_engine_active_lock(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        db_api.stack_lock_create(stack.id, self.man.engine_id)

        # Create a fake ThreadGroup too
        self.man.thread_group_mgr.groups[stack.id] = DummyThreadGroup()

        st = db_api.stack_get(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn(self.man.engine_id)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
        self.m.VerifyAll()

    def test_stack_delete_other_engine_active_lock_failed(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        db_api.stack_lock_create(stack.id, "other-engine-fake-uuid")

        st = db_api.stack_get(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")

        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(self.ctx, "other-engine-fake-uuid")\
            .AndReturn(True)

        rpc = proxy.RpcProxy("other-engine-fake-uuid", "1.0")
        msg = rpc.make_msg("stop_stack", stack_identity=mox.IgnoreArg())
        self.m.StubOutWithMock(proxy.RpcProxy, 'call')
        proxy.RpcProxy.call(self.ctx, msg, topic='other-engine-fake-uuid',
                            timeout=cfg.CONF.engine_life_check_timeout)\
            .AndRaise(rpc_common.Timeout)
        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.delete_stack,
                               self.ctx, stack.identifier())
        self.assertEqual(ex._exc_info[0], exception.StopActionFailed)
        self.m.VerifyAll()

    def test_stack_delete_other_engine_active_lock_succeeded(self):
        stack_name = 'service_delete_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()

        # Insert a fake lock into the db
        db_api.stack_lock_create(stack.id, "other-engine-fake-uuid")

        st = db_api.stack_get(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")

        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(self.ctx, "other-engine-fake-uuid")\
            .AndReturn(True)

        rpc = proxy.RpcProxy("other-engine-fake-uuid", "1.0")
        msg = rpc.make_msg("stop_stack", stack_identity=mox.IgnoreArg())
        self.m.StubOutWithMock(proxy.RpcProxy, 'call')
        proxy.RpcProxy.call(self.ctx, msg, topic='other-engine-fake-uuid',
                            timeout=cfg.CONF.engine_life_check_timeout)\
            .AndReturn(None)

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
        db_api.stack_lock_create(stack.id, "other-engine-fake-uuid")

        st = db_api.stack_get(self.ctx, sid)
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=st).MultipleTimes().AndReturn(stack)

        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")

        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(self.ctx, "other-engine-fake-uuid")\
            .AndReturn(False)

        self.m.StubOutWithMock(stack_lock.StackLock, 'acquire')
        stack_lock.StackLock.acquire().AndReturn(None)
        self.m.ReplayAll()

        self.assertIsNone(self.man.delete_stack(self.ctx, stack.identifier()))
        self.man.thread_group_mgr.groups[sid].wait()
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
        self.m.StubOutWithMock(environment, 'Environment')

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.env, timeout_mins=60).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndReturn(None)

        self.m.StubOutWithMock(threadgroup, 'ThreadGroup')
        threadgroup.ThreadGroup().AndReturn(DummyThreadGroup())

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        self.m.VerifyAll()

    def test_stack_update_equals(self):
        stack_name = 'test_stack_update_equals_resource_limit'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'Resources': {
               'A': {'Type': 'GenericResourceType'},
               'B': {'Type': 'GenericResourceType'},
               'C': {'Type': 'GenericResourceType'}}}

        template = parser.Template(tpl)

        old_stack = parser.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        s = db_api.stack_get(self.ctx, sid)

        stack = parser.Stack(self.ctx, stack_name, template)

        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.env, timeout_mins=60).AndReturn(stack)

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
        self.assertEqual(3, old_stack.root_stack.total_resources())
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

        template = parser.Template(tpl)

        create_stack = parser.Stack(self.ctx, stack_name, template)
        sid = create_stack.store()
        create_stack.create()
        self.assertEqual((create_stack.CREATE, create_stack.COMPLETE),
                         create_stack.state)

        s = db_api.stack_get(self.ctx, sid)

        old_stack = parser.Stack.load(self.ctx, stack=s)

        self.assertEqual((old_stack.CREATE, old_stack.COMPLETE),
                         old_stack.state)
        self.assertEqual(create_stack.identifier().arn(),
                         old_stack['A'].properties['Foo'])

        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

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

    def test_nested_stack_update_stack_id_equal(self):
        stack_name = 'test_stack_update_stack_id_equal'
        res._register_class('ResourceWithPropsType',
                            generic_rsrc.ResourceWithProps)
        tpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'some_param': {'Type': 'String'}
            },
            'Resources': {
                'nested': {
                    'Type': 'AWS::CloudFormation::Stack',
                    'Properties': {
                        'TemplateURL': 'https://server.test/nested_tpl',
                        'Parameters': {'some_param': {'Ref': 'some_param'}}
                    }
                }
            }
        }
        nested_tpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'some_param': {'Type': 'String'}
            },
            'Resources': {
                'A': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'AWS::StackId'}
                    }
                }
            }
        }

        self.m.StubOutWithMock(urlfetch, 'get')
        urlfetch.get('https://server.test/nested_tpl').MultipleTimes().\
            AndReturn(json.dumps(nested_tpl))
        mox.Replay(urlfetch.get)

        template = parser.Template(tpl)

        create_env = environment.Environment({'some_param': 'foo'})
        create_stack = parser.Stack(self.ctx, stack_name, template, create_env)
        sid = create_stack.store()
        create_stack.create()
        self.assertEqual((create_stack.CREATE, create_stack.COMPLETE),
                         create_stack.state)

        s = db_api.stack_get(self.ctx, sid)

        old_stack = parser.Stack.load(self.ctx, stack=s)

        self.assertEqual((old_stack.CREATE, old_stack.COMPLETE),
                         old_stack.state)

        old_nested = old_stack['nested'].nested()

        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

        self.m.ReplayAll()

        result = self.man.update_stack(self.ctx, create_stack.identifier(),
                                       tpl, {'some_param': 'bar'}, None, {})

        self.man.thread_group_mgr.groups[sid].wait()

        create_nested = create_stack['nested'].nested()

        self.assertEqual((old_nested.UPDATE, old_nested.COMPLETE),
                         old_nested.state)
        self.assertEqual(create_stack.identifier(), result)
        self.assertIsNotNone(create_stack.identifier().stack_id)
        self.assertEqual(create_nested.identifier().arn(),
                         old_nested['A'].properties['Foo'])

        self.assertEqual(create_nested['A'].id, old_nested['A'].id)

        self.m.VerifyAll()

    def test_stack_update_exceeds_resource_limit(self):
        stack_name = 'test_stack_update_exceeds_resource_limit'
        params = {}
        res._register_class('GenericResourceType',
                            generic_rsrc.GenericResource)
        tpl = {'Resources': {
               'A': {'Type': 'GenericResourceType'},
               'B': {'Type': 'GenericResourceType'},
               'C': {'Type': 'GenericResourceType'}}}

        template = parser.Template(tpl)

        old_stack = parser.Stack(self.ctx, stack_name, template)
        sid = old_stack.store()
        self.assertIsNotNone(sid)

        cfg.CONF.set_override('max_resources_per_stack', 2)

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.update_stack, self.ctx,
                               old_stack.identifier(), template, params,
                               None, {})
        self.assertEqual(ex._exc_info[0], exception.RequestLimitExceeded)
        self.assertIn(exception.StackResourceLimitExceeded.msg_fmt,
                      str(ex._exc_info[1]))

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
        self.m.StubOutWithMock(environment, 'Environment')

        parser.Template(template, files=None).AndReturn(stack.t)
        environment.Environment(params).AndReturn(stack.env)
        parser.Stack(self.ctx, stack.name,
                     stack.t, stack.env, timeout_mins=60).AndReturn(stack)

        self.m.StubOutWithMock(stack, 'validate')
        stack.validate().AndRaise(exception.StackValidationFailed(
            message='fubar'))

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(
            rpc_common.ClientException,
            self.man.update_stack,
            self.ctx, old_stack.identifier(),
            template, params, None, api_args)
        self.assertEqual(ex._exc_info[0], exception.StackValidationFailed)
        self.m.VerifyAll()

    def test_stack_update_nonexist(self):
        stack_name = 'service_update_nonexist_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.update_stack,
                               self.ctx, stack.identifier(), template,
                               params, None, {})
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)
        self.m.VerifyAll()

    def test_stack_update_no_credentials(self):
        stack_name = 'test_stack_update_no_credentials'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        # force check for credentials on create
        old_stack['WebServer'].requires_deferred_auth = True

        sid = old_stack.store()
        s = db_api.stack_get(self.ctx, sid)

        self.ctx = utils.dummy_context(password=None)

        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        self.m.StubOutWithMock(parser, 'Template')
        self.m.StubOutWithMock(environment, 'Environment')
        self.m.StubOutWithMock(self.man, '_get_stack')

        self.man._get_stack(self.ctx, old_stack.identifier()).AndReturn(s)

        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

        parser.Template(template, files=None).AndReturn(old_stack.t)
        environment.Environment(params).AndReturn(old_stack.env)
        parser.Stack(self.ctx, old_stack.name,
                     old_stack.t, old_stack.env,
                     timeout_mins=60).AndReturn(old_stack)

        self.m.ReplayAll()

        api_args = {'timeout_mins': 60}
        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.update_stack, self.ctx,
                               old_stack.identifier(),
                               template, params, None, api_args)
        self.assertEqual(ex._exc_info[0], exception.MissingCredentialError)
        self.assertEqual(
            'Missing required credential: X-Auth-Key', str(ex._exc_info[1]))

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
        self.assertEqual('Missing required credential: X-Auth-User', str(ex))

        # missing password
        ctx = utils.dummy_context(password=None)
        ex = self.assertRaises(exception.MissingCredentialError,
                               self.man._validate_deferred_auth_context,
                               ctx, stack)
        self.assertEqual('Missing required credential: X-Auth-Key', str(ex))


class StackServiceUpdateNotSupportedTest(HeatTestCase):

    scenarios = [
        ('suspend_in_progress', dict(action='SUSPEND', status='IN_PROGRESS')),
        ('suspend_complete', dict(action='SUSPEND', status='COMPLETE')),
        ('suspend_failed', dict(action='SUSPEND', status='FAILED')),
        ('create_in_progress', dict(action='CREATE', status='IN_PROGRESS')),
        ('delete_in_progress', dict(action='DELETE', status='IN_PROGRESS')),
        ('update_in_progress', dict(action='UPDATE', status='IN_PROGRESS')),
        ('rb_in_progress', dict(action='ROLLBACK', status='IN_PROGRESS')),
        ('resume_in_progress', dict(action='RESUME', status='IN_PROGRESS')),
    ]

    def setUp(self):
        super(StackServiceUpdateNotSupportedTest, self).setUp()
        utils.setup_dummy_db()
        utils.reset_dummy_db()
        self.ctx = utils.dummy_context()

        self.m.StubOutWithMock(service.EngineListener, 'start')
        service.EngineListener.start().AndReturn(None)
        self.m.ReplayAll()
        self.man = service.EngineService('a-host', 'a-topic')

    def test_stack_update_during(self):
        stack_name = '%s-%s' % (self.action, self.status)

        old_stack = get_wordpress_stack(stack_name, self.ctx)
        old_stack.action = self.action
        old_stack.status = self.status

        sid = old_stack.store()
        s = db_api.stack_get(self.ctx, sid)

        self.m.StubOutWithMock(parser, 'Stack')
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=s).AndReturn(old_stack)

        self.m.ReplayAll()

        params = {'foo': 'bar'}
        template = '{ "Resources": {} }'
        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.update_stack,
                               self.ctx, old_stack.identifier(), template,
                               params, None, {})
        self.assertEqual(ex._exc_info[0], exception.NotSupported)
        self.m.VerifyAll()


class StackServiceSuspendResumeTest(HeatTestCase):

    def setUp(self):
        super(StackServiceSuspendResumeTest, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()

        self.m.StubOutWithMock(service.EngineListener, 'start')
        service.EngineListener.start().AndReturn(None)
        self.m.ReplayAll()
        self.man = service.EngineService('a-host', 'a-topic')

    def test_stack_suspend(self):
        stack_name = 'service_suspend_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)
        sid = stack.store()
        s = db_api.stack_get(self.ctx, sid)

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

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.stack_suspend, self.ctx,
                               stack.identifier())
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)
        self.m.VerifyAll()

    def test_stack_resume_nonexist(self):
        stack_name = 'service_resume_nonexist_test_stack'
        stack = get_wordpress_stack(stack_name, self.ctx)

        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.man.stack_resume, self.ctx,
                               stack.identifier())
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)
        self.m.VerifyAll()


class StackServiceAuthorizeTest(HeatTestCase):

    def setUp(self):
        super(StackServiceAuthorizeTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.m.StubOutWithMock(service.EngineListener, 'start')
        service.EngineListener.start().AndReturn(None)
        self.m.ReplayAll()

        self.eng = service.EngineService('a-host', 'a-topic')
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')
        res._register_class('ResourceWithPropsType',
                            generic_rsrc.ResourceWithProps)

        utils.setup_dummy_db()

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
        get().AndRaise(service.clients.novaclient.exceptions.NotFound(404))

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


class StackServiceTest(HeatTestCase):

    def setUp(self):
        super(StackServiceTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')

        self.m.StubOutWithMock(service.EngineListener, 'start')
        service.EngineListener.start().AndReturn(None)
        self.m.ReplayAll()

        self.eng = service.EngineService('a-host', 'a-topic')
        cfg.CONF.set_default('heat_stack_user_role', 'stack_user_role')
        res._register_class('ResourceWithPropsType',
                            generic_rsrc.ResourceWithProps)

        utils.setup_dummy_db()

    @mock.patch.object(service.db_api, 'stack_get_all')
    @mock.patch.object(service.service.Service, 'start')
    def test_start_gets_all_stacks(self, mock_super_start, mock_stack_get_all):
        mock_stack_get_all.return_value = []

        self.eng.start()
        mock_stack_get_all.assert_called_once_with(mock.ANY, tenant_safe=False)

    @mock.patch.object(service.db_api, 'stack_get_all')
    @mock.patch.object(service.service.Service, 'start')
    def test_start_watches_all_stacks(self, mock_super_start, mock_get_all):
        s1 = mock.Mock(id=1)
        s2 = mock.Mock(id=2)
        mock_get_all.return_value = [s1, s2]
        mock_watch = mock.Mock()
        self.eng.stack_watch.start_watch_task = mock_watch

        self.eng.start()
        calls = mock_watch.call_args_list
        self.assertEqual(2, mock_watch.call_count)
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
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.identify_stack, self.ctx, 'wibble')
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)

    @stack_context('service_create_existing_test_stack', False)
    def test_stack_create_existing(self):
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.create_stack, self.ctx,
                               self.stack.name, self.stack.t, {}, None, {})
        self.assertEqual(ex._exc_info[0], exception.StackExists)

    @stack_context('service_name_tenants_test_stack', False)
    def test_stack_by_name_tenants(self):
        self.assertEqual(self.stack.id,
                         db_api.stack_get_by_name(self.ctx,
                                                  self.stack.name).id)
        ctx2 = utils.dummy_context(tenant_id='stack_service_test_tenant2')
        self.assertIsNone(db_api.stack_get_by_name(ctx2, self.stack.name))

    @stack_context('service_event_list_test_stack')
    def test_stack_event_list(self):
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = db_api.stack_get(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier(),
                                         show_deleted=True).AndReturn(s)
        self.m.ReplayAll()

        events = self.eng.list_events(self.ctx, self.stack.identifier())

        self.assertEqual(2, len(events))
        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertEqual('WebServer', ev['resource_name'])

            self.assertIn('physical_resource_id', ev)

            self.assertIn('resource_properties', ev)
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            user_data = ev['resource_properties']['UserData']
            self.assertIn('wordpress', user_data)
            self.assertEqual('F17-x86_64-gold',
                             ev['resource_properties']['ImageId'])
            self.assertEqual('m1.large',
                             ev['resource_properties']['InstanceType'])

            self.assertEqual('CREATE', ev['resource_action'])
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_status_reason', ev)
            self.assertEqual('state changed', ev['resource_status_reason'])

            self.assertIn('resource_type', ev)
            self.assertEqual('AWS::EC2::Instance', ev['resource_type'])

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

        def run(stack_id, func, *args):
            func(*args)
            return thread
        self.eng.thread_group_mgr.start = run

        new_tmpl = {'Resources': {'AResource': {'Type':
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

        self.assertEqual(self.stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        events = self.eng.list_events(self.ctx, self.stack.identifier())

        self.assertEqual(6, len(events))

        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertIn('physical_resource_id', ev)
            self.assertIn('resource_properties', ev)
            self.assertIn('resource_status_reason', ev)

            self.assertIn(ev['resource_action'], ('CREATE', 'DELETE'))
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_type', ev)
            self.assertIn(ev['resource_type'], ('AWS::EC2::Instance',
                                                'GenericResourceType'))

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

        self.m.VerifyAll()

    @stack_context('service_event_list_test_stack')
    def test_stack_event_list_by_tenant(self):
        events = self.eng.list_events(self.ctx, None)

        self.assertEqual(2, len(events))
        for ev in events:
            self.assertIn('event_identity', ev)
            self.assertIsInstance(ev['event_identity'], dict)
            self.assertTrue(ev['event_identity']['path'].rsplit('/', 1)[1])

            self.assertIn('resource_name', ev)
            self.assertEqual('WebServer', ev['resource_name'])

            self.assertIn('physical_resource_id', ev)

            self.assertIn('resource_properties', ev)
            # Big long user data field.. it mentions 'wordpress'
            # a few times so this should work.
            user_data = ev['resource_properties']['UserData']
            self.assertIn('wordpress', user_data)
            self.assertEqual('F17-x86_64-gold',
                             ev['resource_properties']['ImageId'])
            self.assertEqual('m1.large',
                             ev['resource_properties']['InstanceType'])

            self.assertEqual('CREATE', ev['resource_action'])
            self.assertIn(ev['resource_status'], ('IN_PROGRESS', 'COMPLETE'))

            self.assertIn('resource_status_reason', ev)
            self.assertEqual('state changed', ev['resource_status_reason'])

            self.assertIn('resource_type', ev)
            self.assertEqual('AWS::EC2::Instance', ev['resource_type'])

            self.assertIn('stack_identity', ev)

            self.assertIn('stack_name', ev)
            self.assertEqual(self.stack.name, ev['stack_name'])

            self.assertIn('event_time', ev)

        self.m.VerifyAll()

    @stack_context('service_list_all_test_stack')
    def test_stack_list_all(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx, stack=mox.IgnoreArg(), resolve_data=False)\
            .AndReturn(self.stack)

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

    @mock.patch.object(db_api, 'stack_get_all')
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
                                                   )

    @mock.patch.object(db_api, 'stack_get_all')
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
                                                   )

    @mock.patch.object(db_api, 'stack_get_all')
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
                                                   )

    @mock.patch.object(db_api, 'stack_count_all')
    def test_count_stacks_passes_filter_info(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, filters={'foo': 'bar'})
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters={'foo': 'bar'},
                                                     tenant_safe=mock.ANY)

    @mock.patch.object(db_api, 'stack_count_all')
    def test_count_stacks_tenant_safe_default_true(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=True)

    @mock.patch.object(db_api, 'stack_count_all')
    def test_count_stacks_passes_tenant_safe_info(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, tenant_safe=False)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     tenant_safe=False)

    @stack_context('service_abandon_stack')
    def test_abandon_stack(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        expected_res = {
            u'WebServer': {
                'action': 'CREATE',
                'metadata': {},
                'name': u'WebServer',
                'resource_data': {},
                'resource_id': 9999,
                'status': 'COMPLETE',
                'type': u'AWS::EC2::Instance'}}
        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn(None)
        self.m.ReplayAll()
        ret = self.eng.abandon_stack(self.ctx, self.stack.identifier())
        self.assertEqual(6, len(ret))
        self.assertEqual('CREATE', ret['action'])
        self.assertEqual('COMPLETE', ret['status'])
        self.assertEqual('service_abandon_stack', ret['name'])
        self.assertIn('id', ret)
        self.assertEqual(expected_res, ret['resources'])
        self.assertEqual(self.stack.t.t, ret['template'])
        self.m.VerifyAll()

    @stack_context('service_abandon_stack')
    def test_abandon_stack_fails_action_in_progress_on_other_engine(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")
        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(
            self.ctx,
            "other-engine-fake-uuid").AndReturn(True)

        self.m.ReplayAll()
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.abandon_stack,
                               self.ctx,
                               self.stack.identifier())
        self.assertEqual(ex._exc_info[0], exception.ActionInProgress)
        self.m.VerifyAll()

    @stack_context('service_abandon_stack')
    def test_abandon_stack_fails_action_in_progress_on_same_engine(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn(self.eng.engine_id)

        self.m.ReplayAll()
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.abandon_stack,
                               self.ctx,
                               self.stack.identifier())
        self.assertEqual(ex._exc_info[0], exception.ActionInProgress)
        self.m.VerifyAll()

    @stack_context('service_abandon_stack')
    def test_abandon_stack_success_other_engine_not_alive(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.StubOutWithMock(stack_lock.StackLock, 'try_acquire')
        stack_lock.StackLock.try_acquire().AndReturn("other-engine-fake-uuid")
        self.m.StubOutWithMock(stack_lock.StackLock, 'engine_alive')
        stack_lock.StackLock.engine_alive(
            self.ctx,
            "other-engine-fake-uuid").AndReturn(False)

        expected_res = {
            u'WebServer': {
                'action': 'CREATE',
                'metadata': {},
                'name': u'WebServer',
                'resource_data': {},
                'resource_id': 9999,
                'status': 'COMPLETE',
                'type': u'AWS::EC2::Instance'}}
        self.m.ReplayAll()
        ret = self.eng.abandon_stack(self.ctx, self.stack.identifier())
        self.assertEqual(6, len(ret))
        self.assertEqual('CREATE', ret['action'])
        self.assertEqual('COMPLETE', ret['status'])
        self.assertEqual('service_abandon_stack', ret['name'])
        self.assertIn('id', ret)
        self.assertEqual(expected_res, ret['resources'])
        self.assertEqual(self.stack.t.t, ret['template'])
        self.m.VerifyAll()

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

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier)
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)
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

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier)
        self.assertEqual(ex._exc_info[0], exception.InvalidTenant)

        self.m.VerifyAll()

    @stack_context('service_describe_test_stack', False)
    def test_stack_describe(self):
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = db_api.stack_get(self.ctx, self.stack.id)
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
        self.assertEqual(['OS::Neutron::RouterGateway'], resources)

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
                },
            },
            'attributes': {
                'foo': {'description': 'A generic attribute'},
                'Foo': {'description': 'Another generic attribute'},
            },
        }

        schema = self.eng.resource_schema(self.ctx, type_name=type_name)
        self.assertEqual(expected, schema)

    def test_resource_schema_nonexist(self):
        self.assertRaises(exception.ResourceTypeNotFound,
                          self.eng.resource_schema,
                          self.ctx, type_name='Bogus')

    @stack_context('service_stack_resource_describe__test_stack')
    def test_stack_resource_describe(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        r = self.eng.describe_stack_resource(self.ctx, self.stack.identifier(),
                                             'WebServer')

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
        self.assertEqual('WebServer', r['resource_name'])

        self.m.VerifyAll()

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

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.describe_stack_resource,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)

        self.m.VerifyAll()

    @stack_context('service_resource_describe_nonexist_test_stack')
    def test_stack_resource_describe_nonexist_resource(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)

        self.m.ReplayAll()
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(ex._exc_info[0], exception.ResourceNotFound)

        self.m.VerifyAll()

    @stack_context('service_resource_describe_user_deny_test_stack')
    def test_stack_resource_describe_stack_user_deny(self):
        self.ctx.roles = [cfg.CONF.heat_stack_user_role]
        self.m.StubOutWithMock(service.EngineService, '_authorize_stack_user')
        service.EngineService._authorize_stack_user(self.ctx, mox.IgnoreArg(),
                                                    'foo').AndReturn(False)
        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.describe_stack_resource,
                               self.ctx, self.stack.identifier(), 'foo')
        self.assertEqual(ex._exc_info[0], exception.Forbidden)

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

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.describe_stack_resources,
                               self.ctx, non_exist_identifier, 'WebServer')
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)

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
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.find_physical_resource,
                               self.ctx, 'foo')
        self.assertEqual(ex._exc_info[0], exception.PhysicalResourceNotFound)

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

    def test_stack_resources_list_nonexist_stack(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.StackNotFound(stack_name='test')
        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        service.EngineService._get_stack(
            self.ctx, non_exist_identifier).AndRaise(stack_not_found_exc)
        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.list_stack_resources,
                               self.ctx, non_exist_identifier)
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)

        self.m.VerifyAll()

    def test_signal_reception(self):
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
        s = db_api.stack_get(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(service.EngineService, 'load_user_creds')
        service.EngineService.load_user_creds(
            mox.IgnoreArg()).AndReturn(self.ctx)

        self.m.StubOutWithMock(res.Resource, 'signal')
        res.Resource.signal(mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()

        self.eng.resource_signal(self.ctx,
                                 dict(self.stack.identifier()),
                                 'WebServerScaleDownPolicy',
                                 test_data)
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
        s = db_api.stack_get(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)

        self.m.StubOutWithMock(service.EngineService, 'load_user_creds')
        service.EngineService.load_user_creds(
            mox.IgnoreArg()).AndReturn(self.ctx)
        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.resource_signal, self.ctx,
                               dict(self.stack.identifier()),
                               'resource_does_not_exist',
                               test_data)
        self.assertEqual(ex._exc_info[0], exception.ResourceNotFound)
        self.m.VerifyAll()
        self.stack.delete()

    @stack_context('service_metadata_test_stack')
    def test_metadata(self):
        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        pre_update_meta = self.stack['WebServer'].metadata

        self.m.StubOutWithMock(service.EngineService, '_get_stack')
        s = db_api.stack_get(self.ctx, self.stack.id)
        service.EngineService._get_stack(self.ctx,
                                         self.stack.identifier()).AndReturn(s)
        self.m.StubOutWithMock(instances.Instance, 'metadata_update')
        instances.Instance.metadata_update(new_metadata=test_metadata)
        self.m.StubOutWithMock(service.EngineService, 'load_user_creds')
        service.EngineService.load_user_creds(
            mox.IgnoreArg()).AndReturn(self.ctx)
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
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.metadata_update,
                               self.ctx, non_exist_identifier,
                               'WebServer', test_metadata)
        self.assertEqual(ex._exc_info[0], exception.StackNotFound)
        self.m.VerifyAll()

    @stack_context('service_metadata_err_resource_test_stack', False)
    def test_metadata_err_resource(self):
        self.m.StubOutWithMock(parser.Stack, 'load')
        parser.Stack.load(self.ctx,
                          stack=mox.IgnoreArg()).AndReturn(self.stack)
        self.m.ReplayAll()

        test_metadata = {'foo': 'bar', 'baz': 'quux', 'blarg': 'wibble'}
        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.metadata_update,
                               self.ctx, dict(self.stack.identifier()),
                               'NooServer', test_metadata)
        self.assertEqual(ex._exc_info[0], exception.ResourceNotFound)

        self.m.VerifyAll()

    @stack_context('periodic_watch_task_not_created')
    def test_periodic_watch_task_not_created(self):
        self.eng.thread_group_mgr.groups[self.stack.id] = DummyThreadGroup()
        self.eng.stack_watch.start_watch_task(self.stack.id, self.ctx)
        self.assertEqual(
            [], self.eng.thread_group_mgr.groups[self.stack.id].threads)

    def test_periodic_watch_task_created(self):
        stack = get_stack('period_watch_task_created',
                          utils.dummy_context(),
                          alarm_template)
        self.stack = stack
        self.m.ReplayAll()
        stack.store()
        stack.create()
        self.eng.thread_group_mgr.groups[stack.id] = DummyThreadGroup()
        self.eng.stack_watch.start_watch_task(stack.id, self.ctx)
        expected = [self.eng.stack_watch.periodic_watcher_task]
        observed = self.eng.thread_group_mgr.groups[stack.id].threads
        self.assertEqual(expected, observed)
        self.stack.delete()

    def test_periodic_watch_task_created_nested(self):
        self.m.StubOutWithMock(urlfetch, 'get')
        urlfetch.get('https://server.test/alarm.template').MultipleTimes().\
            AndReturn(alarm_template)
        self.m.ReplayAll()

        stack = get_stack('period_watch_task_created_nested',
                          utils.dummy_context(),
                          nested_alarm_template)
        setup_keystone_mocks(self.m, stack)
        self.stack = stack
        self.m.ReplayAll()
        stack.store()
        stack.create()
        self.eng.thread_group_mgr.groups[stack.id] = DummyThreadGroup()
        self.eng.stack_watch.start_watch_task(stack.id, self.ctx)
        self.assertEqual([self.eng.stack_watch.periodic_watcher_task],
                         self.eng.thread_group_mgr.groups[stack.id].threads)
        self.stack.delete()

    @stack_context('service_show_watch_test_stack', False)
    @utils.wr_delete_after
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

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.show_watch,
                               self.ctx, watch_name="nonexistent")
        self.assertEqual(ex._exc_info[0], exception.WatchRuleNotFound)

        # Check the response has all keys defined in the engine API
        for key in engine_api.WATCH_KEYS:
            self.assertIn(key, result[0])

    @stack_context('service_show_watch_metric_test_stack', False)
    @utils.wr_delete_after
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
        watch = db_api.watch_rule_get_by_name(self.ctx, 'show_watch_metric_1')
        self.assertIsNotNone(watch)
        values = {'watch_rule_id': watch.id,
                  'data': {u'Namespace': u'system/linux',
                           u'ServiceFailure': {
                               u'Units': u'Counter', u'Value': 1}}}
        watch = db_api.watch_data_create(self.ctx, values)

        # Check there is one result returned
        result = self.eng.show_watch_metric(self.ctx,
                                            metric_namespace=None,
                                            metric_name=None)
        self.assertEqual(1, len(result))

        # Create another metric datapoint and check we get two
        watch = db_api.watch_data_create(self.ctx, values)
        result = self.eng.show_watch_metric(self.ctx,
                                            metric_namespace=None,
                                            metric_name=None)
        self.assertEqual(2, len(result))

        # Check the response has all keys defined in the engine API
        for key in engine_api.WATCH_DATA_KEYS:
            self.assertIn(key, result[0])

    @stack_context('service_show_watch_state_test_stack')
    @utils.wr_delete_after
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
            signal = "dummyfoo"

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
        self.assertEqual(state, result[engine_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [], self.eng.thread_group_mgr.groups[self.stack.id].threads)

        state = watchrule.WatchRule.NORMAL
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[engine_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [], self.eng.thread_group_mgr.groups[self.stack.id].threads)

        state = watchrule.WatchRule.ALARM
        result = self.eng.set_watch_state(self.ctx,
                                          watch_name="OverrideAlarm",
                                          state=state)
        self.assertEqual(state, result[engine_api.WATCH_STATE_VALUE])
        self.assertEqual(
            [DummyAction.signal],
            self.eng.thread_group_mgr.groups[self.stack.id].threads)

        self.m.VerifyAll()

    @stack_context('service_show_watch_state_badstate_test_stack')
    @utils.wr_delete_after
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
            watchrule.WatchRule.set_watch_state(state)\
                .InAnyOrder().AndRaise(ValueError)
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
        watchrule.WatchRule.load(self.ctx, "nonexistent")\
            .AndRaise(exception.WatchRuleNotFound(watch_name='test'))
        self.m.ReplayAll()

        ex = self.assertRaises(rpc_common.ClientException,
                               self.eng.set_watch_state,
                               self.ctx, watch_name="nonexistent",
                               state=state)
        self.assertEqual(ex._exc_info[0], exception.WatchRuleNotFound)
        self.m.VerifyAll()

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
        templ = parser.Template(lazy_load_template)
        stack = parser.Stack(self.ctx, stack_name, templ,
                             environment.Environment({}))

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
        tpl = {
            'Description': 'Lorem ipsum.',
            'Resources': {
                'SampleResource1': {'Type': 'GenericResource1'},
                'SampleResource2': {'Type': 'GenericResource2'},
            }
        }

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
        ex = self.assertRaises(rpc_common.ClientException,
                               self._preview_stack)
        self.assertEqual(ex._exc_info[0], exception.StackExists)

    @mock.patch.object(service.api, 'format_stack_preview', new=mock.Mock())
    @mock.patch.object(service.parser, 'Stack')
    def test_preview_stack_checks_stack_validity(self, mock_parser):
        exc = exception.StackValidationFailed(message='Validation Failed')
        mock_parsed_stack = mock.Mock()
        mock_parsed_stack.validate.side_effect = exc
        mock_parser.return_value = mock_parsed_stack
        ex = self.assertRaises(rpc_common.ClientException,
                               self._preview_stack)
        self.assertEqual(ex._exc_info[0], exception.StackValidationFailed)

    @mock.patch.object(service.db_api, 'stack_get_by_name')
    def test_validate_new_stack_checks_existing_stack(self, mock_stack_get):
        mock_stack_get.return_value = 'existing_db_stack'
        self.assertRaises(exception.StackExists, self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', 'parsed_template')

    @mock.patch.object(service.db_api, 'stack_count_all')
    def test_validate_new_stack_checks_stack_limit(self, mock_db_count):
        cfg.CONF.set_override('max_stacks_per_tenant', 99)
        mock_db_count.return_value = 99
        template = service.parser.Template({})
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', template)

    def test_validate_new_stack_checks_resource_limit(self):
        cfg.CONF.set_override('max_resources_per_stack', 5)
        template = {'Resources': [1, 2, 3, 4, 5, 6]}
        parsed_template = service.parser.Template(template)
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', parsed_template)


class SoftwareConfigServiceTest(HeatTestCase):

    def setUp(self):
        super(SoftwareConfigServiceTest, self).setUp()
        self.ctx = utils.dummy_context()

        self.m.StubOutWithMock(service.EngineListener, 'start')
        service.EngineListener.start().AndReturn(None)
        self.m.ReplayAll()
        self.engine = service.EngineService('a-host', 'a-topic')
        utils.setup_dummy_db()

    def _create_software_config(
            self, group='Heat::Shell', name='config_mysql', config=None,
            inputs=[], outputs=[], options={}):
        return self.engine.create_software_config(
            self.ctx, group, name, config, inputs, outputs, options)

    def test_show_software_config(self):
        config_id = str(uuid.uuid4())

        ex = self.assertRaises(rpc_common.ClientException,
                               self.engine.show_software_config,
                               self.ctx, config_id)
        self.assertEqual(ex._exc_info[0], exception.NotFound)

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

        ex = self.assertRaises(rpc_common.ClientException,
                               self.engine.show_software_config,
                               self.ctx, config_id)
        self.assertEqual(ex._exc_info[0], exception.NotFound)

    def _create_software_deployment(self, config_id=None, input_values={},
                                    action='INIT',
                                    status='COMPLETE', status_reason='',
                                    config_group=None,
                                    server_id=str(uuid.uuid4()),
                                    config_name=None,
                                    stack_user_project_id=None):
        if config_id is None:
            config = self._create_software_config(group=config_group,
                                                  name=config_name)
            config_id = config['id']
        return self.engine.create_software_deployment(
            self.ctx, server_id, config_id, input_values,
            action, status, status_reason, stack_user_project_id)

    def test_list_software_deployments(self):
        deployment = self._create_software_deployment()
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

    def test_metadata_software_deployments(self):
        server_id = str(uuid.uuid4())
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
        ex = self.assertRaises(rpc_common.ClientException,
                               self.engine.show_software_deployment,
                               self.ctx, deployment_id)
        self.assertEqual(ex._exc_info[0], exception.NotFound)

        deployment = self._create_software_deployment()
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        self.assertEqual(
            deployment,
            self.engine.show_software_deployment(self.ctx, deployment_id))

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

    def test_update_software_deployment(self):
        deployment = self._create_software_deployment()
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        deployment_action = deployment['action']
        self.assertEqual('INIT', deployment_action)
        config_id = deployment['config_id']
        self.assertIsNotNone(config_id)
        updated = self.engine.update_software_deployment(
            self.ctx, deployment_id=deployment_id, config_id=config_id,
            input_values={}, output_values={}, action='DEPLOY',
            status='WAITING', status_reason='')
        self.assertIsNotNone(updated)
        self.assertEqual(config_id, updated['config_id'])
        self.assertEqual('DEPLOY', updated['action'])
        self.assertEqual('WAITING', updated['status'])

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
                self.ctx, deployment_id, **values)
            for key, value in kwargs.iteritems():
                self.assertEqual(value, updated[key])

        check_software_deployment_updated(config_id=config_id)
        check_software_deployment_updated(input_values={'foo': 'fooooo'})
        check_software_deployment_updated(output_values={'bar': 'baaaaa'})
        check_software_deployment_updated(action='DEPLOY')
        check_software_deployment_updated(status='COMPLETE')
        check_software_deployment_updated(status_reason='Done!')

    def test_delete_software_deployment(self):
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(rpc_common.ClientException,
                               self.engine.delete_software_deployment,
                               self.ctx, deployment_id)
        self.assertEqual(ex._exc_info[0], exception.NotFound)

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


class ThreadGroupManagerTest(HeatTestCase):
    def setUp(self):
        super(ThreadGroupManagerTest, self).setUp()
        self.f = 'function'
        self.fargs = ('spam', 'ham', 'eggs')
        self.fkwargs = {'foo': 'bar'}
        self.cnxt = 'ctxt'
        self.engine_id = 'engine_id'
        self.stack = mock.Mock()
        self.lock_mock = mock.Mock()
        self.stlock_mock = self.useFixture(
            mockpatch.Patch('heat.engine.service.stack_lock')).mock
        self.stlock_mock.StackLock.return_value = self.lock_mock
        self.tg_mock = mock.Mock()
        self.thg_mock = self.useFixture(
            mockpatch.Patch('heat.engine.service.threadgroup')).mock
        self.thg_mock.ThreadGroup.return_value = self.tg_mock
        self.cfg_mock = self.useFixture(
            mockpatch.Patch('heat.engine.service.cfg')).mock

    def test_tgm_start_with_acquired_lock(self):
        thm = service.ThreadGroupManager()
        with self.patchobject(thm, 'start'):
            thm.start_with_acquired_lock(self.stack, self.lock_mock,
                                         self.f, *self.fargs,
                                         **self.fkwargs)
            thm.start.assert_called_with(self.stack.id, self.f,
                                         *self.fargs, **self.fkwargs)
            self.assertEqual(self.stack.id,
                             thm.start().link.call_args[0][1])

            self.assertFalse(self.lock_mock.release.called)

    def test_tgm_start_with_acquired_lock_fail(self):
        thm = service.ThreadGroupManager()
        with self.patchobject(thm, 'start'):
            with mock.patch('heat.engine.service.excutils'):
                thm.start.side_effect = Exception
                thm.start_with_acquired_lock(self.stack, self.lock_mock,
                                             self.f, *self.fargs,
                                             **self.fkwargs)
                self.lock_mock.release.assert_called_with(self.stack.id)

    def test_tgm_start_with_lock(self):
        thm = service.ThreadGroupManager()
        with self.patchobject(thm, 'start_with_acquired_lock'):
            thm.start_with_lock(self.cnxt, self.stack, self.engine_id, self.f,
                                *self.fargs, **self.fkwargs)
            self.stlock_mock.StackLock.assert_called_with(self.cnxt,
                                                          self.stack,
                                                          self.engine_id)
            self.lock_mock.acquire.assert_called_once()
            thm.start_with_acquired_lock.assert_called_once()
            calls = thm.start_with_acquired_lock.call_args
            self.assertEqual((self.stack, self.lock_mock, self.f) + self.fargs,
                             calls[0])
            self.assertEqual(self.fkwargs, calls[1])

    def test_tgm_start(self):
        stack_id = 'test'

        thm = service.ThreadGroupManager()
        ret = thm.start(stack_id, self.f, *self.fargs, **self.fkwargs)

        self.assertEqual(self.tg_mock, thm.groups['test'])
        self.tg_mock.add_thread.assert_called_with(self.f, *self.fargs,
                                                   **self.fkwargs)
        self.assertEqual(self.tg_mock.add_thread(), ret)

    def test_tgm_stop(self):
        stack_id = 'test'

        thm = service.ThreadGroupManager()
        thm.start(stack_id, self.f, *self.fargs, **self.fkwargs)
        thm.stop(stack_id)

        self.tg_mock.stop.assert_called_once()
        self.assertNotIn(stack_id, thm.groups)

    def test_tgm_add_timer(self):
        stack_id = 'test'

        thm = service.ThreadGroupManager()
        thm.add_timer(stack_id, self.f, *self.fargs, **self.fkwargs)

        self.assertEqual(thm.groups[stack_id], self.tg_mock)
        self.tg_mock.add_timer.assert_called_with(
            self.cfg_mock.CONF.periodic_interval,
            self.f, *self.fargs, **self.fkwargs)
