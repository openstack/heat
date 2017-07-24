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
from heat.common.i18n import _
from heat.common import template_format
from heat.engine.resources.openstack.neutron.lbaas import pool
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class PoolTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = pool.resource_mapping()
        self.assertEqual(pool.Pool,
                         mapping['OS::Neutron::LBaaS::Pool'])

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func, tmpl=inline_templates.POOL_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.pool = self.stack['pool']

        self.neutron_client = mock.MagicMock()
        self.pool.client = mock.MagicMock(return_value=self.neutron_client)

        self.pool.client_plugin().find_resourceid_by_name_or_id = (
            mock.MagicMock(return_value='123'))
        self.pool.client_plugin().client = mock.MagicMock(
            return_value=self.neutron_client)

    def test_validate_no_cookie_name(self):
        tmpl = yaml.load(inline_templates.POOL_TEMPLATE)
        sp = tmpl['resources']['pool']['properties']['session_persistence']
        sp['type'] = 'APP_COOKIE'
        self._create_stack(tmpl=yaml.dump(tmpl))

        msg = _('Property cookie_name is required when '
                'session_persistence type is set to APP_COOKIE.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.StackValidationFailed,
                                   msg, self.pool.validate)

    def test_validate_source_ip_cookie_name(self):
        tmpl = yaml.load(inline_templates.POOL_TEMPLATE)
        sp = tmpl['resources']['pool']['properties']['session_persistence']
        sp['type'] = 'SOURCE_IP'
        sp['cookie_name'] = 'cookie'
        self._create_stack(tmpl=yaml.dump(tmpl))

        msg = _('Property cookie_name must NOT be specified when '
                'session_persistence type is set to SOURCE_IP.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.StackValidationFailed,
                                   msg, self.pool.validate)

    def test_create(self):
        self._create_stack()
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.create_lbaas_pool.side_effect = [
            exceptions.StateInvalidClient,
            {'pool': {'id': '1234'}}
        ]
        expected = {
            'pool': {
                'name': 'my_pool',
                'description': 'my pool',
                'session_persistence': {
                    'type': 'HTTP_COOKIE'
                },
                'lb_algorithm': 'ROUND_ROBIN',
                'listener_id': '123',
                'loadbalancer_id': 'my_lb',
                'protocol': 'HTTP',
                'admin_state_up': True
            }
        }

        props = self.pool.handle_create()

        self.assertFalse(self.pool.check_create_complete(props))
        self.neutron_client.create_lbaas_pool.assert_called_with(expected)
        self.assertFalse(self.pool.check_create_complete(props))
        self.neutron_client.create_lbaas_pool.assert_called_with(expected)
        self.assertFalse(self.pool.check_create_complete(props))
        self.assertTrue(self.pool.check_create_complete(props))

    def test_create_missing_properties(self):
        self.patchobject(pool.Pool, 'is_service_available',
                         return_value=(True, None))

        for prop in ('lb_algorithm', 'listener', 'protocol'):
            tmpl = yaml.load(inline_templates.POOL_TEMPLATE)
            del tmpl['resources']['pool']['properties']['loadbalancer']
            del tmpl['resources']['pool']['properties'][prop]
            self._create_stack(tmpl=yaml.dump(tmpl))
            if prop == 'listener':
                self.assertRaises(exception.PropertyUnspecifiedError,
                                  self.pool.validate)
            else:
                self.assertRaises(exception.StackValidationFailed,
                                  self.pool.validate)

    def test_show_resource(self):
        self._create_stack()
        self.pool.resource_id_set('1234')
        self.neutron_client.show_lbaas_pool.return_value = {
            'pool': {'id': '1234'}
        }

        self.assertEqual(self.pool._show_resource(), {'id': '1234'})

        self.neutron_client.show_lbaas_pool.assert_called_with('1234')

    def test_update(self):
        self._create_stack()
        self.pool.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.update_lbaas_pool.side_effect = [
            exceptions.StateInvalidClient, None]
        prop_diff = {
            'admin_state_up': False,
            'name': 'your_pool',
            'lb_algorithm': 'SOURCE_IP'
        }

        prop_diff = self.pool.handle_update(None, None, prop_diff)

        self.assertFalse(self.pool.check_update_complete(prop_diff))
        self.assertFalse(self.pool._update_called)
        self.neutron_client.update_lbaas_pool.assert_called_with(
            '1234', {'pool': prop_diff})
        self.assertFalse(self.pool.check_update_complete(prop_diff))
        self.assertTrue(self.pool._update_called)
        self.neutron_client.update_lbaas_pool.assert_called_with(
            '1234', {'pool': prop_diff})
        self.assertFalse(self.pool.check_update_complete(prop_diff))
        self.assertTrue(self.pool.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.pool.resource_id_set('1234')
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]
        self.neutron_client.delete_lbaas_pool.side_effect = [
            exceptions.StateInvalidClient, None]

        self.pool.handle_delete()

        self.assertFalse(self.pool.check_delete_complete(None))
        self.assertFalse(self.pool._delete_called)
        self.assertFalse(self.pool.check_delete_complete(None))
        self.assertTrue(self.pool._delete_called)
        self.neutron_client.delete_lbaas_pool.assert_called_with('1234')
        self.assertFalse(self.pool.check_delete_complete(None))
        self.assertTrue(self.pool.check_delete_complete(None))

    def test_delete_already_gone(self):
        self._create_stack()
        self.pool.resource_id_set('1234')
        self.neutron_client.delete_lbaas_pool.side_effect = (
            exceptions.NotFound)

        self.pool.handle_delete()
        self.assertTrue(self.pool.check_delete_complete(None))

    def test_delete_failed(self):
        self._create_stack()
        self.pool.resource_id_set('1234')
        self.neutron_client.delete_lbaas_pool.side_effect = (
            exceptions.Unauthorized)

        self.pool.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.pool.check_delete_complete, None)
