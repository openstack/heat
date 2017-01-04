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

from heat.common import template_format
from heat.engine.resources.openstack.neutron.lbaas import pool_member
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class PoolMemberTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = pool_member.resource_mapping()
        self.assertEqual(pool_member.PoolMember,
                         mapping['OS::Neutron::LBaaS::PoolMember'])

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func, tmpl=inline_templates.MEMBER_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.member = self.stack['member']

        self.neutron_client = mock.MagicMock()
        self.member.client = mock.MagicMock(return_value=self.neutron_client)

        self.member.client_plugin().find_resourceid_by_name_or_id = (
            mock.MagicMock(return_value='123'))
        self.member.client_plugin().client = mock.MagicMock(
            return_value=self.neutron_client)
        self.member.translate_properties(self.member.properties)

    def test_create(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.create_lbaas_member.side_effect = [
            exceptions.StateInvalidClient,
            {'member': {'id': '1234'}}
        ]
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
        self.neutron_client.create_lbaas_member.assert_called_with('123',
                                                                   expected)
        self.assertFalse(self.member.check_create_complete(props))
        self.neutron_client.create_lbaas_member.assert_called_with('123',
                                                                   expected)
        self.assertFalse(self.member.check_create_complete(props))
        self.assertTrue(self.member.check_create_complete(props))

    def test_show_resource(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.neutron_client.show_lbaas_member.return_value = {
            'member': {'id': '1234'}
        }

        self.assertEqual(self.member._show_resource(), {'id': '1234'})

        self.neutron_client.show_lbaas_member.assert_called_with('1234', '123')

    def test_update(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.update_lbaas_member.side_effect = [
            exceptions.StateInvalidClient, None]
        prop_diff = {
            'admin_state_up': False,
            'weight': 2,
        }

        prop_diff = self.member.handle_update(None, None, prop_diff)

        self.assertFalse(self.member.check_update_complete(prop_diff))
        self.assertFalse(self.member._update_called)
        self.neutron_client.update_lbaas_member.assert_called_with(
            '1234', '123', {'member': prop_diff})
        self.assertFalse(self.member.check_update_complete(prop_diff))
        self.assertTrue(self.member._update_called)
        self.neutron_client.update_lbaas_member.assert_called_with(
            '1234', '123', {'member': prop_diff})
        self.assertFalse(self.member.check_update_complete(prop_diff))
        self.assertTrue(self.member.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.delete_lbaas_member.side_effect = [
            exceptions.StateInvalidClient, None]

        self.member.handle_delete()

        self.assertFalse(self.member.check_delete_complete(None))
        self.assertFalse(self.member._delete_called)
        self.neutron_client.delete_lbaas_member.assert_called_with('1234',
                                                                   '123')
        self.assertFalse(self.member.check_delete_complete(None))
        self.assertTrue(self.member._delete_called)
        self.neutron_client.delete_lbaas_member.assert_called_with('1234',
                                                                   '123')
        self.assertFalse(self.member.check_delete_complete(None))
        self.assertTrue(self.member.check_delete_complete(None))

    def test_delete_already_gone(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.neutron_client.delete_lbaas_member.side_effect = (
            exceptions.NotFound)

        self.member.handle_delete()

        self.assertTrue(self.member.check_delete_complete(None))

    def test_delete_failed(self):
        self._create_stack()
        self.member.resource_id_set('1234')
        self.neutron_client.delete_lbaas_member.side_effect = (
            exceptions.Unauthorized)

        self.member.handle_delete()

        self.assertRaises(exceptions.Unauthorized,
                          self.member.check_delete_complete, None)
