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
from heat.common import template_format
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class RBACPolicyTest(common.HeatTestCase):

    @mock.patch('heat.engine.clients.os.neutron.'
                'NeutronClientPlugin.has_extension', return_value=True)
    def _create_stack(self, ext_func, tmpl=inline_templates.RBAC_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.rbac = self.stack['rbac']
        self.neutron_client = mock.MagicMock()
        self.rbac.client = mock.MagicMock()
        self.rbac.client.return_value = self.neutron_client

    def _test_create(self, obj_type='network'):
        tpl = yaml.safe_load(inline_templates.RBAC_TEMPLATE)
        tpl['resources']['rbac']['properties']['object_type'] = obj_type
        self._create_stack(tmpl=yaml.safe_dump(tpl))
        expected = {
            "rbac_policy": {
                "action": "access_as_shared",
                "object_type": obj_type,
                "object_id": "9ba4c03a-dbd5-4836-b651-defa595796ba",
                "target_tenant": "d1dbbed707e5469da9cd4fdd618e9706"
            }
        }
        self.rbac.handle_create()
        self.neutron_client.create_rbac_policy.assert_called_with(expected)

    def test_create_network_rbac(self):
        self._test_create()

    def test_create_qos_policy_rbac(self):
        self._test_create(obj_type='qos_policy')

    def _test_validate_invalid_action(self, msg,
                                      invalid_action='invalid',
                                      obj_type='network'):
        tpl = yaml.safe_load(inline_templates.RBAC_TEMPLATE)
        tpl['resources']['rbac']['properties']['action'] = invalid_action
        tpl['resources']['rbac']['properties']['object_type'] = obj_type
        self._create_stack(tmpl=yaml.safe_dump(tpl))

        self.patchobject(type(self.rbac), 'is_service_available',
                         return_value=(True, None))

        self.assertRaisesRegex(exception.StackValidationFailed, msg,
                               self.rbac.validate)

    def test_validate_action_for_network(self):
        msg = ('Property error: resources.rbac.properties.action: '
               '"invalid" is not an allowed value '
               r'\[access_as_shared, access_as_external\]')
        self._test_validate_invalid_action(msg)

    def test_validate_action_for_qos_policy(self):
        msg = ('Property error: resources.rbac.properties.action: '
               '"invalid" is not an allowed value '
               r'\[access_as_shared, access_as_external\]')
        self._test_validate_invalid_action(msg, obj_type='qos_policy')
        # we dont support access_as_external for qos_policy
        msg = ('Property error: resources.rbac.properties.action: '
               'Invalid action "access_as_external" for object type '
               'qos_policy. Valid actions: access_as_shared')
        self._test_validate_invalid_action(msg,
                                           obj_type='qos_policy',
                                           invalid_action='access_as_external')

    def test_validate_invalid_type(self):
        tpl = yaml.safe_load(inline_templates.RBAC_TEMPLATE)
        tpl['resources']['rbac']['properties']['object_type'] = 'networks'
        self._create_stack(tmpl=yaml.safe_dump(tpl))
        msg = '"networks" is not an allowed value'

        self.patchobject(type(self.rbac), 'is_service_available',
                         return_value=(True, None))

        self.assertRaisesRegex(exception.StackValidationFailed, msg,
                               self.rbac.validate)

    def test_validate_object_id_reference(self):
        self._create_stack(tmpl=inline_templates.RBAC_REFERENCE_TEMPLATE)

        self.patchobject(type(self.rbac), 'is_service_available',
                         return_value=(True, None))

        # won't check the object_id, so validate() is success
        self.rbac.validate()

    def test_update(self):
        self._create_stack()
        self.rbac.resource_id_set('bca25c0e-5937-4341-a911-53e202629269')
        prop_diff = {
            'target_tenant': '77485d3b002b4e0c9e8b37fac7261842'
        }
        self.rbac.handle_update(None, None, prop_diff)
        self.neutron_client.update_rbac_policy.assert_called_with(
            'bca25c0e-5937-4341-a911-53e202629269', {'rbac_policy': prop_diff})

    def test_delete(self):
        self._create_stack()
        self.rbac.resource_id_set('bca25c0e-5937-4341-a911-53e202629269')
        self.rbac.handle_delete()
        self.neutron_client.delete_rbac_policy.assert_called_with(
            'bca25c0e-5937-4341-a911-53e202629269')

    def test_delete_failed(self):
        self._create_stack()
        self.rbac.resource_id_set('bca25c0e-5937-4341-a911-53e202629269')
        self.neutron_client.delete_rbac_policy.side_effect = (
            exceptions.Unauthorized)
        self.assertRaises(exceptions.Unauthorized, self.rbac.handle_delete)

    def test_delete_not_found(self):
        self._create_stack()
        self.rbac.resource_id_set('bca25c0e-5937-4341-a911-53e202629269')
        self.neutron_client.delete_rbac_policy.side_effect = (
            exceptions.NotFound())
        self.assertIsNone(self.rbac.handle_delete())

    def test_show_resource(self):
        self._create_stack()
        self.rbac.resource_id_set('1234')
        self.neutron_client.show_rbac_policy.return_value = {
            'rbac_policy': {'id': '123'}
        }
        self.assertEqual(self.rbac._show_resource(), {'id': '123'})
        self.neutron_client.show_rbac_policy.assert_called_with('1234')
