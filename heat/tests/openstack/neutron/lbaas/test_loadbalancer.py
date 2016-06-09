#
#    Copyright 2015 IBM Corp.
#
#    All Rights Reserved.
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

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.neutron.lbaas import loadbalancer
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class LoadBalancerTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = loadbalancer.resource_mapping()
        self.assertEqual(loadbalancer.LoadBalancer,
                         mapping['OS::Neutron::LBaaS::LoadBalancer'])

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func, tmpl=inline_templates.LB_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.lb = self.stack['lb']
        self.neutron_client = mock.MagicMock()
        self.lb.client = mock.MagicMock()
        self.lb.client.return_value = self.neutron_client

        self.lb.client_plugin().find_resourceid_by_name_or_id = mock.MagicMock(
            return_value='123')
        self.lb.client_plugin().client = mock.MagicMock(
            return_value=self.neutron_client)
        self.lb.translate_properties(self.lb.properties)
        self.lb.resource_id_set('1234')

    def test_create(self):
        self._create_stack()
        expected = {
            'loadbalancer': {
                'name': 'my_lb',
                'description': 'my loadbalancer',
                'vip_address': '10.0.0.4',
                'vip_subnet_id': '123',
                'provider': 'octavia',
                'tenant_id': '1234',
                'admin_state_up': True,
            }
        }

        self.lb.handle_create()

        self.neutron_client.create_loadbalancer.assert_called_with(expected)

    def test_check_create_complete(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_CREATE'}},
            {'loadbalancer': {'provisioning_status': 'ERROR'}},
        ]

        self.assertTrue(self.lb.check_create_complete(None))
        self.assertFalse(self.lb.check_create_complete(None))
        self.assertRaises(exception.ResourceInError,
                          self.lb.check_create_complete, None)

    def test_show_resource(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.return_value = {
            'loadbalancer': {'id': '1234'}
        }

        self.assertEqual({'id': '1234'}, self.lb._show_resource())

        self.neutron_client.show_loadbalancer.assert_called_with('1234')

    def test_update(self):
        self._create_stack()
        prop_diff = {
            'name': 'lb',
            'description': 'a loadbalancer',
            'admin_state_up': False,
        }

        prop_diff = self.lb.handle_update(None, None, prop_diff)

        self.neutron_client.update_loadbalancer.assert_called_once_with(
            '1234', {'loadbalancer': prop_diff})

    def test_update_complete(self):
        self._create_stack()
        prop_diff = {
            'name': 'lb',
            'description': 'a loadbalancer',
            'admin_state_up': False,
        }
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
        ]

        self.lb.handle_update(None, None, prop_diff)

        self.assertTrue(self.lb.check_update_complete(prop_diff))
        self.assertFalse(self.lb.check_update_complete(prop_diff))
        self.assertTrue(self.lb.check_update_complete({}))

    def test_delete_active(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
            exceptions.NotFound
        ]

        self.lb.handle_delete()

        self.assertFalse(self.lb.check_delete_complete(None))
        self.assertTrue(self.lb.check_delete_complete(None))
        self.neutron_client.delete_loadbalancer.assert_called_with('1234')
        self.assertEqual(2, self.neutron_client.show_loadbalancer.call_count)

    def test_delete_pending(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
            exceptions.NotFound
        ]

        self.lb.handle_delete()

        self.assertFalse(self.lb.check_delete_complete(None))
        self.assertFalse(self.lb.check_delete_complete(None))
        self.assertTrue(self.lb.check_delete_complete(None))
        self.neutron_client.delete_loadbalancer.assert_called_with('1234')
        self.assertEqual(3, self.neutron_client.show_loadbalancer.call_count)

    def test_delete_error(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'ERROR'}},
            exceptions.NotFound
        ]

        self.lb.handle_delete()

        self.assertFalse(self.lb.check_delete_complete(None))
        self.assertTrue(self.lb.check_delete_complete(None))
        self.neutron_client.delete_loadbalancer.assert_called_with('1234')
        self.assertEqual(2, self.neutron_client.show_loadbalancer.call_count)

    def test_delete_already_gone(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = (
            exceptions.NotFound)

        self.lb.handle_delete()
        self.assertTrue(self.lb.check_delete_complete(None))
        self.assertEqual(1, self.neutron_client.show_loadbalancer.call_count)

    def test_delete_failed(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.return_value = {
            'loadbalancer': {'provisioning_status': 'ACTIVE'}}
        self.neutron_client.delete_loadbalancer.side_effect = (
            exceptions.Unauthorized)

        self.lb.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.lb.check_delete_complete, None)
