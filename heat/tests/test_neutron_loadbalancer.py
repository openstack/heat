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

import copy
import mox
from oslo.config import cfg
import six

from neutronclient.common import exceptions
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine.resources.neutron import loadbalancer
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes as nova_fakes


health_monitor_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources",
  "Parameters" : {},
  "Resources" : {
    "monitor": {
      "Type": "OS::Neutron::HealthMonitor",
      "Properties": {
        "type": "HTTP",
        "delay": 3,
        "max_retries": 5,
        "timeout": 10
      }
    }
  }
}
'''

pool_template_with_vip_subnet = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources",
  "Parameters" : {},
  "Resources" : {
    "pool": {
      "Type": "OS::Neutron::Pool",
      "Properties": {
        "protocol": "HTTP",
        "subnet": "sub123",
        "lb_method": "ROUND_ROBIN",
        "vip": {
          "protocol_port": 80,
          "subnet": "sub9999"
        }
      }
    }
  }
}
'''

pool_template_deprecated = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources",
  "Parameters" : {},
  "Resources" : {
    "pool": {
      "Type": "OS::Neutron::Pool",
      "Properties": {
        "protocol": "HTTP",
        "subnet_id": "sub123",
        "lb_method": "ROUND_ROBIN",
        "vip": {
          "protocol_port": 80
        }
      }
    }
  }
}
'''

pool_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources",
  "Parameters" : {},
  "Resources" : {
    "pool": {
      "Type": "OS::Neutron::Pool",
      "Properties": {
        "protocol": "HTTP",
        "subnet": "sub123",
        "lb_method": "ROUND_ROBIN",
        "vip": {
          "protocol_port": 80
        }
      }
    }
  }
}
'''


member_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer member",
  "Resources" : {
    "member": {
      "Type": "OS::Neutron::PoolMember",
      "Properties": {
        "protocol_port": 8080,
        "pool_id": "pool123",
        "address": "1.2.3.4"
      }
    }
  }
}
'''

lb_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources",
  "Parameters" : {},
  "Resources" : {
    "lb": {
      "Type": "OS::Neutron::LoadBalancer",
      "Properties": {
        "protocol_port": 8080,
        "pool_id": "pool123",
        "members": ["1234"]
      }
    }
  }
}
'''


pool_with_session_persistence_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources wit",
  "Parameters" : {},
  "Resources" : {
    "pool": {
      "Type": "OS::Neutron::Pool",
      "Properties": {
        "protocol": "HTTP",
        "subnet": "sub123",
        "lb_method": "ROUND_ROBIN",
        "vip": {
          "protocol_port": 80,
          "session_persistence": {
            "type": "APP_COOKIE",
            "cookie_name": "cookie"
          }
        }
      }
    }
  }
}
'''


pool_with_health_monitors_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources",
  "Parameters" : {},
  "Resources" : {
    "monitor1": {
      "Type": "OS::Neutron::HealthMonitor",
      "Properties": {
        "type": "HTTP",
        "delay": 3,
        "max_retries": 5,
        "timeout": 10
        }
    },
    "monitor2": {
      "Type": "OS::Neutron::HealthMonitor",
      "Properties": {
        "type": "HTTP",
        "delay": 3,
        "max_retries": 5,
        "timeout": 10
        }
    },
    "pool": {
      "Type": "OS::Neutron::Pool",
      "Properties": {
        "protocol": "HTTP",
        "subnet_id": "sub123",
        "lb_method": "ROUND_ROBIN",
        "vip": {
          "protocol_port": 80
        },
        "monitors": [
          {"Ref": "monitor1"},
          {"Ref": "monitor2"}
        ]
      }
    }
  }
}
'''


class HealthMonitorTest(HeatTestCase):

    def setUp(self):
        super(HealthMonitorTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'show_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'update_health_monitor')
        self.stub_keystoneclient()

    def create_health_monitor(self):
        neutronclient.Client.create_health_monitor({
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}
        ).AndReturn({'health_monitor': {'id': '5678'}})

        snippet = template_format.parse(health_monitor_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return loadbalancer.HealthMonitor(
            'monitor', resource_defns['monitor'], stack)

    def test_create(self):
        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        neutronclient.Client.create_health_monitor({
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}
        ).AndRaise(exceptions.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(health_monitor_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.HealthMonitor(
            'monitor', resource_defns['monitor'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_health_monitor('5678')
        neutronclient.Client.show_health_monitor('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_health_monitor('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_health_monitor('5678').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_health_monitor()
        neutronclient.Client.show_health_monitor('5678').MultipleTimes(
        ).AndReturn(
            {'health_monitor': {'admin_state_up': True, 'delay': 3}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual(3, rsrc.FnGetAtt('delay'))
        self.m.VerifyAll()

    def test_attribute_failed(self):
        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (monitor subnet_id) is incorrect.',
            six.text_type(error))
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_health_monitor()
        neutronclient.Client.update_health_monitor(
            '5678', {'health_monitor': {'delay': 10}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['delay'] = 10
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.m.VerifyAll()


class PoolTest(HeatTestCase):

    def setUp(self):
        super(PoolTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_pool')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_pool')
        self.m.StubOutWithMock(neutronclient.Client, 'show_pool')
        self.m.StubOutWithMock(neutronclient.Client, 'update_pool')
        self.m.StubOutWithMock(neutronclient.Client,
                               'associate_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client,
                               'disassociate_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'create_vip')
        self.m.StubOutWithMock(neutronV20, 'find_resourceid_by_name_or_id')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_vip')
        self.m.StubOutWithMock(neutronclient.Client, 'show_vip')
        self.stub_keystoneclient()

    def create_pool(self, resolve_neutron=True, with_vip_subnet=False):
        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.show_pool('5678').AndReturn(
            {'pool': {'status': 'ACTIVE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'ACTIVE'}})
        stvipvsn = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub9999',
                'pool_id': '5678', 'protocol_port': 80}
        }

        stvippsn = copy.deepcopy(stvipvsn)
        stvippsn['vip']['subnet_id'] = 'sub123'

        if resolve_neutron and with_vip_subnet:
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'subnet',
                'sub123'
            ).AndReturn('sub123')
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'subnet',
                'sub9999'
            ).AndReturn('sub9999')
            snippet = template_format.parse(pool_template_with_vip_subnet)
            neutronclient.Client.create_vip(stvipvsn
                                            ).AndReturn({'vip': {'id': 'xyz'}})

        elif resolve_neutron and not with_vip_subnet:
            neutronV20.find_resourceid_by_name_or_id(
                mox.IsA(neutronclient.Client),
                'subnet',
                'sub123'
            ).AndReturn('sub123')
            snippet = template_format.parse(pool_template)
            neutronclient.Client.create_vip(stvippsn
                                            ).AndReturn({'vip': {'id': 'xyz'}})
        else:
            snippet = template_format.parse(pool_template_deprecated)
            neutronclient.Client.create_vip(stvippsn
                                            ).AndReturn({'vip': {'id': 'xyz'}})
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return loadbalancer.Pool(
            'pool', resource_defns['pool'], stack)

    def test_create(self):
        self._test_create()

    def test_create_deprecated(self):
        self._test_create(resolve_neutron=False, with_vip_subnet=False)

    def _test_create(self, resolve_neutron=True, with_vip_subnet=False):
        rsrc = self.create_pool(resolve_neutron, with_vip_subnet)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_with_vip_subnet(self):
        rsrc = self.create_pool(with_vip_subnet=True)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_pending(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub123'
        ).AndReturn('sub123')

        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.create_vip({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}
        ).AndReturn({'vip': {'id': 'xyz'}})
        neutronclient.Client.show_pool('5678').AndReturn(
            {'pool': {'status': 'PENDING_CREATE'}})
        neutronclient.Client.show_pool('5678').MultipleTimes().AndReturn(
            {'pool': {'status': 'ACTIVE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'PENDING_CREATE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'ACTIVE'}})

        snippet = template_format.parse(pool_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], stack)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed_error_status(self):
        cfg.CONF.set_override('action_retry_limit', 0)

        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub123'
        ).AndReturn('sub123')

        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.create_vip({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}
        ).AndReturn({'vip': {'id': 'xyz'}})
        neutronclient.Client.show_pool('5678').AndReturn(
            {'pool': {'status': 'ERROR', 'name': '5678'}})

        snippet = template_format.parse(pool_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], stack)
        self.m.ReplayAll()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'ResourceInError: Went to status ERROR due to "error in pool"',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed_unexpected_vip_status(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub123'
        ).AndReturn('sub123')

        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.create_vip({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}
        ).AndReturn({'vip': {'id': 'xyz'}})
        neutronclient.Client.show_pool('5678').MultipleTimes().AndReturn(
            {'pool': {'status': 'ACTIVE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'SOMETHING', 'name': 'xyz'}})

        snippet = template_format.parse(pool_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], stack)
        self.m.ReplayAll()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'ResourceUnknownStatus: Pool creation failed due to vip - '
            'Unknown status SOMETHING',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub123'
        ).AndReturn('sub123')

        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndRaise(exceptions.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(pool_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_create_with_session_persistence(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub123'
        ).AndReturn('sub123')
        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.create_vip({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80,
                'session_persistence': {
                    'type': 'APP_COOKIE',
                    'cookie_name': 'cookie'}}}
        ).AndReturn({'vip': {'id': 'xyz'}})
        neutronclient.Client.show_pool('5678').AndReturn(
            {'pool': {'status': 'ACTIVE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'ACTIVE'}})

        snippet = template_format.parse(pool_with_session_persistence_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], stack)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_failing_validation_with_session_persistence(self):
        msg = _('Property cookie_name is required, when '
                'session_persistence type is set to APP_COOKIE.')
        snippet = template_format.parse(pool_with_session_persistence_template)
        pool = snippet['Resources']['pool']
        persistence = pool['Properties']['vip']['session_persistence']

        # When persistence type is set to APP_COOKIE, cookie_name is required
        persistence['type'] = 'APP_COOKIE'
        persistence['cookie_name'] = None

        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        resource = loadbalancer.Pool('pool', resource_defns['pool'], stack)

        error = self.assertRaises(exception.StackValidationFailed,
                                  resource.validate)
        self.assertEqual(msg, six.text_type(error))

    def test_validation_not_failing_without_session_persistence(self):
        snippet = template_format.parse(pool_template)

        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        resource = loadbalancer.Pool('pool', resource_defns['pool'], stack)

        self.assertIsNone(resource.validate())

    def test_properties_are_prepared_for_session_persistence(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub123'
        ).AndReturn('sub123')

        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.create_vip({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80,
                'session_persistence': {'type': 'HTTP_COOKIE'}}}
        ).AndReturn({'vip': {'id': 'xyz'}})
        neutronclient.Client.show_pool('5678').AndReturn(
            {'pool': {'status': 'ACTIVE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'ACTIVE'}})

        snippet = template_format.parse(pool_with_session_persistence_template)
        pool = snippet['Resources']['pool']
        persistence = pool['Properties']['vip']['session_persistence']

        # change persistence type to HTTP_COOKIE that not require cookie_name
        persistence['type'] = 'HTTP_COOKIE'
        del persistence['cookie_name']

        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        resource = loadbalancer.Pool('pool', resource_defns['pool'], stack)

        # assert that properties contain cookie_name property with None value
        persistence = resource.properties['vip']['session_persistence']
        self.assertIn('cookie_name', persistence)
        self.assertIsNone(persistence['cookie_name'])

        self.m.ReplayAll()
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE), resource.state)
        self.m.VerifyAll()

    def test_delete(self):
        rsrc = self.create_pool()
        neutronclient.Client.delete_vip('xyz')
        neutronclient.Client.show_vip('xyz').AndRaise(
            exceptions.NeutronClientException(status_code=404))
        neutronclient.Client.delete_pool('5678')
        neutronclient.Client.show_pool('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_vip('xyz').AndRaise(
            exceptions.NeutronClientException(status_code=404))
        neutronclient.Client.delete_pool('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_pool()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_vip_failed(self):
        neutronclient.Client.delete_vip('xyz').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_pool()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_vip('xyz').AndRaise(
            exceptions.NeutronClientException(status_code=404))
        neutronclient.Client.delete_pool('5678').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_pool()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_pool()
        neutronclient.Client.show_pool('5678').MultipleTimes(
        ).AndReturn(
            {'pool': {'admin_state_up': True, 'lb_method': 'ROUND_ROBIN'}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual('ROUND_ROBIN', rsrc.FnGetAtt('lb_method'))
        self.m.VerifyAll()

    def test_vip_attribute(self):
        rsrc = self.create_pool()
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'address': '10.0.0.3', 'name': 'xyz'}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual({'address': '10.0.0.3', 'name': 'xyz'},
                         rsrc.FnGetAtt('vip'))
        self.m.VerifyAll()

    def test_attribute_failed(self):
        rsrc = self.create_pool()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'net_id')
        self.assertEqual(
            'The Referenced Attribute (pool net_id) is incorrect.',
            six.text_type(error))
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_pool()
        neutronclient.Client.update_pool(
            '5678', {'pool': {'admin_state_up': False}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['admin_state_up'] = False
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.m.VerifyAll()

    def test_update_monitors(self):
        neutronV20.find_resourceid_by_name_or_id(
            mox.IsA(neutronclient.Client),
            'subnet',
            'sub123'
        ).AndReturn('sub123')
        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.associate_health_monitor(
            '5678', {'health_monitor': {'id': 'mon123'}})
        neutronclient.Client.associate_health_monitor(
            '5678', {'health_monitor': {'id': 'mon456'}})
        neutronclient.Client.create_vip({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}
        ).AndReturn({'vip': {'id': 'xyz'}})
        neutronclient.Client.show_pool('5678').AndReturn(
            {'pool': {'status': 'ACTIVE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'ACTIVE'}})
        neutronclient.Client.disassociate_health_monitor(
            '5678', 'mon456')
        neutronclient.Client.associate_health_monitor(
            '5678', {'health_monitor': {'id': 'mon789'}})

        snippet = template_format.parse(pool_template)
        stack = utils.parse_stack(snippet)
        snippet['Resources']['pool']['Properties']['monitors'] = [
            'mon123', 'mon456']
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.Pool('pool', resource_defns['pool'], stack)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['monitors'] = ['mon123', 'mon789']
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.m.VerifyAll()


class PoolMemberTest(HeatTestCase):

    def setUp(self):
        super(PoolMemberTest, self).setUp()
        self.fc = nova_fakes.FakeClient()
        self.m.StubOutWithMock(neutronclient.Client, 'create_member')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_member')
        self.m.StubOutWithMock(neutronclient.Client, 'update_member')
        self.m.StubOutWithMock(neutronclient.Client, 'show_member')
        self.stub_keystoneclient()

    def create_member(self):
        neutronclient.Client.create_member({
            'member': {
                'pool_id': 'pool123', 'protocol_port': 8080,
                'address': '1.2.3.4', 'admin_state_up': True}}
        ).AndReturn({'member': {'id': 'member5678'}})
        snippet = template_format.parse(member_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return loadbalancer.PoolMember(
            'member', resource_defns['member'], stack)

    def test_create(self):
        rsrc = self.create_member()

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('member5678', rsrc.resource_id)
        self.m.VerifyAll()

    def test_create_optional_parameters(self):
        neutronclient.Client.create_member({
            'member': {
                'pool_id': 'pool123', 'protocol_port': 8080,
                'weight': 100, 'admin_state_up': False,
                'address': '1.2.3.4'}}
        ).AndReturn({'member': {'id': 'member5678'}})
        snippet = template_format.parse(member_template)
        snippet['Resources']['member']['Properties']['admin_state_up'] = False
        snippet['Resources']['member']['Properties']['weight'] = 100
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = loadbalancer.PoolMember(
            'member', resource_defns['member'], stack)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('member5678', rsrc.resource_id)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_member()
        neutronclient.Client.show_member('member5678').MultipleTimes(
        ).AndReturn(
            {'member': {'admin_state_up': True, 'weight': 5}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual(5, rsrc.FnGetAtt('weight'))
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_member()
        neutronclient.Client.update_member(
            'member5678', {'member': {'pool_id': 'pool456'}})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['pool_id'] = 'pool456'

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.m.VerifyAll()

    def test_delete(self):
        rsrc = self.create_member()
        neutronclient.Client.delete_member(u'member5678')
        neutronclient.Client.show_member(u'member5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_missing_member(self):
        rsrc = self.create_member()
        neutronclient.Client.delete_member(u'member5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()


class LoadBalancerTest(HeatTestCase):

    def setUp(self):
        super(LoadBalancerTest, self).setUp()
        self.fc = nova_fakes.FakeClient()
        self.m.StubOutWithMock(neutronclient.Client, 'create_member')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_member')
        self.stub_keystoneclient()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')

    def create_load_balancer(self):
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        neutronclient.Client.create_member({
            'member': {
                'pool_id': 'pool123', 'protocol_port': 8080,
                'address': '1.2.3.4'}}
        ).AndReturn({'member': {'id': 'member5678'}})
        snippet = template_format.parse(lb_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return loadbalancer.LoadBalancer(
            'lb', resource_defns['lb'], stack)

    def test_create(self):
        rsrc = self.create_load_balancer()

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_load_balancer()
        neutronclient.Client.delete_member(u'member5678')
        neutronclient.Client.create_member({
            'member': {
                'pool_id': 'pool123', 'protocol_port': 8080,
                'address': '4.5.6.7'}}
        ).AndReturn({'member': {'id': 'memberxyz'}})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['members'] = ['5678']

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.m.VerifyAll()

    def test_update_missing_member(self):
        rsrc = self.create_load_balancer()
        neutronclient.Client.delete_member(u'member5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['members'] = []

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        rsrc = self.create_load_balancer()
        neutronclient.Client.delete_member(u'member5678')

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_missing_member(self):
        rsrc = self.create_load_balancer()
        neutronclient.Client.delete_member(u'member5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()


class PoolUpdateHealthMonitorsTest(HeatTestCase):

    def setUp(self):
        super(PoolUpdateHealthMonitorsTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_pool')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_pool')
        self.m.StubOutWithMock(neutronclient.Client, 'show_pool')
        self.m.StubOutWithMock(neutronclient.Client, 'update_pool')
        self.m.StubOutWithMock(neutronclient.Client,
                               'associate_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client,
                               'disassociate_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'create_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'show_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'update_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'create_vip')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_vip')
        self.m.StubOutWithMock(neutronclient.Client, 'show_vip')
        self.stub_keystoneclient()

    def _create_pool_with_health_monitors(self):
        neutronclient.Client.create_health_monitor({
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}
        ).AndReturn({'health_monitor': {'id': '5555'}})

        neutronclient.Client.create_health_monitor({
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}
        ).AndReturn({'health_monitor': {'id': '6666'}})
        neutronclient.Client.create_pool({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName('test_stack', 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        ).AndReturn({'pool': {'id': '5678'}})
        neutronclient.Client.associate_health_monitor(
            '5678', {'health_monitor': {'id': '5555'}}).InAnyOrder()
        neutronclient.Client.associate_health_monitor(
            '5678', {'health_monitor': {'id': '6666'}}).InAnyOrder()
        neutronclient.Client.create_vip({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}
        ).AndReturn({'vip': {'id': 'xyz'}})
        neutronclient.Client.show_pool('5678').AndReturn(
            {'pool': {'status': 'ACTIVE'}})
        neutronclient.Client.show_vip('xyz').AndReturn(
            {'vip': {'status': 'ACTIVE'}})

    def test_update_pool_with_references_to_health_monitors(self):
        self._create_pool_with_health_monitors()

        neutronclient.Client.disassociate_health_monitor(
            '5678', mox.IsA(unicode))

        self.m.ReplayAll()
        snippet = template_format.parse(pool_with_health_monitors_template)
        self.stack = utils.parse_stack(snippet)
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        snippet['Resources']['pool']['Properties']['monitors'] = [
            {u'Ref': u'monitor1'}]
        updated_stack = utils.parse_stack(snippet)
        self.stack.update(updated_stack)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_pool_with_empty_list_of_health_monitors(self):
        self._create_pool_with_health_monitors()

        neutronclient.Client.disassociate_health_monitor(
            '5678', '5555').InAnyOrder()
        neutronclient.Client.disassociate_health_monitor(
            '5678', '6666').InAnyOrder()

        self.m.ReplayAll()
        snippet = template_format.parse(pool_with_health_monitors_template)
        self.stack = utils.parse_stack(snippet)
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        snippet['Resources']['pool']['Properties']['monitors'] = []
        updated_stack = utils.parse_stack(snippet)
        self.stack.update(updated_stack)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_pool_without_health_monitors(self):
        self._create_pool_with_health_monitors()

        neutronclient.Client.disassociate_health_monitor(
            '5678', '5555').InAnyOrder()
        neutronclient.Client.disassociate_health_monitor(
            '5678', '6666').InAnyOrder()

        self.m.ReplayAll()
        snippet = template_format.parse(pool_with_health_monitors_template)
        self.stack = utils.parse_stack(snippet)
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        snippet['Resources']['pool']['Properties'].pop('monitors')
        updated_stack = utils.parse_stack(snippet)
        self.stack.update(updated_stack)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()
