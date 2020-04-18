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

from unittest import mock

from heat.common import template_format
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class FlavorProfileTest(common.HeatTestCase):

    def _create_stack(self, tmpl=inline_templates.FLAVORPROFILE_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.flavor_profile = self.stack['flavor_profile']

        self.octavia_client = mock.MagicMock()
        self.flavor_profile.client = mock.MagicMock()
        self.flavor_profile.client.return_value = self.octavia_client

        self.flavor_profile.client_plugin().client = mock.MagicMock(
            return_value=self.octavia_client)
        self.patchobject(self.flavor_profile, 'physical_resource_name',
                         return_value='resource_name')

    def test_create(self):
        self._create_stack()
        self.octavia_client.flavorprofile_show.side_effect = [
            {'flavorprofile': {'id': 'fp123'}}
        ]
        expected = {
            'flavorprofile': {
                'name': 'test_flavor_profile',
                'provider_name': 'test_provider',
                'flavor_data': '{"flavor_data_key": "flavor_data_value"}\n'
            }
        }

        self.flavor_profile.handle_create()

        self.octavia_client.flavorprofile_create.assert_called_with(
            json=expected)

    def test_update(self):
        self._create_stack()
        self.flavor_profile.resource_id_set('f123')
        prop_diff = {
            'name': 'test_flavor_profile2',
            'provider_name': 'test_provider2',
            'flavor_data': '{"flavor_data_key2": "flavor_data_value2"}\n'
        }

        self.flavor_profile.handle_update(None, None, prop_diff)

        self.octavia_client.flavorprofile_set.assert_called_once_with(
            'f123', json={'flavorprofile': prop_diff})

        self.octavia_client.flavorprofile_set.reset_mock()

        # Updating a flavor profile with None as name should use
        # physical_resource_name() as new name
        prop_diff = {
            'name': None,
            'provider_name': 'test_provider3',
            'flavor_data': '{"flavor_data_key3": "flavor_data_value3"}\n'
        }

        self.flavor_profile.handle_update(None, None, prop_diff)

        self.assertEqual(prop_diff['name'], 'resource_name')
        self.octavia_client.flavorprofile_set.assert_called_once_with(
            'f123', json={'flavorprofile': prop_diff})

    def test_delete(self):
        self._create_stack()
        self.flavor_profile.resource_id_set('f123')

        self.flavor_profile.handle_delete()

        self.octavia_client.flavorprofile_delete.assert_called_with('f123')
