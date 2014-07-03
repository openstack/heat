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

from heat.engine import parser
from heat.engine import resource
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import utils

from ..resources.nova_flavor import NovaFlavor  # noqa
from ..resources.nova_flavor import resource_mapping  # noqa
from heat.tests.v1_1 import fakes

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
                'extra_specs': {"foo": "bar"}
            }
        }
    }
}


class NovaFlavorTest(HeatTestCase):
    def setUp(self):
        super(NovaFlavorTest, self).setUp()

        self.ctx = utils.dummy_context()

        # For unit testing purpose. Register resource provider
        # explicitly.
        resource._register_class("OS::Nova::Flavor", NovaFlavor)

        self.stack = parser.Stack(
            self.ctx, 'nova_flavor_test_stack',
            template.Template(flavor_template)
        )

        self.my_flavor = self.stack['my_flavor']
        nova = mock.MagicMock()
        self.novaclient = mock.MagicMock()
        self.my_flavor.nova = nova
        nova.return_value = self.novaclient
        self.flavors = self.novaclient.flavors

    def test_resource_mapping(self):
        mapping = resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(NovaFlavor, mapping['OS::Nova::Flavor'])
        self.assertIsInstance(self.my_flavor, NovaFlavor)

    def test_flavor_handle_create(self):
        value = mock.MagicMock()
        flavor_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        value.id = flavor_id
        self.flavors.create.return_value = value
        self.my_flavor.handle_create()
        value.set_keys.assert_called_once_with({"foo": "bar"})
        self.assertEqual(flavor_id, self.my_flavor.resource_id)

    def test_flavor_handle_update_keys(self):
        value = mock.MagicMock()
        self.flavors.get.return_value = value
        value.get_keys.return_value = {}

        new_keys = {"new_foo": "new_bar"}
        prop_diff = {'extra_specs': new_keys}
        self.my_flavor.handle_update(json_snippet=None,
                                     tmpl_diff=None, prop_diff=prop_diff)
        value.unset_keys.assert_called_once_with({})
        value.set_keys.assert_called_once_with(new_keys)

    def test_flavor_handle_delete(self):
        self.resource_id = None
        self.assertIsNone(self.my_flavor.handle_delete())
        flavor_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        self.my_flavor.resource_id = flavor_id
        self.flavors.delete.return_value = None
        self.assertIsNone(self.my_flavor.handle_delete())
        self.flavors.delete.side_effect = fakes.fake_exception()
        self.assertIsNone(self.my_flavor.handle_delete())
