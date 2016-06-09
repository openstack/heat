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

from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine import rsrc_defn
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

address_scope_template = '''
heat_template_version: 2016-04-08
description: This template to define a neutron address scope.
resources:
  my_address_scope:
    type: OS::Neutron::AddressScope
    properties:
      shared: False
      tenant_id: d66c74c01d6c41b9846088c1ad9634d0
'''


class NeutronAddressScopeTest(common.HeatTestCase):
    def setUp(self):
        super(NeutronAddressScopeTest, self).setUp()

        self.ctx = utils.dummy_context()
        tpl = template_format.parse(address_scope_template)
        self.stack = stack.Stack(
            self.ctx,
            'neutron_address_scope_test',
            template.Template(tpl)
        )

        self.neutronclient = mock.MagicMock()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.my_address_scope = self.stack['my_address_scope']
        self.my_address_scope.client = mock.MagicMock(
            return_value=self.neutronclient)
        self.patchobject(self.my_address_scope, 'physical_resource_name',
                         return_value='test_address_scope')

    def test_address_scope_handle_create(self):
        addrs = {
            'address_scope': {
                'id': '9c1eb3fe-7bba-479d-bd43-1d497e53c384',
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0',
                'shared': False,
                'ip_version': 4
            }
        }
        create_props = {'name': 'test_address_scope',
                        'shared': False,
                        'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0',
                        'ip_version': 4}

        self.neutronclient.create_address_scope.return_value = addrs
        self.my_address_scope.handle_create()
        self.assertEqual('9c1eb3fe-7bba-479d-bd43-1d497e53c384',
                         self.my_address_scope.resource_id)
        self.neutronclient.create_address_scope.assert_called_once_with(
            {'address_scope': create_props}
        )

    def test_address_scope_handle_delete(self):
        addrs_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.my_address_scope.resource_id = addrs_id
        self.neutronclient.delete_address_scope.return_value = None

        self.assertIsNone(self.my_address_scope.handle_delete())
        self.neutronclient.delete_address_scope.assert_called_once_with(
            self.my_address_scope.resource_id)

    def test_address_scope_handle_delete_not_found(self):
        addrs_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.my_address_scope.resource_id = addrs_id
        not_found = self.neutronclient.NotFound
        self.neutronclient.delete_address_scope.side_effect = not_found

        self.assertIsNone(self.my_address_scope.handle_delete())
        self.neutronclient.delete_address_scope.assert_called_once_with(
            self.my_address_scope.resource_id)

    def test_address_scope_handle_delete_resource_id_is_none(self):
        self.my_address_scope.resource_id = None
        self.assertIsNone(self.my_address_scope.handle_delete())
        self.assertEqual(0,
                         self.neutronclient.delete_address_scope.call_count)

    def test_address_scope_handle_update(self):
        addrs_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.my_address_scope.resource_id = addrs_id

        props = {
            'name': 'test_address_scope',
            'shared': True
        }

        update_dict = props.copy()
        update_snippet = rsrc_defn.ResourceDefinition(
            self.my_address_scope.name,
            self.my_address_scope.type(),
            props)

        # with name
        self.my_address_scope.handle_update(
            json_snippet=update_snippet,
            tmpl_diff={},
            prop_diff=props)

        # without name
        props['name'] = None
        self.my_address_scope.handle_update(
            json_snippet=update_snippet,
            tmpl_diff={},
            prop_diff=props)
        self.assertEqual(2, self.neutronclient.update_address_scope.call_count)
        self.neutronclient.update_address_scope.assert_called_with(
            addrs_id, {'address_scope': update_dict})

    def test_address_scope_get_attr(self):
        self.my_address_scope.resource_id = 'addrs_id'
        addrs = {
            'address_scope': {
                'name': 'test_addrs',
                'id': '9c1eb3fe-7bba-479d-bd43-1d497e53c384',
                'tenant_id': 'd66c74c01d6c41b9846088c1ad9634d0',
                'shared': True,
                'ip_version': 4
            }
        }
        self.neutronclient.show_address_scope.return_value = addrs
        self.assertEqual(addrs['address_scope'],
                         self.my_address_scope.FnGetAtt('show'))
        self.neutronclient.show_address_scope.assert_called_once_with(
            self.my_address_scope.resource_id)
