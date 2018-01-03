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
from heat.engine.resources.openstack.octavia import l7policy
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class L7PolicyTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = l7policy.resource_mapping()
        self.assertEqual(mapping['OS::Octavia::L7Policy'],
                         l7policy.L7Policy)

    def _create_stack(self, tmpl=inline_templates.L7POLICY_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.l7policy = self.stack['l7policy']

        self.octavia_client = mock.MagicMock()
        self.l7policy.client = mock.MagicMock(
            return_value=self.octavia_client)
        self.l7policy.client_plugin().client = mock.MagicMock(
            return_value=self.octavia_client)

    def test_validate_reject_action_with_conflicting_props(self):
        tmpl = yaml.safe_load(inline_templates.L7POLICY_TEMPLATE)
        props = tmpl['resources']['l7policy']['properties']
        props['action'] = 'REJECT'
        self._create_stack(tmpl=yaml.safe_dump(tmpl))

        msg = _('Properties redirect_pool and redirect_url are not '
                'required when action type is set to REJECT.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.StackValidationFailed,
                                   msg, self.l7policy.validate)

    def test_validate_redirect_pool_action_with_url(self):
        tmpl = yaml.safe_load(inline_templates.L7POLICY_TEMPLATE)
        props = tmpl['resources']['l7policy']['properties']
        props['action'] = 'REDIRECT_TO_POOL'
        props['redirect_pool'] = '123'
        self._create_stack(tmpl=yaml.safe_dump(tmpl))

        msg = _('redirect_url property should only be specified '
                'for action with value REDIRECT_TO_URL.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.ResourcePropertyValueDependency,
                                   msg, self.l7policy.validate)

    def test_validate_redirect_pool_action_without_pool(self):
        tmpl = yaml.safe_load(inline_templates.L7POLICY_TEMPLATE)
        props = tmpl['resources']['l7policy']['properties']
        props['action'] = 'REDIRECT_TO_POOL'
        del props['redirect_url']
        self._create_stack(tmpl=yaml.safe_dump(tmpl))

        msg = _('Property redirect_pool is required when action type '
                'is set to REDIRECT_TO_POOL.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.StackValidationFailed,
                                   msg, self.l7policy.validate)

    def test_validate_redirect_url_action_with_pool(self):
        tmpl = yaml.safe_load(inline_templates.L7POLICY_TEMPLATE)
        props = tmpl['resources']['l7policy']['properties']
        props['redirect_pool'] = '123'
        self._create_stack(tmpl=yaml.safe_dump(tmpl))

        msg = _('redirect_pool property should only be specified '
                'for action with value REDIRECT_TO_POOL.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.ResourcePropertyValueDependency,
                                   msg, self.l7policy.validate)

    def test_validate_redirect_url_action_without_url(self):
        tmpl = yaml.safe_load(inline_templates.L7POLICY_TEMPLATE)
        props = tmpl['resources']['l7policy']['properties']
        del props['redirect_url']
        self._create_stack(tmpl=yaml.safe_dump(tmpl))

        msg = _('Property redirect_url is required when action type '
                'is set to REDIRECT_TO_URL.')
        with mock.patch('heat.engine.clients.os.neutron.NeutronClientPlugin.'
                        'has_extension', return_value=True):
            self.assertRaisesRegex(exception.StackValidationFailed,
                                   msg, self.l7policy.validate)

    def test_create(self):
        self._create_stack()
        self.octavia_client.l7policy_show.side_effect = [
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'PENDING_CREATE'},
            {'provisioning_status': 'ACTIVE'},
        ]

        self.octavia_client.l7policy_create.side_effect = [
            exceptions.Conflict(409),
            {'l7policy': {'id': '1234'}}
        ]
        expected = {
            'l7policy': {
                'name': u'test_l7policy',
                'description': u'test l7policy resource',
                'action': u'REDIRECT_TO_URL',
                'listener_id': u'123',
                'redirect_url': u'http://www.mirantis.com',
                'position': 1,
                'admin_state_up': True
            }
        }

        props = self.l7policy.handle_create()

        self.assertFalse(self.l7policy.check_create_complete(props))
        self.octavia_client.l7policy_create.assert_called_with(json=expected)
        self.assertFalse(self.l7policy.check_create_complete(props))
        self.octavia_client.l7policy_create.assert_called_with(json=expected)
        self.assertFalse(self.l7policy.check_create_complete(props))
        self.assertTrue(self.l7policy.check_create_complete(props))

    def test_create_missing_properties(self):
        for prop in ('action', 'listener'):
            tmpl = yaml.load(inline_templates.L7POLICY_TEMPLATE)
            del tmpl['resources']['l7policy']['properties'][prop]
            self._create_stack(tmpl=yaml.dump(tmpl))

            self.assertRaises(exception.StackValidationFailed,
                              self.l7policy.validate)

    def test_show_resource(self):
        self._create_stack()
        self.l7policy.resource_id_set('1234')
        self.octavia_client.l7policy_show.return_value = {'id': '1234'}

        self.assertEqual({'id': '1234'}, self.l7policy._show_resource())

        self.octavia_client.l7policy_show.assert_called_with('1234')

    def test_update(self):
        self._create_stack()
        self.l7policy.resource_id_set('1234')
        self.octavia_client.l7policy_show.side_effect = [
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.l7policy_set.side_effect = [
            exceptions.Conflict(409), None]
        prop_diff = {
            'admin_state_up': False,
            'name': 'your_l7policy',
            'redirect_url': 'http://www.google.com'
        }

        prop_diff = self.l7policy.handle_update(None, None, prop_diff)

        self.assertFalse(self.l7policy.check_update_complete(prop_diff))
        self.assertFalse(self.l7policy._update_called)
        self.octavia_client.l7policy_set.assert_called_with(
            '1234', json={'l7policy': prop_diff})
        self.assertFalse(self.l7policy.check_update_complete(prop_diff))
        self.assertTrue(self.l7policy._update_called)
        self.octavia_client.l7policy_set.assert_called_with(
            '1234', json={'l7policy': prop_diff})
        self.assertFalse(self.l7policy.check_update_complete(prop_diff))
        self.assertTrue(self.l7policy.check_update_complete(prop_diff))

    def test_update_redirect_pool_prop_name(self):
        self._create_stack()
        self.l7policy.resource_id_set('1234')
        self.octavia_client.l7policy_show.side_effect = [
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'PENDING_UPDATE'},
            {'provisioning_status': 'ACTIVE'},
        ]
        self.octavia_client.l7policy_set.side_effect = [
            exceptions.Conflict(409), None]

        unresolved_diff = {
            'redirect_url': None,
            'action': 'REDIRECT_TO_POOL',
            'redirect_pool': 'UNRESOLVED_POOL'
        }
        resolved_diff = {
            'redirect_url': None,
            'action': 'REDIRECT_TO_POOL',
            'redirect_pool_id': '123'
        }

        self.l7policy.handle_update(None, None, unresolved_diff)

        self.assertFalse(self.l7policy.check_update_complete(resolved_diff))
        self.assertFalse(self.l7policy._update_called)
        self.octavia_client.l7policy_set.assert_called_with(
            '1234', json={'l7policy': resolved_diff})
        self.assertFalse(self.l7policy.check_update_complete(resolved_diff))
        self.assertTrue(self.l7policy._update_called)
        self.octavia_client.l7policy_set.assert_called_with(
            '1234', json={'l7policy': resolved_diff})
        self.assertFalse(self.l7policy.check_update_complete(resolved_diff))
        self.assertTrue(self.l7policy.check_update_complete(resolved_diff))

    def test_delete(self):
        self._create_stack()
        self.l7policy.resource_id_set('1234')
        self.octavia_client.l7policy_show.side_effect = [
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'PENDING_DELETE'},
            {'provisioning_status': 'DELETED'},
        ]
        self.octavia_client.l7policy_delete.side_effect = [
            exceptions.Conflict(409),
            None]

        self.l7policy.handle_delete()

        self.assertFalse(self.l7policy.check_delete_complete(None))
        self.assertFalse(self.l7policy._delete_called)
        self.octavia_client.l7policy_delete.assert_called_with(
            '1234')
        self.assertFalse(self.l7policy.check_delete_complete(None))
        self.assertTrue(self.l7policy._delete_called)
        self.octavia_client.l7policy_delete.assert_called_with(
            '1234')
        self.assertTrue(self.l7policy.check_delete_complete(None))

    def test_delete_failed(self):
        self._create_stack()
        self.l7policy.resource_id_set('1234')
        self.octavia_client.l7policy_delete.side_effect = (
            exceptions.Unauthorized(401))

        self.l7policy.handle_delete()
        self.assertRaises(exceptions.Unauthorized,
                          self.l7policy.check_delete_complete, None)

        self.octavia_client.l7policy_delete.assert_called_with(
            '1234')
