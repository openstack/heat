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
import yaml

from neutronclient.common import exceptions

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.neutron.lbaas import listener
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class ListenerTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = listener.resource_mapping()
        self.assertEqual(listener.Listener,
                         mapping['OS::Neutron::LBaaS::Listener'])

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func, tmpl=inline_templates.LISTENER_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.listener = self.stack['listener']

        self.neutron_client = mock.MagicMock()
        self.listener.client = mock.MagicMock(return_value=self.neutron_client)

        self.listener.client_plugin().find_resourceid_by_name_or_id = (
            mock.MagicMock(return_value='123'))
        self.listener.client_plugin().client = mock.MagicMock(
            return_value=self.neutron_client)

    def test_validate_terminated_https(self):
        self.patchobject(listener.Listener, 'is_service_available',
                         return_value=(True, None))

        tmpl = yaml.load(inline_templates.LISTENER_TEMPLATE)
        props = tmpl['resources']['listener']['properties']
        props['protocol'] = 'TERMINATED_HTTPS'
        del props['default_tls_container_ref']
        self._create_stack(tmpl=yaml.dump(tmpl))

        self.assertRaises(exception.StackValidationFailed,
                          self.listener.validate)

    def test_create(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.create_listener.side_effect = [
            exceptions.StateInvalidClient,
            {'listener': {'id': '1234'}}
        ]
        expected = {
            'listener': {
                'protocol_port': 80,
                'protocol': 'TCP',
                'loadbalancer_id': '123',
                'default_pool_id': 'my_pool',
                'name': 'my_listener',
                'description': 'my listener',
                'admin_state_up': True,
                'default_tls_container_ref': 'ref',
                'sni_container_refs': ['ref1', 'ref2'],
                'connection_limit': -1,
                'tenant_id': '1234',
            }
        }

        props = self.listener.handle_create()

        self.assertFalse(self.listener.check_create_complete(props))
        self.neutron_client.create_listener.assert_called_with(expected)
        self.assertFalse(self.listener.check_create_complete(props))
        self.neutron_client.create_listener.assert_called_with(expected)
        self.assertFalse(self.listener.check_create_complete(props))
        self.assertTrue(self.listener.check_create_complete(props))

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def test_create_missing_properties(self, ext_func):
        for prop in ('protocol', 'protocol_port', 'loadbalancer'):
            tmpl = yaml.load(inline_templates.LISTENER_TEMPLATE)
            del tmpl['resources']['listener']['properties'][prop]
            del tmpl['resources']['listener']['properties']['default_pool']
            self._create_stack(tmpl=yaml.dump(tmpl))
            if prop == 'loadbalancer':
                self.assertRaises(exception.PropertyUnspecifiedError,
                                  self.listener.validate)
            else:
                self.assertRaises(exception.StackValidationFailed,
                                  self.listener.validate)

    def test_show_resource(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.neutron_client.show_listener.return_value = {
            'listener': {'id': '1234'}
        }

        self.assertEqual({'id': '1234'}, self.listener._show_resource())

        self.neutron_client.show_listener.assert_called_with('1234')

    def test_update(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.update_listener.side_effect = [
            exceptions.StateInvalidClient, None]
        prop_diff = {
            'admin_state_up': False,
            'name': 'your_listener',
        }

        prop_diff = self.listener.handle_update(self.listener.t,
                                                None, prop_diff)

        self.assertFalse(self.listener.check_update_complete(prop_diff))
        self.assertFalse(self.listener._update_called)
        self.neutron_client.update_listener.assert_called_with(
            '1234', {'listener': prop_diff})
        self.assertFalse(self.listener.check_update_complete(prop_diff))
        self.assertTrue(self.listener._update_called)
        self.neutron_client.update_listener.assert_called_with(
            '1234', {'listener': prop_diff})
        self.assertFalse(self.listener.check_update_complete(prop_diff))
        self.assertTrue(self.listener.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.delete_listener.side_effect = [
            exceptions.StateInvalidClient, None]

        self.listener.handle_delete()

        self.assertFalse(self.listener.check_delete_complete(None))
        self.assertFalse(self.listener._delete_called)
        self.neutron_client.delete_listener.assert_called_with('1234')
        self.assertFalse(self.listener.check_delete_complete(None))
        self.assertTrue(self.listener._delete_called)
        self.neutron_client.delete_listener.assert_called_with('1234')
        self.assertFalse(self.listener.check_delete_complete(None))
        self.assertTrue(self.listener.check_delete_complete(None))

    def test_delete_already_gone(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.neutron_client.delete_listener.side_effect = (
            exceptions.NotFound)

        self.listener.handle_delete()
        self.assertTrue(self.listener.check_delete_complete(None))

    def test_delete_failed(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.neutron_client.delete_listener.side_effect = (
            exceptions.Unauthorized)

        self.listener.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.listener.check_delete_complete, None)
