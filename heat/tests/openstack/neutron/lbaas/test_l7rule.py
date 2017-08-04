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

from neutronclient.common import exceptions

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine.resources.openstack.neutron.lbaas import l7rule
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class L7RuleTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = l7rule.resource_mapping()
        self.assertEqual(mapping['OS::Neutron::LBaaS::L7Rule'],
                         l7rule.L7Rule)

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func, tmpl=inline_templates.L7RULE_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.l7rule = self.stack['l7rule']

        self.neutron_client = mock.MagicMock()
        self.l7rule.client = mock.MagicMock(return_value=self.neutron_client)

        self.l7rule.client_plugin().find_resourceid_by_name_or_id = (
            mock.MagicMock(return_value='123'))
        self.l7rule.client_plugin().client = mock.MagicMock(
            return_value=self.neutron_client)
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_UPDATE'}},
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
        ]

    def test_validate_when_key_required(self):
        tmpl = yaml.load(inline_templates.L7RULE_TEMPLATE)
        props = tmpl['resources']['l7rule']['properties']
        del props['key']
        self._create_stack(tmpl=yaml.dump(tmpl))

        msg = _('Property key is missing. This property should be '
                'specified for rules of HEADER and COOKIE types.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.StackValidationFailed,
                                   msg, self.l7rule.validate)

    def test_create(self):
        self._create_stack()
        self.neutron_client.create_lbaas_l7rule.side_effect = [
            exceptions.StateInvalidClient,
            {'rule': {'id': '1234'}}
        ]
        expected = (
            '123',
            {
                'rule': {
                    'admin_state_up': True,
                    'invert': False,
                    'type': u'HEADER',
                    'compare_type': u'ENDS_WITH',
                    'key': u'test_key',
                    'value': u'test_value',
                    'invert': False
                }
            }
        )

        props = self.l7rule.handle_create()

        self.assertFalse(self.l7rule.check_create_complete(props))
        self.neutron_client.create_lbaas_l7rule.assert_called_with(*expected)
        self.assertFalse(self.l7rule.check_create_complete(props))
        self.neutron_client.create_lbaas_l7rule.assert_called_with(*expected)
        self.assertFalse(self.l7rule.check_create_complete(props))
        self.assertTrue(self.l7rule.check_create_complete(props))

    def test_create_missing_properties(self):
        self.patchobject(l7rule.L7Rule, 'is_service_available',
                         return_value=(True, None))

        for prop in ('l7policy', 'type', 'compare_type', 'value'):
            tmpl = yaml.load(inline_templates.L7RULE_TEMPLATE)
            del tmpl['resources']['l7rule']['properties'][prop]
            self._create_stack(tmpl=yaml.dump(tmpl))

            self.assertRaises(exception.StackValidationFailed,
                              self.l7rule.validate)

    def test_show_resource(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.neutron_client.show_lbaas_l7rule.return_value = {
            'rule': {'id': '1234'}
        }

        self.assertEqual({'id': '1234'}, self.l7rule._show_resource())

        self.neutron_client.show_lbaas_l7rule.assert_called_with('1234', '123')

    def test_update(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.neutron_client.update_lbaas_l7rule.side_effect = [
            exceptions.StateInvalidClient, None]
        prop_diff = {
            'admin_state_up': False,
            'name': 'your_l7policy',
            'redirect_url': 'http://www.google.com'
        }

        prop_diff = self.l7rule.handle_update(None, None, prop_diff)

        self.assertFalse(self.l7rule.check_update_complete(prop_diff))
        self.assertFalse(self.l7rule._update_called)
        self.neutron_client.update_lbaas_l7rule.assert_called_with(
            '1234', '123', {'rule': prop_diff})
        self.assertFalse(self.l7rule.check_update_complete(prop_diff))
        self.assertTrue(self.l7rule._update_called)
        self.neutron_client.update_lbaas_l7rule.assert_called_with(
            '1234', '123', {'rule': prop_diff})
        self.assertFalse(self.l7rule.check_update_complete(prop_diff))
        self.assertTrue(self.l7rule.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.neutron_client.delete_lbaas_l7rule.side_effect = [
            exceptions.StateInvalidClient, None]

        self.l7rule.handle_delete()

        self.assertFalse(self.l7rule.check_delete_complete(None))
        self.assertFalse(self.l7rule._delete_called)
        self.assertFalse(self.l7rule.check_delete_complete(None))
        self.assertTrue(self.l7rule._delete_called)
        self.neutron_client.delete_lbaas_l7rule.assert_called_with(
            '1234', '123')
        self.assertFalse(self.l7rule.check_delete_complete(None))
        self.assertTrue(self.l7rule.check_delete_complete(None))

    def test_delete_already_gone(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.neutron_client.delete_lbaas_l7rule.side_effect = (
            exceptions.NotFound)

        self.l7rule.handle_delete()
        self.assertTrue(self.l7rule.check_delete_complete(None))

    def test_delete_failed(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.neutron_client.delete_lbaas_l7rule.side_effect = (
            exceptions.Unauthorized)

        self.l7rule.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.l7rule.check_delete_complete, None)
