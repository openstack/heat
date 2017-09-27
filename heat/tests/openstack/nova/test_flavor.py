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

from heat.engine.clients.os import nova as novac
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

flavor_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'my_flavor': {
            'type': 'OS::Nova::Flavor',
            'properties': {
                'ram': 1024,
                'vcpus': 2,
                'disk': 20,
                'swap': 2,
                'rxtx_factor': 1.0,
                'ephemeral': 0,
                'extra_specs': {"foo": "bar"},
                'tenants': []
            }
        }
    }
}


class NovaFlavorTest(common.HeatTestCase):
    def setUp(self):
        super(NovaFlavorTest, self).setUp()
        self.patchobject(novac.NovaClientPlugin, 'has_extension',
                         return_value=True)
        self.ctx = utils.dummy_context()

    def create_flavor(self, with_name_id=False, is_public=True):
        if with_name_id:
            props = flavor_template['resources']['my_flavor']['properties']
            props['name'] = 'test_flavor'
            props['flavorid'] = '1234'
        if not is_public:
            props = flavor_template['resources']['my_flavor']['properties']
            props['is_public'] = False
            props['tenants'] = ["foo", "bar"]
        self.stack = stack.Stack(
            self.ctx, 'nova_flavor_test_stack',
            template.Template(flavor_template)
        )
        self.my_flavor = self.stack['my_flavor']
        nova = mock.MagicMock()
        self.novaclient = mock.MagicMock()
        self.my_flavor.client = nova
        nova.return_value = self.novaclient
        self.flavors = self.novaclient.flavors

    def test_flavor_handle_create_no_id_name(self):
        self.create_flavor()
        kwargs = {
            'vcpus': 2, 'disk': 20, 'swap': 2,
            'flavorid': 'auto', 'is_public': True,
            'rxtx_factor': 1.0, 'ram': 1024,
            'ephemeral': 0, 'name': 'm1.xxx'
        }
        self.patchobject(self.my_flavor, 'physical_resource_name',
                         return_value='m1.xxx')
        value = mock.MagicMock()
        flavor_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        value.id = flavor_id
        value.is_public = True
        value.get_keys.return_value = {'k': 'v'}
        self.flavors.create.return_value = value
        self.flavors.get.return_value = value
        self.my_flavor.handle_create()
        self.flavors.create.assert_called_once_with(**kwargs)
        value.set_keys.assert_called_once_with({"foo": "bar"})
        self.assertEqual(flavor_id, self.my_flavor.resource_id)
        self.assertTrue(self.my_flavor.FnGetAtt('is_public'))
        self.assertEqual({'k': 'v'}, self.my_flavor.FnGetAtt('extra_specs'))

    def test_flavor_handle_create_with_id_name(self):
        self.create_flavor(with_name_id=True)
        kwargs = {
            'vcpus': 2, 'disk': 20, 'swap': 2,
            'flavorid': '1234', 'is_public': True,
            'rxtx_factor': 1.0, 'ram': 1024,
            'ephemeral': 0, 'name': 'test_flavor'
        }
        self.patchobject(self.my_flavor, 'physical_resource_name',
                         return_value='m1.xxx')
        value = mock.MagicMock()
        flavor_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        value.id = flavor_id
        value.is_public = True
        self.flavors.create.return_value = value
        self.flavors.get.return_value = value
        self.my_flavor.handle_create()
        self.flavors.create.assert_called_once_with(**kwargs)
        value.set_keys.assert_called_once_with({"foo": "bar"})
        self.assertEqual(flavor_id, self.my_flavor.resource_id)
        self.assertTrue(self.my_flavor.FnGetAtt('is_public'))

    def test_private_flavor_handle_create(self):
        self.create_flavor(is_public=False)
        value = mock.MagicMock()
        flavor_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        value.id = flavor_id
        value.is_public = False
        self.flavors.create.return_value = value
        self.flavors.get.return_value = value
        self.my_flavor.handle_create()
        value.set_keys.assert_called_once_with({"foo": "bar"})
        self.assertEqual(flavor_id, self.my_flavor.resource_id)
        self.assertFalse(self.my_flavor.FnGetAtt('is_public'))
        client_test = self.my_flavor.client().flavor_access.add_tenant_access
        test_tenants = [mock.call(value, 'foo'), mock.call(value, 'bar')]
        self.assertEqual(test_tenants, client_test.call_args_list)

    def test_flavor_handle_update_keys(self):
        self.create_flavor()
        value = mock.MagicMock()
        self.flavors.get.return_value = value
        value.get_keys.return_value = {}

        new_keys = {"new_foo": "new_bar"}
        prop_diff = {'extra_specs': new_keys}
        self.my_flavor.handle_update(json_snippet=None,
                                     tmpl_diff=None, prop_diff=prop_diff)
        value.unset_keys.assert_called_once_with({})
        value.set_keys.assert_called_once_with(new_keys)

    def test_flavor_handle_update_add_tenants(self):
        self.create_flavor(is_public=False)
        value = mock.MagicMock()

        new_tenants = ["new_foo", "new_bar"]
        prop_diff = {'tenants': new_tenants}
        self.flavors.get.return_value = value

        self.my_flavor.handle_update(json_snippet=None,
                                     tmpl_diff=None, prop_diff=prop_diff)
        test_tenants_add = [mock.call(value, 'new_foo'),
                            mock.call(value, 'new_bar')]
        test_add = self.my_flavor.client().flavor_access.add_tenant_access
        self.assertItemsEqual(test_tenants_add,
                              test_add.call_args_list)

    def test_flavor_handle_update_remove_tenants(self):
        self.create_flavor(is_public=False)
        value = mock.MagicMock()

        new_tenants = []
        prop_diff = {'tenants': new_tenants}
        self.flavors.get.return_value = value

        itemFoo = mock.MagicMock()
        itemFoo.tenant_id = 'foo'
        itemBar = mock.MagicMock()
        itemBar.tenant_id = 'bar'

        self.my_flavor.client().flavor_access.list.return_value = [itemFoo,
                                                                   itemBar]
        self.my_flavor.handle_update(json_snippet=None,
                                     tmpl_diff=None, prop_diff=prop_diff)
        test_tenants_remove = [mock.call(value, 'foo'),
                               mock.call(value, 'bar')]
        test_rem = self.my_flavor.client().flavor_access.remove_tenant_access
        self.assertItemsEqual(test_tenants_remove,
                              test_rem.call_args_list)

    def test_flavor_show_resource(self):
        self.create_flavor()
        self.my_flavor.resource_id = 'flavor_test_id'
        self.my_flavor.client = mock.MagicMock()
        flavors = mock.MagicMock()
        flavor = mock.MagicMock()
        flavor.to_dict.return_value = {'flavor': 'info'}
        flavors.get.return_value = flavor
        self.my_flavor.client().flavors = flavors
        self.assertEqual({'flavor': 'info'}, self.my_flavor.FnGetAtt('show'))
        flavors.get.assert_called_once_with('flavor_test_id')

    def test_flavor_get_live_state(self):
        self.create_flavor()
        value = mock.MagicMock()
        value.get_keys.return_value = {'key': 'value'}
        value.to_dict.return_value = {'ram': 1024,
                                      'disk': 0,
                                      'vcpus': 1,
                                      'rxtx_factor': 1.0,
                                      'OS-FLV-EXT-DATA:ephemeral': 0,
                                      'os-flavor-access:is_public': True}

        self.flavors.get.return_value = value
        self.my_flavor.resource_id = '1234'

        reality = self.my_flavor.get_live_state(self.my_flavor.properties)
        self.assertEqual({'extra_specs': {'key': 'value'}}, reality)
