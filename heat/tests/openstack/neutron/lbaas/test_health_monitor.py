#
#    Copyright 2015 IBM Corp.
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

from heat.common import template_format
from heat.engine.resources.openstack.neutron.lbaas import health_monitor
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class HealthMonitorTest(common.HeatTestCase):

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func, tmpl=inline_templates.MONITOR_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.healthmonitor = self.stack['monitor']

        self.neutron_client = mock.MagicMock()
        self.healthmonitor.client = mock.MagicMock(
            return_value=self.neutron_client)

        self.healthmonitor.client_plugin().find_resourceid_by_name_or_id = (
            mock.MagicMock(return_value='123'))
        self.healthmonitor.client_plugin().client = mock.MagicMock(
            return_value=self.neutron_client)

    def test_resource_mapping(self):
        mapping = health_monitor.resource_mapping()
        self.assertEqual(health_monitor.HealthMonitor,
                         mapping['OS::Neutron::LBaaS::HealthMonitor'])

    def test_create(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.create_lbaas_healthmonitor.side_effect = [
            exceptions.StateInvalidClient,
            {'healthmonitor': {'id': '1234'}}
        ]
        expected = {
            'healthmonitor': {
                'admin_state_up': True,
                'delay': 3,
                'expected_codes': '200-202',
                'http_method': 'HEAD',
                'max_retries': 5,
                'pool_id': '123',
                'timeout': 10,
                'type': 'HTTP',
                'url_path': '/health'
            }
        }

        props = self.healthmonitor.handle_create()

        self.assertFalse(self.healthmonitor.check_create_complete(props))
        self.neutron_client.create_lbaas_healthmonitor.assert_called_with(
            expected)
        self.assertFalse(self.healthmonitor.check_create_complete(props))
        self.neutron_client.create_lbaas_healthmonitor.assert_called_with(
            expected)
        self.assertFalse(self.healthmonitor.check_create_complete(props))
        self.assertTrue(self.healthmonitor.check_create_complete(props))

    def test_show_resource(self):
        self._create_stack()
        self.healthmonitor.resource_id_set('1234')

        self.assertTrue(self.healthmonitor._show_resource())

        self.neutron_client.show_lbaas_healthmonitor.assert_called_with(
            '1234')

    def test_update(self):
        self._create_stack()
        self.healthmonitor.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.update_lbaas_healthmonitor.side_effect = [
            exceptions.StateInvalidClient, None]
        prop_diff = {
            'admin_state_up': False,
        }

        prop_diff = self.healthmonitor.handle_update(None, None, prop_diff)

        self.assertFalse(self.healthmonitor.check_update_complete(prop_diff))
        self.assertFalse(self.healthmonitor._update_called)
        self.neutron_client.update_lbaas_healthmonitor.assert_called_with(
            '1234', {'healthmonitor': prop_diff})
        self.assertFalse(self.healthmonitor.check_update_complete(prop_diff))
        self.assertTrue(self.healthmonitor._update_called)
        self.neutron_client.update_lbaas_healthmonitor.assert_called_with(
            '1234', {'healthmonitor': prop_diff})
        self.assertFalse(self.healthmonitor.check_update_complete(prop_diff))
        self.assertTrue(self.healthmonitor.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.healthmonitor.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.delete_lbaas_healthmonitor.side_effect = [
            exceptions.StateInvalidClient, None]

        self.healthmonitor.handle_delete()

        self.assertFalse(self.healthmonitor.check_delete_complete(None))
        self.assertFalse(self.healthmonitor._delete_called)
        self.neutron_client.delete_lbaas_healthmonitor.assert_called_with(
            '1234')
        self.assertFalse(self.healthmonitor.check_delete_complete(None))
        self.assertTrue(self.healthmonitor._delete_called)
        self.neutron_client.delete_lbaas_healthmonitor.assert_called_with(
            '1234')
        self.assertFalse(self.healthmonitor.check_delete_complete(None))
        self.assertTrue(self.healthmonitor.check_delete_complete(None))

    def test_delete_already_gone(self):
        self._create_stack()
        self.healthmonitor.resource_id_set('1234')
        self.neutron_client.delete_lbaas_healthmonitor.side_effect = (
            exceptions.NotFound)

        self.healthmonitor.handle_delete()

        self.assertTrue(self.healthmonitor.check_delete_complete(None))
        self.neutron_client.delete_lbaas_healthmonitor.assert_called_with(
            '1234')

    def test_delete_failed(self):
        self._create_stack()
        self.healthmonitor.resource_id_set('1234')
        self.neutron_client.delete_lbaas_healthmonitor.side_effect = (
            exceptions.Unauthorized)

        self.healthmonitor.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.healthmonitor.check_delete_complete, None)

        self.neutron_client.delete_lbaas_healthmonitor.assert_called_with(
            '1234')
