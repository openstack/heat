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
from heat.engine.resources.openstack.octavia import availability_zone_profile
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class AvailabilityZoneProfileTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = availability_zone_profile.resource_mapping()
        self.assertEqual(
            availability_zone_profile.AvailabilityZoneProfile,
            mapping['OS::Octavia::AvailabilityZoneProfile'],
        )

    def _create_stack(
        self, tmpl=inline_templates.AVAILABILITY_ZONE_PROFILE_TEMPLATE
    ):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.az = self.stack['availability_zone_profile']

        self.octavia_client = mock.MagicMock()
        self.az.client = mock.MagicMock()
        self.az.client.return_value = self.octavia_client

        self.az.resource_id_set('1234')
        self.patchobject(
            self.az, 'physical_resource_name', return_value='resource_name'
        )

    def test_create(self):
        self._create_stack()
        expected = {
            'availability_zone_profile': {
                'name': 'test_availability_zone_profile',
                'availability_zone_data': '{"compute_zone": "az-central"}',
                'provider_name': 'amphora',
            }
        }

        self.az.handle_create()

        self.octavia_client.availabilityzoneprofile_create.assert_called_with(
            json=expected
        )

    def test_show_resource(self):
        self._create_stack()
        self.octavia_client.availabilityzoneprofile_show.return_value = {
            'id': 'azp_id_1234'
        }
        self.assertEqual({'id': 'azp_id_1234'}, self.az._show_resource())

        self.octavia_client.availabilityzoneprofile_show.assert_called_with(
            '1234'
        )

    def test_update(self):
        self._create_stack()
        prop_diff = {
            'name': 'test_availability_zone_profile2',
            'availability_zone_data': '{"compute_zone": "az-edge2"}',
            'provider_name': 'amphora2',
        }

        self.az.handle_update(None, None, prop_diff)

        octavia_client = self.octavia_client
        octavia_client.availabilityzoneprofile_set.assert_called_once_with(
            '1234', json={'availability_zone_profile': prop_diff}
        )

        octavia_client.availabilityzoneprofile_set.reset_mock()

        # Updating an availability zone with None as name should use
        # physical_resource_name() as new name
        prop_diff = {
            'name': None,
            'availability_zone_data': '{"compute_zone": "az-edge3"}',
            'provider_name': 'amphora3',
        }

        self.az.handle_update(None, None, prop_diff)

        self.assertEqual(prop_diff['name'], 'resource_name')
        octavia_client.availabilityzoneprofile_set.assert_called_once_with(
            '1234', json={'availability_zone_profile': prop_diff}
        )

    def test_delete(self):
        self._create_stack()

        self.az.handle_delete()

        self.octavia_client.availabilityzoneprofile_delete.assert_called_with(
            '1234'
        )
