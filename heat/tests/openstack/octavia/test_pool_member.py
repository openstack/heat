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

from heat.common import template_format
from heat.engine import properties
from heat.engine.resources.openstack.octavia import pool_member
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class PoolMemberTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = pool_member.resource_mapping()
        self.assertEqual(pool_member.PoolMember,
                         mapping['OS::Octavia::PoolMember'])

    def _create_stack(self, tmpl=inline_templates.MEMBER_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.member = self.stack['member']
        self.patchobject(neutronV20, 'find_resourceid_by_name_or_id',
                         return_value='123')

        self.octavia_client = mock.MagicMock()
        self.member.client = mock.MagicMock(return_value=self.octavia_client)
        self.member.client_plugin().get_pool = (
            mock.MagicMock(return_value='123'))
        self.member.client_plugin().client = mock.MagicMock(
            return_value=self.octavia_client)
        self.member.translate_properties(self.member.properties)

    def test_create(self):
        self._create_stack()
        self.octavia_client.member_show.side_effect = [
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.member_create.side_effect = [
            exceptions.Conflict(409), {'member': {'id': '1234'}}]
        expected = {
            'member': {
                'address': '1.2.3.4',
                'protocol_port': 80,
                'weight': 1,
                'subnet_id': '123',
                'admin_state_up': True,
            }
        }
        props = self.member.handle_create()
        self.assertFalse(self.member.check_create_complete(props))
        self.octavia_client.member_create.assert_called_with('123',
                                                             json=expected)
        self.assertFalse(self.member.check_create_complete(props))
        self.octavia_client.member_create.assert_called_with('123',
                                                             json=expected)
        self.assertFalse(self.member.check_create_complete(props))
        self.assertTrue(self.member.check_create_complete(props))

    def test_show_resource(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.octavia_client.member_show.return_value = {'id': '1234'}

        self.assertEqual(self.member._show_resource(), {'id': '1234'})

        self.octavia_client.member_show.assert_called_with('123', '1234')

    def test_update(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.octavia_client.member_show.side_effect = [
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.member_set.side_effect = [
            exceptions.Conflict(409), None]
        prop_diff = {
            'admin_state_up': False,
            'weight': 2,
        }

        prop_diff = self.member.handle_update(None, None, prop_diff)

        self.assertFalse(self.member.check_update_complete(prop_diff))
        self.assertFalse(self.member._update_called)
        self.octavia_client.member_set.assert_called_with(
            '123', '1234', json={'member': prop_diff})
        self.assertFalse(self.member.check_update_complete(prop_diff))
        self.assertTrue(self.member._update_called)
        self.octavia_client.member_set.assert_called_with(
            '123', '1234', json={'member': prop_diff})
        self.assertFalse(self.member.check_update_complete(prop_diff))
        self.assertTrue(self.member.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.octavia_client.member_show.side_effect = [
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'DELETED'},
        ]
        self.octavia_client.member_delete.side_effect = [
            exceptions.Conflict(409),
            None]

        self.member.handle_delete()

        self.assertFalse(self.member.check_delete_complete(None))
        self.assertFalse(self.member._delete_called)
        self.octavia_client.member_delete.assert_called_with('123',
                                                             '1234')
        self.assertFalse(self.member.check_delete_complete(None))
        self.octavia_client.member_delete.assert_called_with('123',
                                                             '1234')
        self.assertTrue(self.member._delete_called)
        self.assertTrue(self.member.check_delete_complete(None))

    def test_delete_not_found(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.octavia_client.member_show.side_effect = [
            {'provisioning_status': 'PENDING_DELETE'},
        ]
        self.octavia_client.member_delete.side_effect = [
            exceptions.Conflict(409),
            exceptions.NotFound(404)]

        self.member.handle_delete()

        self.assertFalse(self.member.check_delete_complete(None))
        self.assertFalse(self.member._delete_called)
        self.octavia_client.member_delete.assert_called_with('123',
                                                             '1234')
        self.assertTrue(self.member.check_delete_complete(None))
        self.octavia_client.member_delete.assert_called_with('123',
                                                             '1234')
        self.assertFalse(self.member._delete_called)

    def _prepare_delete_with_value_error(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.m_gpv = self.patchobject(properties.Properties,
                                      '_get_property_value',
                                      side_effect=ValueError)

    def test_delete_value_error_with_not_found(self):
        self._prepare_delete_with_value_error()
        m_get_pool = mock.Mock(side_effect=exceptions.NotFound(404))
        self.member.client_plugin().get_pool = m_get_pool

        self.member.handle_delete()

        self.assertTrue(self.member.check_delete_complete(None))
        m_get_pool.assert_called_once_with(123)
        self.assertFalse(self.member._delete_called)
        self.assertEqual(0, self.octavia_client.member_delete.call_count)
        self.m_gpv.assert_called_once_with('pool')

    def test_delete_value_error_with_pool_found(self):
        self._prepare_delete_with_value_error()
        self.member.client_plugin().get_pool = mock.Mock(return_value='123')

        self.member.handle_delete()

        self.assertRaises(ValueError, self.member.check_delete_complete, None)
        self.assertFalse(self.member._delete_called)
        self.assertEqual(0, self.octavia_client.member_delete.call_count)
        self.m_gpv.assert_called_once_with('pool')

    def test_delete_value_error_with_pool_error(self):
        self._prepare_delete_with_value_error()
        self.member.client_plugin().get_pool = mock.Mock(side_effect=KeyError)

        self.member.handle_delete()

        self.assertRaises(KeyError, self.member.check_delete_complete, None)
        self.assertFalse(self.member._delete_called)
        self.assertEqual(0, self.octavia_client.member_delete.call_count)
        self.m_gpv.assert_called_once_with('pool')

    def test_delete_failed(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.octavia_client.member_delete.side_effect = (
            exceptions.Unauthorized(401))

        self.member.handle_delete()

        self.assertRaises(exceptions.Unauthorized,
                          self.member.check_delete_complete, None)

    def _prepare_get_pool_prop(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.m_prop = self.patchobject(
            properties.Properties, '_get_property_value')

    def test_get_pool_prop(self):
        self._prepare_get_pool_prop()
        self.member._get_pool_prop()
        self.m_prop.assert_called_once_with('pool')

    def _get_pool_prop_with_value_error(self, side_effect=[]):
        self._prepare_get_pool_prop()
        self.m_prop.side_effect = ValueError
        self.member.client_plugin().get_pool = mock.Mock(
            side_effect=side_effect)

    def test_get_pool_prop_value_error_and_raise_exception(self):
        self._get_pool_prop_with_value_error(
            side_effect=exceptions.NotFound(404))

        self.assertRaises(
            exceptions.NotFound, self.member._get_pool_prop)

    def test_get_pool_prop_value_error_and_raise(self):
        self._get_pool_prop_with_value_error(side_effect=['foo'])

        self.assertRaises(ValueError, self.member._get_pool_prop)
