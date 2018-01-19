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
import yaml

from osc_lib import exceptions

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.octavia import listener
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class ListenerTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = listener.resource_mapping()
        self.assertEqual(listener.Listener,
                         mapping['OS::Octavia::Listener'])

    def _create_stack(self, tmpl=inline_templates.LISTENER_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.listener = self.stack['listener']

        self.octavia_client = mock.MagicMock()
        self.listener.client = mock.MagicMock(return_value=self.octavia_client)
        self.listener.client_plugin().client = mock.MagicMock(
            return_value=self.octavia_client)

    def test_validate_terminated_https(self):
        tmpl = yaml.safe_load(inline_templates.LISTENER_TEMPLATE)
        props = tmpl['resources']['listener']['properties']
        props['protocol'] = 'TERMINATED_HTTPS'
        del props['default_tls_container_ref']
        self._create_stack(tmpl=yaml.safe_dump(tmpl))

        self.assertRaises(exception.StackValidationFailed,
                          self.listener.validate)

    def test_create(self):
        self._create_stack()
        self.octavia_client.listener_show.side_effect = [
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.listener_create.side_effect = [
            exceptions.Conflict(409), {'listener': {'id': '1234'}}
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
        self.octavia_client.listener_create.assert_called_with(json=expected)
        self.assertFalse(self.listener.check_create_complete(props))
        self.octavia_client.listener_create.assert_called_with(json=expected)
        self.assertFalse(self.listener.check_create_complete(props))
        self.assertTrue(self.listener.check_create_complete(props))

    def test_create_missing_properties(self):
        for prop in ('protocol', 'protocol_port', 'loadbalancer'):
            tmpl = yaml.safe_load(inline_templates.LISTENER_TEMPLATE)
            del tmpl['resources']['listener']['properties'][prop]
            del tmpl['resources']['listener']['properties']['default_pool']
            self._create_stack(tmpl=yaml.safe_dump(tmpl))
            if prop == 'loadbalancer':
                self.assertRaises(exception.PropertyUnspecifiedError,
                                  self.listener.validate)
            else:
                self.assertRaises(exception.StackValidationFailed,
                                  self.listener.validate)

    def test_show_resource(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.octavia_client.listener_show.return_value = {'id': '1234'}
        self.assertEqual({'id': '1234'}, self.listener._show_resource())

        self.octavia_client.listener_show.assert_called_with('1234')

    def test_update(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.octavia_client.listener_show.side_effect = [
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.listener_set.side_effect = [
            exceptions.Conflict(409), None]
        prop_diff = {
            'admin_state_up': False,
            'name': 'your_listener',
        }

        prop_diff = self.listener.handle_update(self.listener.t,
                                                None, prop_diff)

        self.assertFalse(self.listener.check_update_complete(prop_diff))
        self.assertFalse(self.listener._update_called)
        self.octavia_client.listener_set.assert_called_with(
            '1234', json={'listener': prop_diff})
        self.assertFalse(self.listener.check_update_complete(prop_diff))
        self.assertTrue(self.listener._update_called)
        self.octavia_client.listener_set.assert_called_with(
            '1234', json={'listener': prop_diff})
        self.assertFalse(self.listener.check_update_complete(prop_diff))
        self.assertTrue(self.listener.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.octavia_client.listener_show.side_effect = [
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'DELETED'},
        ]
        self.octavia_client.listener_delete.side_effect = [
            exceptions.Conflict(409), None]

        self.listener.handle_delete()

        self.assertFalse(self.listener.check_delete_complete(None))
        self.assertFalse(self.listener._delete_called)
        self.octavia_client.listener_delete.assert_called_with('1234')
        self.assertFalse(self.listener.check_delete_complete(None))
        self.assertTrue(self.listener._delete_called)
        self.octavia_client.listener_delete.assert_called_with('1234')
        self.assertTrue(self.listener.check_delete_complete(None))

    def test_delete_not_found(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.octavia_client.listener_show.side_effect = [
            {'provisioning_status': 'PENDING_DELETE'},
        ]
        self.octavia_client.listener_delete.side_effect = [
            exceptions.Conflict(409),
            exceptions.NotFound(404)]

        self.listener.handle_delete()

        self.assertFalse(self.listener.check_delete_complete(None))
        self.assertFalse(self.listener._delete_called)
        self.octavia_client.listener_delete.assert_called_with('1234')
        self.assertTrue(self.listener.check_delete_complete(None))
        self.octavia_client.listener_delete.assert_called_with('1234')

    def test_delete_failed(self):
        self._create_stack()
        self.listener.resource_id_set('1234')
        self.octavia_client.listener_delete.side_effect = (
            exceptions.Unauthorized(401))

        self.listener.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.listener.check_delete_complete, None)
