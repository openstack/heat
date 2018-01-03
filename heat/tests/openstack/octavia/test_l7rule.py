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
from heat.common.i18n import _
from heat.common import template_format
from heat.engine.resources.openstack.octavia import l7rule
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class L7RuleTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = l7rule.resource_mapping()
        self.assertEqual(mapping['OS::Octavia::L7Rule'],
                         l7rule.L7Rule)

    def _create_stack(self, tmpl=inline_templates.L7RULE_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.l7rule = self.stack['l7rule']

        self.octavia_client = mock.MagicMock()
        self.l7rule.client = mock.MagicMock(
            return_value=self.octavia_client)
        self.l7rule.client_plugin().client = mock.MagicMock(
            return_value=self.octavia_client)

    def test_validate_when_key_required(self):
        tmpl = yaml.safe_load(inline_templates.L7RULE_TEMPLATE)
        props = tmpl['resources']['l7rule']['properties']
        del props['key']
        self._create_stack(tmpl=yaml.safe_dump(tmpl))

        msg = _('Property key is missing. This property should be '
                'specified for rules of HEADER and COOKIE types.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.StackValidationFailed,
                                   msg, self.l7rule.validate)

    def test_create(self):
        self._create_stack()
        self.octavia_client.l7rule_show.side_effect = [
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.l7rule_create.side_effect = [
            exceptions.Conflict(409),
            {'rule': {'id': '1234'}}
        ]
        expected = {
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

        props = self.l7rule.handle_create()
        self.assertFalse(self.l7rule.check_create_complete(props))
        self.octavia_client.l7rule_create.assert_called_with('123',
                                                             json=expected)
        self.assertFalse(self.l7rule.check_create_complete(props))
        self.octavia_client.l7rule_create.assert_called_with('123',
                                                             json=expected)
        self.assertFalse(self.l7rule.check_create_complete(props))
        self.assertTrue(self.l7rule.check_create_complete(props))

    def test_create_missing_properties(self):
        for prop in ('l7policy', 'type', 'compare_type', 'value'):
            tmpl = yaml.safe_load(inline_templates.L7RULE_TEMPLATE)
            del tmpl['resources']['l7rule']['properties'][prop]
            self._create_stack(tmpl=yaml.safe_dump(tmpl))

            self.assertRaises(exception.StackValidationFailed,
                              self.l7rule.validate)

    def test_show_resource(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.octavia_client.l7rule_show.return_value = {'id': '1234'}

        self.assertEqual({'id': '1234'}, self.l7rule._show_resource())

        self.octavia_client.l7rule_show.assert_called_with('1234', '123')

    def test_update(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.octavia_client.l7rule_show.side_effect = [
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.l7rule_set.side_effect = [
            exceptions.Conflict(409), None]
        prop_diff = {
            'admin_state_up': False,
            'name': 'your_l7policy',
            'redirect_url': 'http://www.google.com'
        }

        prop_diff = self.l7rule.handle_update(None, None, prop_diff)

        self.assertFalse(self.l7rule.check_update_complete(prop_diff))
        self.assertFalse(self.l7rule._update_called)
        self.octavia_client.l7rule_set.assert_called_with(
            '1234', '123', json={'rule': prop_diff})
        self.assertFalse(self.l7rule.check_update_complete(prop_diff))
        self.assertTrue(self.l7rule._update_called)
        self.octavia_client.l7rule_set.assert_called_with(
            '1234', '123', json={'rule': prop_diff})
        self.assertFalse(self.l7rule.check_update_complete(prop_diff))
        self.assertTrue(self.l7rule.check_update_complete(prop_diff))

    def test_delete(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.octavia_client.l7rule_show.side_effect = [
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'DELETED'},
        ]
        self.octavia_client.l7rule_delete.side_effect = [
            exceptions.Conflict(409),
            None]

        self.l7rule.handle_delete()

        self.assertFalse(self.l7rule.check_delete_complete(None))
        self.assertFalse(self.l7rule._delete_called)
        self.assertFalse(self.l7rule.check_delete_complete(None))
        self.assertTrue(self.l7rule._delete_called)
        self.octavia_client.l7rule_delete.assert_called_with(
            '1234', '123')
        self.assertTrue(self.l7rule.check_delete_complete(None))

    def test_delete_already_gone(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.octavia_client.l7rule_delete.side_effect = (
            exceptions.NotFound(404))

        self.l7rule.handle_delete()
        self.assertTrue(self.l7rule.check_delete_complete(None))

    def test_delete_failed(self):
        self._create_stack()
        self.l7rule.resource_id_set('1234')
        self.octavia_client.l7rule_delete.side_effect = (
            exceptions.Unauthorized(401))

        self.l7rule.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.l7rule.check_delete_complete, None)
