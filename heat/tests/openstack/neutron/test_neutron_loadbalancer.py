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

import mock
from neutronclient.common import exceptions
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient
from oslo_config import cfg
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine.resources.openstack.neutron import loadbalancer
from heat.engine import scheduler
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


health_monitor_template = '''
heat_template_version: 2015-04-30
description: Template to test load balancer resources
resources:
  monitor:
    type: OS::Neutron::HealthMonitor
    properties:
      type: HTTP
      delay: 3
      max_retries: 5
      timeout: 10
'''

pool_template_with_vip_subnet = '''
heat_template_version: 2015-04-30
description: Template to test load balancer resources
resources:
  pool:
    type: OS::Neutron::Pool
    properties:
      protocol: HTTP
      subnet: sub123
      lb_method: ROUND_ROBIN
      vip:
        protocol_port: 80
        subnet: sub9999
'''

pool_template_with_provider = '''
heat_template_version: 2015-04-30
description: Template to test load balancer resources
resources:
  pool:
    type: OS::Neutron::Pool
    properties:
      protocol: HTTP
      subnet: sub123
      lb_method: ROUND_ROBIN
      provider: test_prov
      vip:
        protocol_port: 80

'''

pool_template = '''
heat_template_version: 2015-04-30
description: Template to test load balancer resources
resources:
  pool:
    type: OS::Neutron::Pool
    properties:
      protocol: HTTP
      subnet: sub123
      lb_method: ROUND_ROBIN
      vip:
        protocol_port: 80

'''

pool_template_deprecated = pool_template.replace('subnet', 'subnet_id')

member_template = '''
heat_template_version: 2015-04-30
description: Template to test load balancer member
resources:
  member:
    type: OS::Neutron::PoolMember
    properties:
      protocol_port: 8080
      pool_id: pool123
      address: 1.2.3.4
'''

lb_template = '''
heat_template_version: 2015-04-30
description: Template to test load balancer resources
resources:
  lb:
    type: OS::Neutron::LoadBalancer
    properties:
      protocol_port: 8080
      pool_id: pool123
      members: [1234]
'''


pool_with_session_persistence_template = '''
heat_template_version: 2015-04-30
description: Template to test load balancer resources
resources:
  pool:
    type: OS::Neutron::Pool
    properties:
      protocol: HTTP
      subnet: sub123
      lb_method: ROUND_ROBIN
      vip:
        protocol_port: 80
        session_persistence:
          type: APP_COOKIE
          cookie_name: cookie
'''


pool_with_health_monitors_template = '''
heat_template_version: 2015-04-30
description: Template to test load balancer resources
resources:
  monitor1:
    type: OS::Neutron::HealthMonitor
    properties:
      type: HTTP
      delay: 3
      max_retries: 5
      timeout: 10

  monitor2:
    type: OS::Neutron::HealthMonitor
    properties:
      type: HTTP
      delay: 3
      max_retries: 5
      timeout: 10

  pool:
    type: OS::Neutron::Pool
    properties:
      protocol: HTTP
      subnet_id: sub123
      lb_method: ROUND_ROBIN
      vip:
        protocol_port: 80
      monitors:
        - {get_resource: monitor1}
        - {get_resource: monitor2}
'''


class HealthMonitorTest(common.HeatTestCase):

    def setUp(self):
        super(HealthMonitorTest, self).setUp()
        mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=mockclient)
        self.mock_create = mockclient.create_health_monitor
        self.mock_delete = mockclient.delete_health_monitor
        self.mock_show = mockclient.show_health_monitor
        self.mock_update = mockclient.update_health_monitor
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.create_snippet = {
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}

    def create_health_monitor(self):
        self.mock_create.return_value = {'health_monitor': {'id': '5678'}}
        snippet = template_format.parse(health_monitor_template)
        self.stack = utils.parse_stack(snippet)
        self.tmpl = snippet
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return loadbalancer.HealthMonitor(
            'monitor', resource_defns['monitor'], self.stack)

    def test_create(self):
        rsrc = self.create_health_monitor()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.mock_create.assert_called_once_with(self.create_snippet)

    def test_create_failed(self):
        self.mock_create.side_effect = exceptions.NeutronClientException()
        snippet = template_format.parse(health_monitor_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.HealthMonitor(
            'monitor', resource_defns['monitor'], self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.monitor: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.mock_create.assert_called_once_with(self.create_snippet)

    def test_delete(self):
        self.mock_delete.return_value = None
        self.mock_show.side_effect = exceptions.NeutronClientException(
            status_code=404)
        rsrc = self.create_health_monitor()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mock_create.assert_called_once_with(self.create_snippet)
        self.mock_delete.assert_called_once_with('5678')

    def test_delete_already_gone(self):
        self.mock_delete.side_effect = exceptions.NeutronClientException(
            status_code=404)
        rsrc = self.create_health_monitor()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mock_create.assert_called_once_with(self.create_snippet)
        self.mock_delete.assert_called_once_with('5678')

    def test_delete_failed(self):
        self.mock_delete.side_effect = exceptions.NeutronClientException(
            status_code=400)
        rsrc = self.create_health_monitor()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.monitor: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.mock_create.assert_called_once_with(self.create_snippet)
        self.mock_delete.assert_called_once_with('5678')

    def test_attribute(self):
        rsrc = self.create_health_monitor()
        self.mock_show.return_value = {
            'health_monitor': {'admin_state_up': True, 'delay': 3}}
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual(3, rsrc.FnGetAtt('delay'))
        self.mock_create.assert_called_once_with(self.create_snippet)
        self.mock_show.assert_called_with('5678')

    def test_attribute_failed(self):
        rsrc = self.create_health_monitor()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'subnet_id')
        self.assertEqual(
            'The Referenced Attribute (monitor subnet_id) is incorrect.',
            six.text_type(error))
        self.mock_create.assert_called_once_with(self.create_snippet)

    def test_update(self):
        rsrc = self.create_health_monitor()
        scheduler.TaskRunner(rsrc.create)()
        props = self.tmpl['resources']['monitor']['properties'].copy()
        props['delay'] = 10
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.mock_create.assert_called_once_with(self.create_snippet)
        self.mock_update.assert_called_once_with(
            '5678', {'health_monitor': {'delay': 10}})


class PoolTest(common.HeatTestCase):

    def setUp(self):
        super(PoolTest, self).setUp()
        mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=mockclient)
        self.mock_create = mockclient.create_pool
        self.mock_delete = mockclient.delete_pool
        self.mock_show = mockclient.show_pool
        self.mock_update = mockclient.update_pool
        self.mock_associate = mockclient.associate_health_monitor
        self.mock_disassociate = mockclient.disassociate_health_monitor
        self.mock_create_vip = mockclient.create_vip
        self.mock_delete_vip = mockclient.delete_vip
        self.mock_show_vip = mockclient.show_vip

        def finder(client, resource_type, name, cmd_resource):
            return name

        self.mock_finder = self.patchobject(
            neutronV20, 'find_resourceid_by_name_or_id',
            side_effect=finder)
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_pool(self, resolve_neutron=True, with_vip_subnet=False):
        if resolve_neutron:
            if with_vip_subnet:
                snippet = template_format.parse(pool_template_with_vip_subnet)
            else:
                snippet = template_format.parse(pool_template)
        else:
            snippet = template_format.parse(pool_template_deprecated)
        self.stack = utils.parse_stack(snippet)
        self.tmpl = snippet
        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_show.return_value = {'pool': {'status': 'ACTIVE'}}
        self.mock_show_vip.return_value = {'vip': {'status': 'ACTIVE'}}
        self.pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        self.vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}

        if with_vip_subnet:
            self.stub_SubnetConstraint_validate()
            self.vip_create_snippet['vip']['subnet_id'] = 'sub9999'
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return loadbalancer.Pool(
            'pool', resource_defns['pool'], self.stack)

    def _test_create(self, resolve_neutron=True,
                     with_vip_subnet=False):
        rsrc = self.create_pool(resolve_neutron,
                                with_vip_subnet)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.mock_create.assert_called_once_with(self.pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(self.vip_create_snippet)

    def test_create(self):
        self._test_create()

    def test_create_deprecated(self):
        self._test_create(resolve_neutron=False,
                          with_vip_subnet=False)

    def test_create_with_vip_subnet(self):
        self._test_create(resolve_neutron=True,
                          with_vip_subnet=True)

    def test_create_pending(self):
        snippet = template_format.parse(pool_template)
        self.stack = utils.parse_stack(snippet)
        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        self.mock_show.side_effect = [
            {'pool': {'status': 'PENDING_CREATE'}},
            {'pool': {'status': 'ACTIVE'}},
            {'pool': {'status': 'ACTIVE'}}]
        self.mock_show_vip.side_effect = [
            {'vip': {'status': 'PENDING_CREATE'}},
            {'vip': {'status': 'ACTIVE'}}]
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}

        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], self.stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mock_create.assert_called_once_with(pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(vip_create_snippet)
        self.mock_show.assert_called_with('5678')
        self.mock_show_vip.assert_called_with('xyz')

    def test_create_failed_error_status(self):
        cfg.CONF.set_override('action_retry_limit', 0)

        snippet = template_format.parse(pool_template)
        self.stack = utils.parse_stack(snippet)
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}

        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        self.mock_show.return_value = {
            'pool': {'status': 'ERROR', 'name': '5678'}}
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'ResourceInError: resources.pool: '
            'Went to status ERROR due to "error in pool"',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.mock_create.assert_called_once_with(pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(vip_create_snippet)
        self.mock_show.assert_called_once_with('5678')

    def test_create_failed_unexpected_vip_status(self):
        snippet = template_format.parse(pool_template)
        self.stack = utils.parse_stack(snippet)
        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        self.mock_show.return_value = {
            'pool': {'status': 'ACTIVE', 'name': '5678'}}
        self.mock_show_vip.return_value = {
            'vip': {'status': 'SOMETHING', 'name': 'xyz'}}
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}

        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual('ResourceUnknownStatus: resources.pool: '
                         'Pool creation failed due to '
                         'vip - Unknown status SOMETHING due to "Unknown"',
                         six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.mock_create.assert_called_once_with(pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(vip_create_snippet)
        self.mock_show.assert_called_once_with('5678')
        self.mock_show_vip.assert_called_once_with('xyz')

    def test_create_failed(self):
        snippet = template_format.parse(pool_template)
        self.stack = utils.parse_stack(snippet)
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}

        self.mock_create.side_effect = exceptions.NeutronClientException()
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.pool: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.mock_create.assert_called_once_with(pool_create_snippet)

    def test_create_with_session_persistence(self):
        snippet = template_format.parse(pool_with_session_persistence_template)
        self.stack = utils.parse_stack(snippet)
        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        self.mock_show.return_value = {
            'pool': {'status': 'ACTIVE', 'name': '5678'}}
        self.mock_show_vip.return_value = {
            'vip': {'status': 'ACTIVE', 'name': 'xyz'}}
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80,
                'session_persistence': {
                    'type': 'APP_COOKIE',
                    'cookie_name': 'cookie'}}}

        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], self.stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.mock_create.assert_called_once_with(pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(vip_create_snippet)
        self.mock_show.assert_called_once_with('5678')
        self.mock_show_vip.assert_called_once_with('xyz')

    def test_create_pool_with_provider(self):
        snippet = template_format.parse(pool_template_with_provider)
        self.stub_ProviderConstraint_validate()
        self.stack = utils.parse_stack(snippet)
        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        self.mock_show.return_value = {
            'pool': {'status': 'ACTIVE', 'provider': 'test_prov'}}
        self.mock_show_vip.return_value = {
            'vip': {'status': 'ACTIVE', 'name': 'xyz'}}
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True,
                'provider': 'test_prov'}}
        vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}

        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.Pool(
            'pool', resource_defns['pool'], self.stack)

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual("test_prov", rsrc.FnGetAtt("provider"))
        self.mock_create.assert_called_once_with(pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(vip_create_snippet)
        self.mock_show_vip.assert_called_once_with('xyz')
        self.mock_show.assert_called_with('5678')

    def test_failing_validation_with_session_persistence(self):
        msg = _('Property cookie_name is required, when '
                'session_persistence type is set to APP_COOKIE.')
        snippet = template_format.parse(pool_with_session_persistence_template)
        pool = snippet['resources']['pool']
        persistence = pool['properties']['vip']['session_persistence']

        # When persistence type is set to APP_COOKIE, cookie_name is required
        persistence['type'] = 'APP_COOKIE'
        persistence['cookie_name'] = None

        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        resource = loadbalancer.Pool('pool', resource_defns['pool'],
                                     self.stack)

        error = self.assertRaises(exception.StackValidationFailed,
                                  resource.validate)
        self.assertEqual(msg, six.text_type(error))

    def test_validation_not_failing_without_session_persistence(self):
        snippet = template_format.parse(pool_template)

        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        resource = loadbalancer.Pool('pool', resource_defns['pool'],
                                     self.stack)
        self.stub_SubnetConstraint_validate()
        self.assertIsNone(resource.validate())

    def test_properties_are_prepared_for_session_persistence(self):
        snippet = template_format.parse(pool_with_session_persistence_template)
        pool = snippet['resources']['pool']
        persistence = pool['properties']['vip']['session_persistence']

        # change persistence type to HTTP_COOKIE that not require cookie_name
        persistence['type'] = 'HTTP_COOKIE'
        del persistence['cookie_name']

        self.stack = utils.parse_stack(snippet)

        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        self.mock_show.return_value = {
            'pool': {'status': 'ACTIVE', 'name': '5678'}}
        self.mock_show_vip.return_value = {
            'vip': {'status': 'ACTIVE', 'name': 'xyz'}}
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80,
                'session_persistence': {'type': 'HTTP_COOKIE'}}}

        resource_defns = self.stack.t.resource_definitions(self.stack)
        resource = loadbalancer.Pool('pool', resource_defns['pool'],
                                     self.stack)

        # assert that properties contain cookie_name property with None value
        persistence = resource.properties['vip']['session_persistence']
        self.assertIn('cookie_name', persistence)
        self.assertIsNone(persistence['cookie_name'])

        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE), resource.state)
        self.mock_create.assert_called_once_with(pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(vip_create_snippet)
        self.mock_show.assert_called_once_with('5678')
        self.mock_show_vip.assert_called_once_with('xyz')

    def test_delete(self):
        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        self.mock_delete.return_value = None
        self.mock_delete_vip.return_value = None
        self.mock_show_vip.side_effect = exceptions.NeutronClientException(
            status_code=404)
        self.mock_show.side_effect = exceptions.NeutronClientException(
            status_code=404)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mock_delete.assert_called_once_with('5678')
        self.mock_delete_vip.assert_called_once_with('xyz')
        self.mock_show.assert_called_with('5678')
        self.assertEqual(2, self.mock_show.call_count)
        self.mock_show_vip.assert_called_with('xyz')
        self.assertEqual(2, self.mock_show_vip.call_count)

    def test_delete_already_gone(self):
        self.mock_delete_vip.side_effect = exceptions.NeutronClientException(
            status_code=404)
        self.mock_delete.side_effect = exceptions.NeutronClientException(
            status_code=404)

        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mock_delete.assert_called_once_with('5678')
        self.mock_delete_vip.assert_called_once_with('xyz')

    def test_delete_vip_failed(self):
        self.mock_delete_vip.side_effect = exceptions.NeutronClientException(
            status_code=400)

        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.pool: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.mock_delete_vip.assert_called_once_with('xyz')
        self.mock_delete.assert_not_called()

    def test_delete_failed(self):
        self.mock_delete_vip.side_effect = exceptions.NeutronClientException(
            status_code=404)
        self.mock_delete.side_effect = exceptions.NeutronClientException(
            status_code=400)

        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.pool: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.mock_delete.assert_called_once_with('5678')
        self.mock_delete_vip.assert_called_once_with('xyz')

    def test_attribute(self):
        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        self.mock_show.return_value = {
            'pool': {'admin_state_up': True, 'lb_method': 'ROUND_ROBIN'}}
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual('ROUND_ROBIN', rsrc.FnGetAtt('lb_method'))

    def test_vip_attribute(self):
        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        self.mock_show_vip.return_value = {
            'vip': {'address': '10.0.0.3', 'name': 'xyz'}}
        self.assertEqual({'address': '10.0.0.3', 'name': 'xyz'},
                         rsrc.FnGetAtt('vip'))

    def test_attribute_failed(self):
        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'net_id')
        self.assertEqual(
            'The Referenced Attribute (pool net_id) is incorrect.',
            six.text_type(error))

    def test_update(self):
        rsrc = self.create_pool()
        scheduler.TaskRunner(rsrc.create)()
        props = self.tmpl['resources']['pool']['properties'].copy()
        props['admin_state_up'] = False
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.mock_update.assert_called_once_with(
            '5678', {'pool': {'admin_state_up': False}})

    def test_update_monitors(self):
        snippet = template_format.parse(pool_template)
        self.stack = utils.parse_stack(snippet)
        self.mock_create.return_value = {'pool': {'id': '5678'}}
        self.mock_create_vip.return_value = {'vip': {'id': 'xyz'}}
        pool_create_snippet = {
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack.name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        vip_create_snippet = {
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}

        self.mock_show.return_value = {
            'pool': {'status': 'ACTIVE', 'name': '5678'}}
        self.mock_show_vip.return_value = {
            'vip': {'status': 'ACTIVE', 'name': 'xyz'}}

        snippet['resources']['pool']['properties']['monitors'] = [
            'mon123', 'mon456']
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.Pool('pool', resource_defns['pool'], self.stack)
        scheduler.TaskRunner(rsrc.create)()

        props = snippet['resources']['pool']['properties'].copy()
        props['monitors'] = ['mon123', 'mon789']
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()
        associate_calls = [mock.call('5678',
                                     {'health_monitor': {'id': 'mon123'}}),
                           mock.call('5678',
                                     {'health_monitor': {'id': 'mon456'}}),
                           mock.call('5678',
                                     {'health_monitor': {'id': 'mon789'}})]
        self.mock_associate.assert_has_calls(associate_calls)
        self.assertEqual(3, self.mock_associate.call_count)
        self.mock_disassociate.assert_called_once_with('5678', 'mon456')
        self.mock_create.assert_called_once_with(pool_create_snippet)
        self.mock_create_vip.assert_called_once_with(vip_create_snippet)
        self.mock_show.assert_called_once_with('5678')
        self.mock_show_vip.assert_called_once_with('xyz')


class PoolMemberTest(common.HeatTestCase):

    def setUp(self):
        super(PoolMemberTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.mc = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mc)
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_member(self):
        self.mc.create_member.return_value = {'member': {'id': 'member5678'}}
        snippet = template_format.parse(member_template)
        self.stack = utils.parse_stack(snippet)
        self.tmpl = snippet
        resource_defns = self.stack.t.resource_definitions(self.stack)
        result = loadbalancer.PoolMember(
            'member', resource_defns['member'], self.stack)
        return result

    def validate_create_member(self):
        self.mc.create_member.assert_called_once_with({
            'member': {
                'pool_id': 'pool123', 'protocol_port': 8080,
                'address': '1.2.3.4', 'admin_state_up': True}}
        )

    def test_create(self):
        rsrc = self.create_member()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('member5678', rsrc.resource_id)
        self.validate_create_member()

    def test_create_optional_parameters(self):
        self.mc.create_member.return_value = {'member': {'id': 'member5678'}}
        snippet = template_format.parse(member_template)
        snippet['resources']['member']['properties']['admin_state_up'] = False
        snippet['resources']['member']['properties']['weight'] = 100
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = loadbalancer.PoolMember(
            'member', resource_defns['member'], self.stack)

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('member5678', rsrc.resource_id)
        self.mc.create_member.assert_called_once_with({
            'member': {
                'pool_id': 'pool123', 'protocol_port': 8080,
                'weight': 100, 'admin_state_up': False,
                'address': '1.2.3.4'}}
        )

    def test_attribute(self):
        rsrc = self.create_member()
        self.mc.show_member.return_value = {
            'member': {'admin_state_up': True, 'weight': 5}}
        scheduler.TaskRunner(rsrc.create)()
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual(5, rsrc.FnGetAtt('weight'))
        self.mc.show_member.assert_called_with('member5678')
        self.validate_create_member()

    def test_update(self):
        rsrc = self.create_member()
        scheduler.TaskRunner(rsrc.create)()

        props = self.tmpl['resources']['member']['properties'].copy()
        props['pool_id'] = 'pool456'
        update_template = rsrc.t.freeze(properties=props)

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.mc.update_member.assert_called_once_with(
            'member5678', {'member': {'pool_id': 'pool456'}})
        self.validate_create_member()

    def test_delete(self):
        rsrc = self.create_member()
        self.mc.show_member.side_effect = [exceptions.NeutronClientException(
            status_code=404)]

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mc.delete_member.assert_called_once_with(u'member5678')
        self.mc.show_member.assert_called_once_with(u'member5678')
        self.validate_create_member()

    def test_delete_missing_member(self):
        rsrc = self.create_member()
        self.mc.delete_member.side_effect = [exceptions.NeutronClientException(
            status_code=404)]

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.validate_create_member()
        self.mc.delete_member.assert_called_once_with(u'member5678')


class LoadBalancerTest(common.HeatTestCase):

    def setUp(self):
        super(LoadBalancerTest, self).setUp()
        self.fc = fakes_nova.FakeClient()

        self.mc = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mc)
        self.patchobject(nova.NovaClientPlugin, 'client')
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_load_balancer(self, extra_create_mocks=[]):
        nova.NovaClientPlugin.client.return_value = self.fc
        results = [{'member': {'id': 'member5678'}}]
        for m in extra_create_mocks:
            results.append(m)
        self.mc.create_member.side_effect = results
        snippet = template_format.parse(lb_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return loadbalancer.LoadBalancer(
            'lb', resource_defns['lb'], self.stack)

    def validate_create_load_balancer(self, create_count=1):
        if create_count > 1:
            self.assertEqual(create_count, self.mc.create_member.call_count)
            self.mc.create_member.assert_called_with({
                'member': {
                    'pool_id': 'pool123', 'protocol_port': 8080,
                    'address': '4.5.6.7'}}
            )
            nova.NovaClientPlugin.client.assert_called_with()
            self.assertEqual(create_count,
                             nova.NovaClientPlugin.client.call_count)
        else:
            self.mc.create_member.assert_called_once_with({
                'member': {
                    'pool_id': 'pool123', 'protocol_port': 8080,
                    'address': '1.2.3.4'}}
            )
            nova.NovaClientPlugin.client.assert_called_once_with()

    def test_create(self):
        rsrc = self.create_load_balancer()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.validate_create_load_balancer()

    def test_update(self):
        rsrc = self.create_load_balancer(
            extra_create_mocks=[{'member': {'id': 'memberxyz'}}])

        scheduler.TaskRunner(rsrc.create)()

        props = dict(rsrc.properties)
        props['members'] = ['5678']
        update_template = rsrc.t.freeze(properties=props)

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.validate_create_load_balancer(create_count=2)
        self.mc.delete_member.assert_called_once_with(u'member5678')

    def test_update_missing_member(self):
        rsrc = self.create_load_balancer()
        self.mc.delete_member.side_effect = [
            exceptions.NeutronClientException(status_code=404)]

        scheduler.TaskRunner(rsrc.create)()

        props = dict(rsrc.properties)
        props['members'] = []
        update_template = rsrc.t.freeze(properties=props)

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.mc.delete_member.assert_called_once_with(u'member5678')
        self.validate_create_load_balancer()

    def test_delete(self):
        rsrc = self.create_load_balancer()

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mc.delete_member.assert_called_once_with(u'member5678')
        self.validate_create_load_balancer()

    def test_delete_missing_member(self):
        rsrc = self.create_load_balancer()
        self.mc.delete_member.side_effect = [
            exceptions.NeutronClientException(status_code=404)]

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.mc.delete_member.assert_called_once_with(u'member5678')
        self.validate_create_load_balancer()


class PoolUpdateHealthMonitorsTest(common.HeatTestCase):

    def setUp(self):
        super(PoolUpdateHealthMonitorsTest, self).setUp()
        self.mc = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mc)
        self.patchobject(neutronV20, 'find_resourceid_by_name_or_id')
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def validate_create_pool_with_health_monitors(self):
        self.mc.create_health_monitor.assert_called_with({
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}
        )
        self.assertEqual(2, self.mc.create_health_monitor.call_count)
        neutronV20.find_resourceid_by_name_or_id.assert_called_with(
            mock.ANY,
            'subnet',
            'sub123',
            cmd_resource=None,
        )
        self.mc.create_pool.assert_called_once_with({
            'pool': {
                'subnet_id': 'sub123', 'protocol': u'HTTP',
                'name': utils.PhysName(self.stack_name, 'pool'),
                'lb_method': 'ROUND_ROBIN', 'admin_state_up': True}}
        )
        self.mc.associate_health_monitor.assert_has_calls([mock.call(
            '5678', {'health_monitor': {'id': '5555'}}), mock.call(
            '5678', {'health_monitor': {'id': '6666'}})],
            any_order=True)
        self.assertEqual(2, self.mc.associate_health_monitor.call_count)
        self.mc.create_vip.assert_called_once_with({
            'vip': {
                'protocol': u'HTTP', 'name': 'pool.vip',
                'admin_state_up': True, 'subnet_id': u'sub123',
                'pool_id': '5678', 'protocol_port': 80}}
        )
        self.mc.show_pool.assert_called_once_with('5678')
        self.mc.show_vip.assert_called_once_with('xyz')

    def _create_pool_with_health_monitors(self, stack_name):
        self.stack_name = stack_name
        self.mc.create_health_monitor.side_effect = [
            {'health_monitor': {'id': '5555'}},
            {'health_monitor': {'id': '6666'}}]

        self.stub_SubnetConstraint_validate()
        neutronV20.find_resourceid_by_name_or_id.return_value = 'sub123'
        self.mc.create_pool.return_value = {'pool': {'id': '5678'}}
        self.mc.create_vip.return_value = {'vip': {'id': 'xyz'}}
        self.mc.show_pool.return_value = {'pool': {'status': 'ACTIVE'}}
        self.mc.show_vip.return_value = {'vip': {'status': 'ACTIVE'}}

    def test_update_pool_with_references_to_health_monitors(self):
        snippet = template_format.parse(pool_with_health_monitors_template)
        self.stack = utils.parse_stack(snippet)
        self._create_pool_with_health_monitors(self.stack.name)
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        snippet['resources']['pool']['properties']['monitors'] = [
            {u'get_resource': u'monitor1'}]
        updated_stack = utils.parse_stack(snippet)
        self.stack.update(updated_stack)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.validate_create_pool_with_health_monitors()
        self.mc.disassociate_health_monitor.assert_called_once_with(
            '5678', mock.ANY)

    def test_update_pool_with_empty_list_of_health_monitors(self):
        snippet = template_format.parse(pool_with_health_monitors_template)
        self.stack = utils.parse_stack(snippet)
        self._create_pool_with_health_monitors(self.stack.name)

        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        snippet['resources']['pool']['properties']['monitors'] = []
        updated_stack = utils.parse_stack(snippet)
        self.stack.update(updated_stack)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.mc.disassociate_health_monitor.assert_has_calls(
            [mock.call('5678', '5555'), mock.call('5678', '6666')],
            any_order=True)
        self.assertEqual(2, self.mc.disassociate_health_monitor.call_count)

        self.validate_create_pool_with_health_monitors()

    def test_update_pool_without_health_monitors(self):
        snippet = template_format.parse(pool_with_health_monitors_template)
        self.stack = utils.parse_stack(snippet)
        self._create_pool_with_health_monitors(self.stack.name)

        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        snippet['resources']['pool']['properties'].pop('monitors')
        updated_stack = utils.parse_stack(snippet)
        self.stack.update(updated_stack)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.mc.disassociate_health_monitor.assert_has_calls(
            [mock.call('5678', '5555'), mock.call('5678', '6666')],
            any_order=True)
        self.assertEqual(2, self.mc.disassociate_health_monitor.call_count)
        self.validate_create_pool_with_health_monitors()
