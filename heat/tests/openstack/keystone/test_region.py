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
from six.moves.urllib import parse

from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import resource
from heat.engine.resources.openstack.keystone import region
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

KEYSTONE_REGION_TEMPLATE = {
    'heat_template_version': '2015-10-15',
    'resources': {
        'test_region': {
            'type': 'OS::Keystone::Region',
            'properties': {
                'id': 'test_region_1',
                'description': 'Test region',
                'parent_region': 'default_region',
                'enabled': 'True'
            }
        }
    }
}


class KeystoneRegionTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneRegionTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(KEYSTONE_REGION_TEMPLATE)
        )

        self.test_region = self.stack['test_region']

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.regions = self.keystoneclient.regions

        keystone_client_plugin = mock.MagicMock()
        self.test_region.client_plugin = mock.MagicMock()
        self.test_region.client_plugin.return_value = keystone_client_plugin

    def _get_mock_region(self):
        value = mock.MagicMock()
        region_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        value.id = region_id

        return value

    def test_region_handle_create(self):
        mock_region = self._get_mock_region()
        self.regions.create.return_value = mock_region

        # validate the properties
        self.assertEqual(
            'test_region_1',
            self.test_region.properties.get(region.KeystoneRegion.ID))
        self.assertEqual(
            'Test region',
            self.test_region.properties.get(
                region.KeystoneRegion.DESCRIPTION))
        self.assertEqual(
            'default_region',
            self.test_region.properties.get(
                region.KeystoneRegion.PARENT_REGION))
        self.assertEqual(
            True,
            self.test_region.properties.get(region.KeystoneRegion.ENABLED))

        self.test_region.handle_create()

        # validate region creation
        self.regions.create.assert_called_once_with(
            id=parse.quote('test_region_1'),
            description='Test region',
            parent_region='default_region',
            enabled=True)

        # validate physical resource id
        self.assertEqual(mock_region.id, self.test_region.resource_id)

    def test_region_handle_create_minimal(self):
        values = {
            'description': 'sample region',
            'enabled': True,
            'parent_region': None,
            'id': None
        }

        def _side_effect(key):
            return values[key]

        mock_region = self._get_mock_region()
        self.regions.create.return_value = mock_region
        self.test_region.properties = mock.MagicMock()
        self.test_region.properties.__getitem__.side_effect = _side_effect

        self.test_region.handle_create()

        self.regions.create.assert_called_once_with(
            id=None,
            description='sample region',
            parent_region=None,
            enabled=True)

    def test_region_handle_update(self):
        self.test_region.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {region.KeystoneRegion.DESCRIPTION:
                     'Test Region updated',
                     region.KeystoneRegion.ENABLED: False,
                     region.KeystoneRegion.PARENT_REGION: 'test_parent_region'}

        self.test_region.handle_update(json_snippet=None,
                                       tmpl_diff=None,
                                       prop_diff=prop_diff)

        self.regions.update.assert_called_once_with(
            region=self.test_region.resource_id,
            description=prop_diff[region.KeystoneRegion.DESCRIPTION],
            enabled=prop_diff[region.KeystoneRegion.ENABLED],
            parent_region='test_parent_region'
        )

    def test_region_get_live_state(self):
        self.test_region.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        mock_dict = mock.MagicMock()
        mock_dict.to_dict.return_value = {
            "parent_region_id": None,
            "enabled": True,
            "id": "79e4d02f8b454a7885c413d5d4297813",
            "links": {"self": "link"},
            "description": ""
        }
        self.regions.get.return_value = mock_dict

        reality = self.test_region.get_live_state(self.test_region.properties)
        expected = {
            "parent_region": None,
            "enabled": True,
            "description": ""
        }
        self.assertEqual(expected, reality)
