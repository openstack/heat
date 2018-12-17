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

from neutronclient.neutron import v2_0 as neutronV20
from osc_lib import exceptions

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.octavia import loadbalancer
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class LoadBalancerTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = loadbalancer.resource_mapping()
        self.assertEqual(loadbalancer.LoadBalancer,
                         mapping['OS::Octavia::LoadBalancer'])

    def _create_stack(self, tmpl=inline_templates.LB_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.lb = self.stack['lb']
        self.octavia_client = mock.MagicMock()
        self.lb.client = mock.MagicMock()
        self.lb.client.return_value = self.octavia_client

        self.patchobject(neutronV20, 'find_resourceid_by_name_or_id',
                         return_value='123')

        self.lb.client_plugin().client = mock.MagicMock(
            return_value=self.octavia_client)
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
                'project_id': '1234',
                'admin_state_up': True,
            }
        }

        self.lb.handle_create()

        self.octavia_client.load_balancer_create.assert_called_with(
            json=expected)

    def test_check_create_complete(self):
        self._create_stack()
        self.octavia_client.load_balancer_show.side_effect = [
            {'provisioning_status': 'ACTIVE'},
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'ERROR'},
        ]

        self.assertTrue(self.lb.check_create_complete(None))
        self.assertFalse(self.lb.check_create_complete(None))
        self.assertRaises(exception.ResourceInError,
                          self.lb.check_create_complete, None)

    def test_show_resource(self):
        self._create_stack()
        self.octavia_client.load_balancer_show.return_value = {'id': '1234'}
        self.assertEqual({'id': '1234'}, self.lb._show_resource())

        self.octavia_client.load_balancer_show.assert_called_with('1234')

    def test_update(self):
        self._create_stack()
        prop_diff = {
            'name': 'lb',
            'description': 'a loadbalancer',
            'admin_state_up': False,
        }

        prop_diff = self.lb.handle_update(None, None, prop_diff)

        self.octavia_client.load_balancer_set.assert_called_once_with(
            '1234', json={'loadbalancer': prop_diff})

    def test_update_complete(self):
        self._create_stack()
        prop_diff = {
            'name': 'lb',
            'description': 'a loadbalancer',
            'admin_state_up': False,
        }
        self.octavia_client.load_balancer_show.side_effect = [
            {'provisioning_status': 'ACTIVE'},
            {'provisioning_status': 'PENDING_UPDATE'},
        ]

        self.lb.handle_update(None, None, prop_diff)

        self.assertTrue(self.lb.check_update_complete(prop_diff))
        self.assertFalse(self.lb.check_update_complete(prop_diff))
        self.assertTrue(self.lb.check_update_complete({}))

    def test_delete(self):
        self._create_stack()
        self.octavia_client.load_balancer_show.side_effect = [
            {'provisioning_status': 'DELETE_PENDING'},
            {'provisioning_status': 'DELETE_PENDING'},
            {'provisioning_status': 'DELETED'},
        ]

        self.octavia_client.load_balancer_delete.side_effect = [
            exceptions.Conflict(409),
            None
        ]

        self.lb.handle_delete()

        self.assertFalse(self.lb.check_delete_complete(None))
        self.assertFalse(self.lb._delete_called)
        self.assertFalse(self.lb.check_delete_complete(None))
        self.assertTrue(self.lb._delete_called)
        self.assertTrue(self.lb.check_delete_complete(None))
        self.octavia_client.load_balancer_delete.assert_called_with('1234')
        self.assertEqual(
            2, self.octavia_client.load_balancer_delete.call_count)

    def test_delete_error(self):
        self._create_stack()
        self.octavia_client.load_balancer_show.side_effect = [
            {'provisioning_status': 'DELETE_PENDING'},
        ]

        self.octavia_client.load_balancer_delete.side_effect = [
            exceptions.Conflict(409),
            exceptions.NotFound(404)
        ]

        self.lb.handle_delete()

        self.assertFalse(self.lb.check_delete_complete(None))
        self.assertTrue(self.lb.check_delete_complete(None))
        self.octavia_client.load_balancer_delete.assert_called_with('1234')
        self.assertEqual(
            2, self.octavia_client.load_balancer_delete.call_count)

    def test_delete_failed(self):
        self._create_stack()
        self.octavia_client.load_balancer_delete.side_effect = (
            exceptions.Unauthorized(403))

        self.lb.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.lb.check_delete_complete, None)
